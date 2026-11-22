"""Activate or roll back a fresh native installation when the operator requests it."""

from __future__ import annotations

import copy
import getpass
import hashlib
import json
import os
import re
import subprocess
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from scripts import macos_launchagent as service
from scripts.native_migrate import proxy_key, save, verify_release


def update_section(content: str, section: str, values: dict) -> str:
    header = re.compile(r"(?m)^[ \t]*\[[^\n]+\][ \t]*(?:#[^\n]*)?$")
    tables = list(header.finditer(content))
    if not section:
        start, end = 0, tables[0].start() if tables else len(content)
    else:
        selected = next(
            (i for i, match in enumerate(tables) if match[0].strip().split("#")[0].strip() == f"[{section}]"), None
        )
        if selected is None:
            content = content.rstrip() + f"\n\n[{section}]\n"
            start, end = len(content), len(content)
        else:
            start = tables[selected].end()
            end = tables[selected + 1].start() if selected + 1 < len(tables) else len(content)
    body = content[start:end]
    for name, value in values.items():
        line = f"{name} = {json.dumps(value, ensure_ascii=False)}"
        pattern = re.compile(r"(?m)^[ \t]*" + re.escape(name) + r"[ \t]*=.*$")
        if pattern.search(body):
            body = pattern.sub(lambda _: line, body)
        else:
            body = body.rstrip() + "\n" + line + "\n"
    return content[:start] + body.rstrip() + "\n\n" + content[end:]


def configured_codex(content: str, helper: Path, defaults: dict) -> str:
    original = tomllib.loads(content)
    expected = copy.deepcopy(original)
    providers = expected.setdefault("model_providers", {})
    provider = providers.setdefault("codex-lb", {})
    conflicts = {"api_key", "env_key", "bearer_token", "experimental_bearer_token", "http_headers", "env_http_headers"}
    if conflicts.intersection(provider):
        raise ValueError("The existing codex-lb provider has conflicting credentials. Resolve them before activation.")
    sections = {
        "": {"model_provider": "codex-lb", **defaults},
        "model_providers.codex-lb": {
            "name": "openai",
            "base_url": service.URL + "/backend-api/codex",
            "wire_api": "responses",
            "requires_openai_auth": False,
            "supports_websockets": True,
            "supports_standalone_web_search": True,
        },
        "model_providers.codex-lb.auth": {"command": str(helper), "timeout_ms": 2000, "refresh_interval_ms": 0},
    }
    expected.update(sections[""])
    if "profile" in expected:
        profile = expected["profile"]
        if not isinstance(profile, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", profile):
            raise ValueError("The active Codex profile name cannot be updated safely.")
        values = dict(sections[""])
        expected.setdefault("profiles", {}).setdefault(profile, {}).update(values)
        sections[f"profiles.{profile}"] = values
    provider.update(sections["model_providers.codex-lb"])
    provider.setdefault("auth", {}).update(sections["model_providers.codex-lb.auth"])
    for section, values in sections.items():
        content = update_section(content, section, values)
    if tomllib.loads(content) != expected:
        raise ValueError("The existing TOML layout cannot be updated safely. No service was changed.")
    return content


def current_config(path: Path) -> str:
    if path.is_symlink():
        raise ValueError(
            "The Codex configuration is a symlink. Select a regular local configuration before activation."
        )
    return path.read_text() if path.exists() else ""


def replace_config(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    pending = path.with_name(path.name + ".codex-lb-pending")
    descriptor = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as output:
        output.write(content)
    pending.replace(path)


def activate() -> None:
    root = service.installation_root()
    state_path = root / "activation.json"
    release = service.release_record()
    verify_release(release)
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    if state.get("phase") == "activated":
        print("This installation is already activated. Run codex-lb status.")
        return
    if state and state["phase"] != "rolled back":
        raise ValueError(
            "An incomplete activation exists. Inspect status, then run codex-lb-activate --rollback before retrying."
        )
    data = service.runtime_path("data")
    initialized = state.get("initialized", False)
    if (data.exists() or data.is_symlink()) and not initialized:
        raise ValueError("The data directory already exists. No existing credentials were replaced.")
    if service.plist_path().exists() or service.registered_job() is not None:
        raise ValueError("A login service already exists. No service was replaced.")
    service.require_free_port()
    config_path = service.runtime_path("codex_config")
    original = current_config(config_path)
    proposed = configured_codex(original, service.runtime_path("bin") / "codex-lb-read-key", release["codex"])
    password = ""
    if not initialized:
        password = getpass.getpass("New codex-lb dashboard password: ")
        if not 8 <= len(password.encode()) <= 72:
            raise ValueError("Use a dashboard password containing 8 to 72 UTF-8 bytes.")
        if password != getpass.getpass("Confirm dashboard password: "):
            raise ValueError("Passwords differ. No service was changed.")
    else:
        proxy_key(data / "codex-api-key.txt")
    backup = root / "backups" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup.mkdir(parents=True, mode=0o700)
    previous = backup / "codex-config.toml"
    descriptor = os.open(previous, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as output:
        output.write(original)
    state = {
        "phase": "preflight passed",
        "backup": str(backup),
        "config_existed": config_path.exists(),
        "initialized": initialized,
    }
    save(state_path, state)
    try:
        if not initialized:
            environment = {"HOME": str(Path.home()), "PATH": service.SERVICE_PATH, "CODEX_LB_DATA_DIR": str(data)}
            subprocess.run(
                [release["venv_python"], "-I", "-B", str(root / "manager/scripts/native_initialize.py")],
                input=json.dumps({"password": password}),
                text=True,
                env=environment,
                cwd=root,
                check=True,
            )
            proxy_key(data / "codex-api-key.txt")
            state.update(initialized=True, phase="data initialized")
            save(state_path, state)
        selected = service.Service(Path(release["venv_python"]), data, service.runtime_path("logs"))
        state["phase"] = "registering service"
        save(state_path, state)
        service.install(selected)
        state["phase"] = "service registered"
        save(state_path, state)
        service.wait_ready()
        if current_config(config_path) != original or config_path.exists() != state["config_existed"]:
            raise ValueError("Codex configuration changed during activation. Its new contents were preserved.")
        # Record intent before replacement so interruption retains a recoverable config hash.
        state.update(phase="configuring Codex", config_sha256=hashlib.sha256(proposed.encode()).hexdigest())
        save(state_path, state)
        replace_config(config_path, proposed)
        state["phase"] = "activated"
        save(state_path, state)
        print(f"Activated codex-lb. Open {service.URL}, sign in to the dashboard, and add your accounts.")
        print("Then start a new Codex session. Existing conversations retain their saved provider.")
        print(f"Management commands: {service.runtime_path('bin')}")
    except BaseException:
        print(f"Activation stopped during: {state['phase']}. Data and backups were retained.")
        print("Inspect codex-lb status and logs. Run codex-lb-activate --rollback before retrying.")
        raise


def rollback() -> None:
    state_path = service.installation_root() / "activation.json"
    state = json.loads(state_path.read_text())
    if state["phase"] == "rolled back":
        raise ValueError("This activation was already rolled back. Local data was preserved.")
    config_path = service.runtime_path("codex_config")
    original = (Path(state["backup"]) / "codex-config.toml").read_text()
    current = current_config(config_path)
    updated = state.get("config_sha256") == hashlib.sha256(current.encode()).hexdigest()
    if state.get("config_sha256") and not updated and current != original:
        raise ValueError("Codex configuration changed after activation. Resolve it before rollback.")
    if state["phase"] in {"registering service", "service registered", "configuring Codex", "activated"}:
        record = service.release_record()
        expected = service.Service(
            Path(record["venv_python"]), service.runtime_path("data"), service.runtime_path("logs")
        )
        if service.plist_path().exists():
            if service.plist_path().read_bytes() != expected.plist():
                raise ValueError("The login service changed. No service was stopped.")
            service.stop()
            service.uninstall()
        elif service.registered_job() is not None:
            raise ValueError("A registered service has no matching property list. Inspect it before rollback.")
    if updated:
        if state["config_existed"]:
            replace_config(config_path, original)
        else:
            config_path.unlink()
    state["phase"] = "rolled back"
    save(state_path, state)
    print("Removed the fresh service and restored Codex configuration. Local data and credentials were preserved.")
    if state["initialized"]:
        print("Run codex-lb-activate to retry using the initialized data.")
    else:
        print("Inspect any partial data before retrying. Existing data is never overwritten.")
