"""Initialize local authentication offline using the pinned application's APIs."""

from __future__ import annotations

import asyncio
import importlib
import importlib.metadata
import json
import os
import sys
from pathlib import Path


async def initialize(password: str) -> None:
    if importlib.metadata.version("codex-lb") != "1.24.0":
        raise ValueError("The authentication initializer supports only the pinned application version 1.24.0.")
    if not 8 <= len(password.encode()) <= 72:
        raise ValueError("Use a dashboard password containing 8 to 72 UTF-8 bytes.")
    data = Path(os.environ["CODEX_LB_DATA_DIR"])
    data.mkdir(parents=True, mode=0o700)  # Existing data must never be initialized again.
    os.umask(0o077)
    # These interfaces belong to the installed release, independently of checkout main.
    database = importlib.import_module("app.db.session")
    crypto = importlib.import_module("app.core.crypto")
    auth_repository = importlib.import_module("app.modules.dashboard_auth.repository")
    auth_service = importlib.import_module("app.modules.dashboard_auth.service")
    settings_module = importlib.import_module("app.modules.settings.repository")
    keys_repository = importlib.import_module("app.modules.api_keys.repository")
    keys_service = importlib.import_module("app.modules.api_keys.service")
    try:
        await database.init_db()
        crypto.TokenEncryptor()
        async with database.SessionLocal() as session:
            auth = auth_service.DashboardAuthService(
                auth_repository.DashboardAuthRepository(session), auth_service.DashboardSessionStore()
            )
            await auth.setup_password(password)
            settings = settings_module.SettingsRepository(session)
            await settings.update(api_key_auth_enabled=True)
            keys = keys_service.ApiKeysService(keys_repository.ApiKeysRepository(session))
            created = await keys.create_key(
                keys_service.ApiKeyCreateData(name="Codex local client", allowed_models=None)
            )
            descriptor = os.open(data / "codex-api-key.txt", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as output:
                output.write(created.key + "\n")
    finally:
        await database.close_db()


def main() -> int:
    payload = json.load(sys.stdin)
    asyncio.run(initialize(payload["password"]))
    print("Initialized local authentication. Provider accounts are empty.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
