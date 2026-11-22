from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import prepare_native as prepare


class NativePreparationTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="codex lb preparation ")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        replacement = patch.object(Path, "home", return_value=self.home)
        replacement.start()
        self.addCleanup(replacement.stop)
        self.destination = self.home / "Library/Application Support/codex-lb"
        self.python = self.home / "release with spaces/bin/python"
        self.python.parent.mkdir(parents=True)
        self.python.symlink_to(sys.executable)

    def test_installed_commands_work_without_the_source_checkout_or_shell_environment(self) -> None:
        prepare.install_tools(self.destination, self.python)
        command = self.home / ".local/bin/codex-lb"
        result = subprocess.run([str(command), "--help"], cwd="/", capture_output=True, text=True, check=True)
        self.assertIn("restart", result.stdout)
        self.assertIn("usage: codex-lb", result.stdout)
        self.assertIn("logs", result.stdout)
        self.assertNotIn(str(prepare.ROOT), command.read_text())
        self.assertFalse((self.home / ".codex-lb").exists())
        self.assertFalse((self.home / "Library/LaunchAgents").exists())

    def test_existing_unrelated_command_is_preserved_before_any_tool_copy(self) -> None:
        target = self.home / ".local/bin/codex-lb"
        target.parent.mkdir(parents=True)
        target.write_text("unrelated command")
        with self.assertRaisesRegex(ValueError, "Refusing to replace"):
            prepare.install_tools(self.destination, self.python)
        self.assertEqual(target.read_text(), "unrelated command")
        self.assertFalse((self.destination / "manager").exists())

    def test_tool_refresh_preserves_known_launchers(self) -> None:
        prepare.install_tools(self.destination, self.python)
        before = (self.home / ".local/bin/codex-lb").read_bytes()
        prepare.install_tools(self.destination, self.python)
        self.assertEqual((self.home / ".local/bin/codex-lb").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
