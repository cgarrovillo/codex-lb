from __future__ import annotations

import json
import signal
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from scripts import macos_launchagent as service
from scripts import native_migrate as migration


class NativeMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        home_patch = patch.object(Path, "home", return_value=self.home)
        home_patch.start()
        self.addCleanup(home_patch.stop)
        self.root = service.installation_root()
        self.root.mkdir(parents=True)
        self.staging = self.home / "old staging"
        self.native = self.staging / ".state/native"
        self.old_data = self.native / "data"
        self.old_data.mkdir(parents=True)
        self.key = b"sk-clb-test-sentinel\n"
        (self.native / "codex-api-key.txt").write_bytes(self.key)
        (self.native / "codex-api-key.txt").chmod(0o600)
        (self.old_data / "encryption.key").write_bytes(b"encryption-sentinel")
        with closing(sqlite3.connect(self.old_data / "store.db")) as connection, connection:
            connection.executescript(
                "CREATE TABLE accounts(id TEXT); INSERT INTO accounts VALUES ('account-sentinel');"
                "CREATE TABLE api_keys(id TEXT); INSERT INTO api_keys VALUES ('key-sentinel');"
            )
        self.config = self.home / ".codex/config.toml"
        self.config.parent.mkdir()
        self.original_config = (
            'model_provider = "codex-lb"\nmodel = "test-model"\n\n'
            '[model_providers.codex-lb]\nbase_url = "http://127.0.0.1:2455/backend-api/codex"\n\n'
            "[model_providers.codex-lb.auth]\ncommand = "
            + json.dumps(str(self.staging / "bin/read-proxy-key"))
            + '\nargs = []\n\n[other]\nvalue = "keep-this"\n'
        )
        self.config.write_text(self.original_config)
        release = self.root / "releases/test release"
        app = release / "venv/site-packages/app"
        config = release / "venv/site-packages/config"
        app.mkdir(parents=True)
        config.mkdir()
        (app / "__init__.py").write_text("")
        (config / "version").write_text("1.24.0")
        python = release / "venv/bin/python"
        python.parent.mkdir()
        python.symlink_to(sys.executable)
        receipt = {
            "source_commit": "a" * 40,
            "release_dir": str(release),
            "venv_python": str(python),
            "app_dir": str(app),
            "config_dir": str(config),
            "app_sha256": migration.tree_digest(app),
            "config_sha256": migration.tree_digest(config),
            "version": "1.24.0",
        }
        (self.root / "release.json").write_text(json.dumps(receipt))
        (self.native / "release.json").write_text(json.dumps(receipt))
        (self.root / "migration-source.json").write_text(json.dumps({"staging": str(self.staging)}))
        self.old_identity = "Fri 20 Nov 15:03:10 2026 /test/python -I -B -m app.cli --port 2455"
        self.new_identity = "Fri Nov 20 15:03:10 2026 /test/python -I -B -m app.cli --port 2455"
        (self.native / "process.json").write_text(
            json.dumps({"pid": 12345, "identity": self.old_identity, "release_dir": str(release)})
        )
        for replacement in (
            patch.object(service, "registered_job", return_value=None),
            patch.object(service, "require_free_port"),
            patch.object(service, "install"),
            patch.object(service, "wait_ready"),
        ):
            replacement.start()
            self.addCleanup(replacement.stop)
        identity_patch = patch.object(
            migration, "process_identity", side_effect=[self.new_identity, self.new_identity, ""]
        )
        identity_patch.start()
        self.addCleanup(identity_patch.stop)
        kill_patch = patch.object(migration.os, "kill")
        self.kill = kill_patch.start()
        self.addCleanup(kill_patch.stop)

    def test_migration_handles_locale_change_and_preserves_credentials(self) -> None:
        migration.activate()
        self.kill.assert_called_once_with(12345, signal.SIGTERM)
        data = self.home / ".codex-lb"
        self.assertEqual((data / "codex-api-key.txt").read_bytes(), self.key)
        self.assertEqual((data / "encryption.key").read_bytes(), b"encryption-sentinel")
        self.assertEqual(migration.data_signature(data), (1, 1))
        state = json.loads((self.root / "activation.json").read_text())
        self.assertEqual(state["phase"], "activated")
        backup = Path(state["backup"])
        self.assertEqual((backup / "codex-config.toml").read_text(), self.original_config)
        self.assertEqual((self.old_data / "encryption.key").read_bytes(), b"encryption-sentinel")
        self.assertIn('value = "keep-this"', self.config.read_text())
        self.assertIn(str(self.home / ".local/bin/codex-lb-read-key"), self.config.read_text())

    def test_existing_destination_blocks_before_process_signal(self) -> None:
        (self.home / ".codex-lb").mkdir()
        with self.assertRaisesRegex(ValueError, "already exists"):
            migration.activate()
        self.kill.assert_not_called()
        self.assertEqual(self.config.read_text(), self.original_config)

    def test_identity_mismatch_never_stops_another_process(self) -> None:
        with patch.object(
            migration, "process_identity", return_value=self.new_identity.replace("15:03:10", "15:04:10")
        ):
            with self.assertRaisesRegex(ValueError, "identity changed"):
                migration.activate()
        self.kill.assert_not_called()

    def test_invalid_pid_never_signals_a_process_group(self) -> None:
        with self.assertRaisesRegex(ValueError, "PID is invalid"):
            migration.validate_old_process({"pid": -1, "identity": self.old_identity})
        self.kill.assert_not_called()

    def test_registration_failure_keeps_original_config_and_backup(self) -> None:
        with patch.object(service, "install", side_effect=RuntimeError("registration failed")):
            with self.assertRaisesRegex(RuntimeError, "registration failed"):
                migration.activate()
        self.assertEqual(self.config.read_text(), self.original_config)
        state = json.loads((self.root / "activation.json").read_text())
        self.assertEqual(state["phase"], "data copied")
        self.assertTrue((Path(state["backup"]) / "data/store.db").is_file())

    def test_rollback_restores_config_and_retains_both_data_directories(self) -> None:
        migration.activate()
        with closing(sqlite3.connect(self.home / ".codex-lb/store.db")) as connection, connection:
            connection.execute("INSERT INTO accounts VALUES ('new-account')")
        with patch.object(service, "uninstall") as remove, patch.object(migration.subprocess, "run") as run:
            migration.rollback()
        remove.assert_called_once()
        self.assertEqual(self.config.read_text(), self.original_config)
        self.assertTrue((self.home / ".codex-lb/store.db").is_file())
        self.assertTrue((self.old_data / "store.db").is_file())
        self.assertEqual(migration.data_signature(self.old_data), (2, 1))
        command = run.call_args.args[0]
        self.assertEqual(command[-1], "start")
        self.assertEqual(command[-2], str(self.staging / "bin/native.py"))

    def test_rollback_refuses_to_overwrite_later_config_edits(self) -> None:
        migration.activate()
        self.config.write_text(self.config.read_text() + "\n# later edit\n")
        with patch.object(service, "uninstall") as remove:
            with self.assertRaisesRegex(ValueError, "changed after activation"):
                migration.rollback()
        remove.assert_not_called()

    def test_unsafe_key_permissions_block_before_process_signal(self) -> None:
        (self.native / "codex-api-key.txt").chmod(0o644)
        with self.assertRaisesRegex(ValueError, "mode 0600"):
            migration.activate()
        self.kill.assert_not_called()

    def test_config_change_is_limited_to_the_provider_helper(self) -> None:
        replacement = self.home / "a different directory/read-key"
        changed = migration.migrated_config(self.original_config, self.staging / "bin/read-proxy-key", replacement)
        self.assertEqual(
            changed.replace(json.dumps(str(replacement)), json.dumps(str(self.staging / "bin/read-proxy-key"))),
            self.original_config,
        )


if __name__ == "__main__":
    unittest.main()
