"""Opt-in checks against the pinned environment prepared by ./install --prefix."""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

PINNED_PYTHON = os.environ.get("CODEX_LB_TEST_PYTHON")
INITIALIZER = Path(__file__).resolve().parents[2] / "scripts/native_initialize.py"


@unittest.skipUnless(PINNED_PYTHON, "Set CODEX_LB_TEST_PYTHON to a prepared 1.24.0 environment.")
class NativeAuthenticationIntegrationTests(unittest.TestCase):
    def test_real_migrations_password_and_client_key_are_local_and_repeat_initialization_is_rejected(self) -> None:
        assert PINNED_PYTHON is not None
        with tempfile.TemporaryDirectory(prefix="codex lb offline auth ") as temporary:
            root = Path(temporary).resolve()
            data = root / "data"
            password = secrets.token_urlsafe(20)
            environment = {"HOME": str(Path.home()), "PATH": "/usr/bin:/bin", "CODEX_LB_DATA_DIR": str(data)}
            command = [PINNED_PYTHON, "-I", "-B", str(INITIALIZER)]
            result = subprocess.run(
                command,
                input=json.dumps({"password": password}),
                env=environment,
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertNotIn(password, result.stdout + result.stderr)
            key = (data / "codex-api-key.txt").read_text().strip()
            self.assertTrue(key.startswith("sk-clb-"))
            self.assertNotIn(key, result.stdout + result.stderr)
            for filename in ("store.db", "encryption.key", "codex-api-key.txt"):
                self.assertEqual((data / filename).stat().st_mode & 0o777, 0o600)
            with sqlite3.connect(data / "store.db") as connection:
                self.assertEqual(connection.execute("PRAGMA quick_check").fetchone(), ("ok",))
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM accounts").fetchone(), (0,))
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM api_keys").fetchone(), (1,))
                self.assertEqual(
                    connection.execute("SELECT api_key_auth_enabled FROM dashboard_settings").fetchone(), (1,)
                )
            # Exercise the release's authentication services, independently of the initializer.
            probe = """
import asyncio, json, sys
from pathlib import Path
from app.db.session import SessionLocal, close_db
from app.modules.dashboard_auth.repository import DashboardAuthRepository
from app.modules.dashboard_auth.service import DashboardAuthService, DashboardSessionStore
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeysService
async def check():
    async with SessionLocal() as session:
        auth = DashboardAuthService(DashboardAuthRepository(session), DashboardSessionStore())
        await auth.verify_password(json.load(sys.stdin)["password"])
        key = Path(__import__("os").environ["CODEX_LB_DATA_DIR"], "codex-api-key.txt").read_text().strip()
        await ApiKeysService(ApiKeysRepository(session)).validate_key(key)
    await close_db()
asyncio.run(check())
"""
            subprocess.run(
                [PINNED_PYTHON, "-I", "-B", "-c", probe],
                input=json.dumps({"password": password}),
                env=environment,
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            )
            before = {
                filename: (data / filename).read_bytes()
                for filename in ("store.db", "encryption.key", "codex-api-key.txt")
            }
            repeated = subprocess.run(
                command,
                input=json.dumps({"password": secrets.token_urlsafe(20)}),
                env=environment,
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(repeated.returncode, 0)
            self.assertIn("FileExistsError", repeated.stderr)
            self.assertEqual({filename: (data / filename).read_bytes() for filename in before}, before)


if __name__ == "__main__":
    unittest.main()
