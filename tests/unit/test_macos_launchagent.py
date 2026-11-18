from __future__ import annotations

import contextlib
import io
import json
import os
import plistlib
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import macos_launchagent as service


class LaunchAgentCliTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        self.data = self.home / "existing data"
        self.data.mkdir()
        (self.data / "store.db").write_bytes(b"database sentinel")
        (self.data / "encryption.key").write_bytes(b"key sentinel")
        self.python = self.home / "venv/bin/python"
        self.python.parent.mkdir(parents=True)
        self.python.symlink_to(sys.executable)
        self.loaded = False
        self.bootstrap_failure = False
        self.bootstrap_timeout = False
        self.bootout_failure = False
        self.calls: list[list[str]] = []
        self.probe_environment: dict[str, str] = {}
        for replacement in (
            patch.object(service.sys, "platform", "darwin"),
            patch.object(service.Path, "home", return_value=self.home),
            patch.object(service.subprocess, "run", side_effect=self.run_process),
            patch.object(service.socket, "create_connection", side_effect=ConnectionRefusedError),
        ):
            replacement.start()
            self.addCleanup(replacement.stop)

    def run_process(self, command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        self.calls.append(command)
        if command[0] == str(self.python):
            self.probe_environment = kwargs["env"]
            return subprocess.CompletedProcess(command, 0, "", "")
        self.assertEqual(command[0], "/bin/launchctl")
        if command[1] == "print":
            if self.loaded:
                output = "state = running\n pid = 123\n environment = {\nIGNORED_SECRET = hidden\n}\n"
                return subprocess.CompletedProcess(command, 0, output, "")
            return subprocess.CompletedProcess(command, 113, "", "Could not find service")
        if command[1] == "bootstrap":
            if self.bootstrap_timeout:
                self.loaded = True
                raise subprocess.TimeoutExpired(command, 20)
            if self.bootstrap_failure:
                return subprocess.CompletedProcess(command, 5, "", "registration rejected")
            self.loaded = True
        if command[1] == "bootout":
            if self.bootout_failure:
                return subprocess.CompletedProcess(command, 5, "", "removal rejected")
            self.loaded = False
        return subprocess.CompletedProcess(command, 0, "", "")

    def invoke(self, *args: str) -> tuple[int, str, str]:
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = service.main(args)
        return code, output.getvalue(), errors.getvalue()

    def install(self, *extra: str) -> tuple[int, str, str]:
        return self.invoke("install", "--python", str(self.python), "--data-dir", str(self.data), *extra)

    def test_preview_preserves_venv_and_excludes_credentials_without_writes(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "credential-sentinel", "GITHUB_TOKEN": "github-sentinel"}):
            code, output, errors = self.install("--dry-run")
        self.assertEqual((code, errors), (0, ""))
        plist = plistlib.loads(output.encode())
        self.assertEqual(plist["ProgramArguments"][0], str(self.python))
        self.assertNotEqual(plist["ProgramArguments"][0], str(self.python.resolve()))
        self.assertEqual(plist["WorkingDirectory"], str(self.data))
        self.assertEqual(plist["EnvironmentVariables"]["CODEX_LB_DATA_DIR"], str(self.data))
        self.assertNotIn("credential-sentinel", output)
        self.assertNotIn("github-sentinel", output)
        self.assertNotIn("OPENAI_API_KEY", output)
        self.assertEqual(set(self.probe_environment), {"HOME", "PATH"})
        self.assertFalse((self.home / "Library").exists())
        self.assertEqual(len(self.calls), 1)

    def test_install_registers_foreground_server_with_private_files(self) -> None:
        code, _, errors = self.install()
        self.assertEqual((code, errors), (0, ""))
        plist = plistlib.loads(service.plist_path().read_bytes())
        self.assertEqual(
            plist["ProgramArguments"],
            [str(self.python), "-I", "-B", "-m", "app.cli", "--host", "127.0.0.1", "--port", "2455"],
        )
        self.assertTrue(plist["RunAtLoad"])
        self.assertTrue(plist["KeepAlive"])
        self.assertEqual(plist["Umask"], 0o077)
        self.assertEqual(stat.S_IMODE(service.plist_path().stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(Path(plist["StandardOutPath"]).stat().st_mode), 0o600)
        self.assertEqual(
            self.calls[-1], ["/bin/launchctl", "bootstrap", f"gui/{os.getuid()}", str(service.plist_path())]
        )
        self.assertEqual((self.data / "store.db").read_bytes(), b"database sentinel")
        self.assertEqual((self.data / "encryption.key").read_bytes(), b"key sentinel")

    def test_existing_plist_is_preserved(self) -> None:
        target = service.plist_path()
        target.parent.mkdir(parents=True)
        target.write_text("existing job")
        code, _, errors = self.install()
        self.assertEqual(code, 1)
        self.assertIn("already exists", errors)
        self.assertEqual(target.read_text(), "existing job")
        self.assertFalse(any(command[1] == "bootstrap" for command in self.calls))

    def test_existing_registered_job_is_preserved(self) -> None:
        self.loaded = True
        code, _, errors = self.install()
        self.assertEqual(code, 1)
        self.assertIn("already exists", errors)
        self.assertFalse(service.plist_path().exists())

    def test_occupied_port_blocks_installation(self) -> None:
        with patch.object(service.socket, "create_connection"):
            code, _, errors = self.install()
        self.assertEqual(code, 1)
        self.assertIn("Port 2455 is occupied", errors)
        self.assertFalse(service.plist_path().exists())

    def test_port_inspection_failure_does_not_start_server(self) -> None:
        with patch.object(service.socket, "create_connection", side_effect=PermissionError):
            code, _, errors = self.install()
        self.assertEqual(code, 1)
        self.assertIn("Cannot check port", errors)
        self.assertFalse(service.plist_path().exists())

    def test_failed_registration_removes_new_plist(self) -> None:
        self.bootstrap_failure = True
        code, _, errors = self.install()
        self.assertEqual(code, 1)
        self.assertIn("could not confirm registration", errors)
        self.assertFalse(service.plist_path().exists())
        self.assertTrue((self.data / "store.db").is_file())

    def test_ambiguous_registration_timeout_keeps_recovery_plist(self) -> None:
        self.bootstrap_timeout = True
        code, _, errors = self.install()
        self.assertEqual(code, 1)
        self.assertIn("timed out", errors)
        self.assertTrue(service.plist_path().is_file())

    def test_uninstall_preserves_data_and_logs(self) -> None:
        self.assertEqual(self.install()[0], 0)
        plist = plistlib.loads(service.plist_path().read_bytes())
        code, _, errors = self.invoke("uninstall")
        self.assertEqual((code, errors), (0, ""))
        self.assertFalse(service.plist_path().exists())
        self.assertFalse(self.loaded)
        self.assertTrue((self.data / "store.db").is_file())
        self.assertTrue((self.data / "encryption.key").is_file())
        self.assertTrue(Path(plist["StandardOutPath"]).is_file())

    def test_failed_uninstall_preserves_plist(self) -> None:
        self.assertEqual(self.install()[0], 0)
        self.bootout_failure = True
        code, _, errors = self.invoke("uninstall")
        self.assertEqual(code, 1)
        self.assertIn("retained", errors)
        self.assertTrue(service.plist_path().is_file())

    def test_status_distinguishes_installed_from_registered_without_env_output(self) -> None:
        self.assertEqual(self.install()[0], 0)
        code, output, errors = self.invoke("status")
        self.assertEqual((code, errors), (0, ""))
        self.assertEqual(json.loads(output), {"installed": True, "registered": True, "state": "running", "pid": "123"})
        self.assertNotIn("IGNORED_SECRET", output)
        self.loaded = False
        self.assertEqual(json.loads(self.invoke("status")[1]), {"installed": True, "registered": False})

    def test_missing_data_is_rejected_without_filesystem_mutations(self) -> None:
        (self.data / "encryption.key").unlink()
        code, _, errors = self.install()
        self.assertEqual(code, 1)
        self.assertIn("Select existing application data", errors)
        self.assertFalse((self.home / "Library").exists())

    def test_missing_python_is_rejected(self) -> None:
        self.python.unlink()
        code, _, errors = self.install()
        self.assertEqual(code, 1)
        self.assertIn("executable Python", errors)

    def test_other_operating_systems_are_rejected(self) -> None:
        with patch.object(service.sys, "platform", "linux"):
            code, _, errors = self.install()
        self.assertEqual(code, 1)
        self.assertIn("requires macOS", errors)
        self.assertEqual(self.calls, [])

    def test_unavailable_launchd_domain_is_reported_without_installation(self) -> None:
        result = subprocess.CompletedProcess([], 1, "", "Could not find domain")
        with patch.object(service, "launchctl", return_value=result):
            code, _, errors = self.install()
        self.assertEqual(code, 1)
        self.assertIn("macOS login session", errors)
        self.assertFalse(service.plist_path().exists())


if __name__ == "__main__":
    unittest.main()
