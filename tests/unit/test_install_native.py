from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from scripts import install_native as installer
from scripts import macos_launchagent as service
from scripts import native_activate as activation
from scripts import native_migrate, prepare_native


class InstallationFixture(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="portable codex lb ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / "installation"
        self.root.mkdir()
        self.manifest = json.loads((prepare_native.ROOT / "deploy/macos-native.json").read_text())
        for replacement in (
            patch.object(installer.platform, "system", return_value="Darwin"),
            patch.object(installer.platform, "machine", return_value="arm64"),
            patch.object(service, "installation_root", return_value=self.root),
        ):
            replacement.start()
            self.addCleanup(replacement.stop)

    def built_release(self, *args) -> dict:
        release = self.root / "releases/test"
        app = release / "venv/app"
        config = release / "venv/config"
        app.mkdir(parents=True)
        config.mkdir()
        (app / "sentinel").write_text("application")
        python = release / "venv/bin/python"
        python.parent.mkdir()
        python.symlink_to(sys.executable)
        return {
            "release_dir": str(release),
            "version": self.manifest["application"]["version"],
            "source_commit": self.manifest["application"]["commit"],
            "venv_python": str(python),
            "app_dir": str(app),
            "app_sha256": prepare_native.tree_digest(app),
            "config_dir": str(config),
            "config_sha256": prepare_native.tree_digest(config),
        }

    def prepare(self) -> None:
        with (
            patch.object(installer, "install_bun", return_value=self.root / "bun"),
            patch.object(installer.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)),
            patch.object(prepare_native, "build_release", side_effect=self.built_release),
            patch.object(service, "launchctl", side_effect=AssertionError("Preparation must not inspect launchd")),
        ):
            installer.prepare(self.root, Path("/verified/uv"), True)


class PortableInstallationTests(InstallationFixture):
    def test_empty_install_needs_no_staging_and_reuses_release_without_touching_data(self) -> None:
        self.prepare()
        self.assertFalse((self.root / "migration-source.json").exists())
        self.assertFalse((self.root / "data").exists())
        self.assertFalse((self.root / "LaunchAgents").exists())
        receipt = (self.root / "release.json").read_bytes()
        data = self.root / "data"
        data.mkdir()
        key = data / "codex-api-key.txt"
        key.write_text("sk-clb-fixture-local-key")
        key.chmod(0o600)
        config = self.root / "codex/config.toml"
        config.parent.mkdir()
        config.write_text("# user configuration\n")
        with patch.object(prepare_native, "build_release", side_effect=AssertionError("No rebuild")):
            installer.prepare(self.root, Path("/verified/uv"), True)
        self.assertEqual((self.root / "release.json").read_bytes(), receipt)
        self.assertEqual(config.read_text(), "# user configuration\n")
        # The installed helper must select fixture data, even outside the checkout.
        result = subprocess.run(
            [str(self.root / "bin/codex-lb-read-key")], cwd="/", capture_output=True, text=True, check=True
        )
        self.assertEqual(result.stdout, "sk-clb-fixture-local-key")
        for command in ("codex-lb", "codex-lb-activate"):
            result = subprocess.run(
                [str(self.root / "bin" / command), "--help"], capture_output=True, text=True, check=True
            )
            self.assertIn("usage", result.stdout)

    def test_unrecorded_data_is_preserved(self) -> None:
        (self.root / "data").mkdir()
        with self.assertRaisesRegex(ValueError, "Existing data"):
            self.prepare()
        self.assertFalse((self.root / "release.json").exists())

    def test_modified_release_is_not_refreshed(self) -> None:
        self.prepare()
        (self.root / "releases/test/venv/app/sentinel").write_text("modified")
        with self.assertRaisesRegex(ValueError, "files changed"):
            installer.prepare(self.root, Path("/verified/uv"), True)

    def test_legacy_receipt_retains_migration_mode(self) -> None:
        self.prepare()
        path = self.root / "release.json"
        record = json.loads(path.read_text())
        del record["installation_mode"]
        del record["paths"]
        path.write_text(json.dumps(record))
        with patch.object(prepare_native, "install_tools") as tools:
            installer.prepare(self.root, Path("/verified/uv"), False)
        self.assertNotIn("installation_mode", json.loads(path.read_text()))
        self.assertEqual(tools.call_args.args[2], Path.home() / ".local/bin")

    def test_bun_architectures_and_checksum_failure(self) -> None:
        for architecture in ("arm64", "x86_64"):
            manifest = self.manifest.copy()
            selected = manifest["bun"][architecture].copy()
            content = io.BytesIO()
            with zipfile.ZipFile(content, "w") as archive:
                archive.writestr(selected["asset"].removesuffix(".zip") + "/bun", b"verified executable")
            selected["sha256"] = hashlib.sha256(content.getvalue()).hexdigest()
            manifest["bun"] = {"version": "test", architecture: selected}

            def download(command: list[str], **kwargs) -> None:
                Path(command[-1]).write_bytes(content.getvalue())

            with patch.object(installer.subprocess, "run", side_effect=download):
                executable = installer.install_bun(self.root, manifest, architecture)
                self.assertEqual(executable.read_bytes(), b"verified executable")
                selected["sha256"] = "0" * 64
                with self.assertRaisesRegex(ValueError, "checksum"):
                    installer.install_bun(self.root, manifest, architecture)
                self.assertEqual(executable.read_bytes(), b"verified executable")


class CodexConfigurationTests(unittest.TestCase):
    def test_preserves_tools_preferences_comments_and_other_providers(self) -> None:
        original = """# personal settings
model = "old-model"
model_provider = "openai"
approval_policy = "never"
[mcp_servers.example]
command = "/a path/tool"
[model_providers.other]
name = "other"
"""
        updated = activation.configured_codex(original, Path("/a path/read-key"), {"model": "selected"})
        result = tomllib.loads(updated)
        self.assertEqual(result["model_provider"], "codex-lb")
        self.assertEqual(result["model"], "selected")
        self.assertEqual(result["mcp_servers"], tomllib.loads(original)["mcp_servers"])
        self.assertEqual(result["model_providers"]["other"], {"name": "other"})
        self.assertEqual(result["approval_policy"], "never")
        self.assertIn("# personal settings", updated)
        self.assertEqual(activation.configured_codex(updated, Path("/a path/read-key"), {"model": "selected"}), updated)

    def test_active_profile_cannot_keep_direct_openai_routing(self) -> None:
        original = 'profile = "work"\n[profiles.work]\nmodel_provider = "openai"\napproval_policy = "never"\n'
        result = tomllib.loads(activation.configured_codex(original, Path("/helper"), {"model": "selected"}))
        self.assertEqual(
            result["profiles"]["work"],
            {
                "model_provider": "codex-lb",
                "model": "selected",
                "approval_policy": "never",
            },
        )

    def test_conflicting_credentials_and_unsupported_layouts_fail(self) -> None:
        for content in (
            '[model_providers.codex-lb]\nenv_key = "SECRET_KEY"\n',
            'model_providers = { codex-lb = {name = "old"} }\n',
        ):
            with self.assertRaises(ValueError):
                activation.configured_codex(content, Path("/helper"), {"model": "selected"})


class FreshActivationTests(InstallationFixture):
    def setUp(self) -> None:
        super().setUp()
        self.prepare()
        self.calls: list[str] = []
        self.config = self.root / "codex/config.toml"
        self.config.parent.mkdir()
        self.config.write_text('# retained\napproval_policy = "never"\n')
        self.original = self.config.read_bytes()
        self.prompt = Mock(return_value="a fixture password")
        for replacement in (
            patch.object(service, "registered_job", return_value=None),
            patch.object(service, "require_free_port"),
            patch.object(service, "install", side_effect=self.register),
            patch.object(service, "wait_ready", side_effect=lambda: self.calls.append("ready")),
            patch.object(activation.getpass, "getpass", self.prompt),
            patch.object(activation.subprocess, "run", side_effect=self.initialize),
            patch.object(service, "stop", side_effect=lambda: self.calls.append("stop")),
            patch.object(service, "uninstall", side_effect=lambda: service.plist_path().unlink()),
        ):
            replacement.start()
            self.addCleanup(replacement.stop)

    def initialize(self, command: list[str], **kwargs) -> None:
        self.assertNotIn("a fixture password", " ".join(command))
        self.assertNotIn("password", str(kwargs["env"]))
        self.assertIn("password", json.loads(kwargs["input"]))
        data = self.root / "data"
        data.mkdir(mode=0o700)
        key = data / "codex-api-key.txt"
        key.write_text("sk-clb-fixture-secret")
        key.chmod(0o600)
        self.calls.append("initialize")

    def register(self, selected: service.Service) -> None:
        self.assertEqual(self.calls, ["initialize"])
        target = service.plist_path()
        target.parent.mkdir()
        target.write_bytes(selected.plist())
        self.calls.append("register")

    def test_activation_auth_precedes_service_and_config_and_rollback_preserves_data(self) -> None:
        activation.activate()
        self.assertEqual(self.calls, ["initialize", "register", "ready"])
        self.assertEqual(tomllib.loads(self.config.read_text())["model_provider"], "codex-lb")
        self.assertEqual(tomllib.loads(self.config.read_text())["approval_policy"], "never")
        self.assertEqual(os.stat(self.config).st_mode & 0o777, 0o600)
        self.prompt.reset_mock()
        activation.activate()
        self.prompt.assert_not_called()
        activation.rollback()
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertTrue((self.root / "data/codex-api-key.txt").is_file())
        self.assertFalse(service.plist_path().exists())
        self.assertEqual(self.calls[-1], "stop")

    def test_bad_config_is_rejected_before_prompt_or_initialization(self) -> None:
        self.config.write_text('[model_providers.codex-lb]\nenv_key = "SECRET_KEY"\n')
        with self.assertRaisesRegex(ValueError, "conflicting credentials"):
            activation.activate()
        self.assertEqual(self.calls, [])
        self.prompt.assert_not_called()

    def test_new_config_is_created_and_removed_by_rollback(self) -> None:
        self.config.unlink()
        activation.activate()
        self.assertEqual(tomllib.loads(self.config.read_text())["model_provider"], "codex-lb")
        activation.rollback()
        self.assertFalse(self.config.exists())

    def test_rollback_then_retry_preserves_credentials_and_skips_password_prompt(self) -> None:
        activation.activate()
        key = (self.root / "data/codex-api-key.txt").read_bytes()
        activation.rollback()
        self.calls.clear()
        self.prompt.reset_mock()
        with patch.object(service, "install", side_effect=lambda selected: self.calls.append("register")):
            activation.activate()
        self.prompt.assert_not_called()
        self.assertEqual(self.calls, ["register", "ready"])
        self.assertEqual((self.root / "data/codex-api-key.txt").read_bytes(), key)

    def test_concurrent_config_edit_is_preserved(self) -> None:
        def edit_config() -> None:
            self.config.write_text("# concurrent edit\n")

        with patch.object(service, "wait_ready", side_effect=edit_config):
            with self.assertRaisesRegex(ValueError, "changed during activation"):
                activation.activate()
        self.assertEqual(self.config.read_text(), "# concurrent edit\n")
        activation.rollback()
        self.assertEqual(self.config.read_text(), "# concurrent edit\n")

    def test_readiness_failure_preserves_original_config_and_allows_rollback(self) -> None:
        with patch.object(service, "wait_ready", side_effect=RuntimeError("unready")):
            with self.assertRaisesRegex(RuntimeError, "unready"):
                activation.activate()
        self.assertEqual(self.config.read_bytes(), self.original)
        activation.rollback()
        self.assertTrue((self.root / "data/codex-api-key.txt").exists())

    def test_rollback_refuses_to_replace_later_config_edits(self) -> None:
        activation.activate()
        self.config.write_text(self.config.read_text() + "# later change\n")
        with self.assertRaisesRegex(ValueError, "changed after activation"):
            activation.rollback()
        self.assertNotIn("stop", self.calls)

    def test_legacy_dispatch_remains_legacy_and_fresh_dispatch_uses_fresh_activation(self) -> None:
        with (
            patch.object(sys, "argv", ["codex-lb-activate"]),
            patch.object(activation, "activate") as fresh,
            patch.object(native_migrate, "activate") as legacy,
        ):
            self.assertEqual(native_migrate.main(), 0)
            fresh.assert_called_once()
            legacy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
