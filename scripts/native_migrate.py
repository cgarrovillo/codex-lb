"""Operator-run activation and rollback for the prepared native installation."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import signal
import sqlite3
import stat
import subprocess
import sys
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from scripts import macos_launchagent as service


def save(path: Path, record: dict) -> None:
    pending = path.with_suffix(".tmp")
    with pending.open("w") as output:
        os.fchmod(output.fileno(), 0o600)
        json.dump(record, output, indent=2)
        output.write("\n")
    pending.replace(path)


def normalized_identity(identity: str) -> tuple[str, ...]:
    fields = identity.split(None, 5)
    if len(fields) != 6:
        raise ValueError("The legacy process identity has an unsupported format.")
    weekday, first, second, clock, year, command = fields
    month, day = (second, first) if first.isdigit() else (first, second)
    return weekday, month, str(int(day)), clock, year, command


def process_identity(pid: int) -> str:
    result = subprocess.run(
        ["/bin/ps", "-p", str(pid), "-o", "lstart=", "-o", "command="],
        env={"PATH": service.SERVICE_PATH, "LC_ALL": "C"},
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError("Cannot inspect the legacy process. No process was stopped.")
    return result.stdout.strip()


def validate_old_process(record: dict) -> bool:
    if not isinstance(record["pid"], int) or record["pid"] <= 1:
        raise ValueError("The legacy PID is invalid. No process was stopped.")
    identity = process_identity(record["pid"])
    if not identity:
        service.require_free_port()
        return False
    if normalized_identity(identity) != normalized_identity(record["identity"]):
        raise ValueError("The legacy process identity changed. No process was stopped.")
    return True


def stop_old_process(record: dict) -> None:
    if not validate_old_process(record):
        return
    os.kill(record["pid"], signal.SIGTERM)
    deadline = time.monotonic() + 95
    while time.monotonic() < deadline:
        identity = process_identity(record["pid"])
        if not identity or normalized_identity(identity) != normalized_identity(record["identity"]):
            service.require_free_port()
            return
        time.sleep(0.5)
    raise RuntimeError("The legacy server did not stop within 95 seconds. No data was copied.")


def tree_digest(path: Path) -> str:
    result = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        if item.is_file() and "__pycache__" not in item.parts:
            result.update(item.relative_to(path).as_posix().encode() + b"\0")
            result.update(item.read_bytes())
    return result.hexdigest()


def verify_release(record: dict, installation: Path | None = None) -> None:
    release = Path(record["release_dir"]).resolve()
    root = ((installation if installation is not None else service.installation_root()) / "releases").resolve()
    if not release.is_relative_to(root):
        raise ValueError("The selected release is outside the permanent installation.")
    if not Path(record["venv_python"]).is_file():
        raise ValueError("The prepared Python executable is missing.")
    for name in ("app", "config"):
        path = Path(record[name + "_dir"]).resolve()
        if not path.is_relative_to(release / "venv") or tree_digest(path) != record[name + "_sha256"]:
            raise ValueError(f"The prepared {name} files changed. Activation did not proceed.")


def proxy_key(path: Path) -> bytes:
    metadata = path.stat()
    if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError("The existing client key must be owned by you with mode 0600.")
    content = path.read_bytes()
    key = content.decode().strip()
    if not key.startswith("sk-clb-") or any(character.isspace() for character in key):
        raise ValueError("The existing client key has an invalid format.")
    return content


def migrated_config(content: str, old_helper: Path, new_helper: Path) -> str:
    parsed = tomllib.loads(content)
    provider = parsed["model_providers"]["codex-lb"]
    if provider["auth"]["command"] != str(old_helper):
        raise ValueError("Codex's existing credential helper differs from the selected staging installation.")
    pattern = r"(?ms)(^\[model_providers\.codex-lb\.auth\][^\n]*\n)(.*?)(?=^\[|\Z)"
    section = re.search(pattern, content)
    if section is None:
        raise ValueError("Cannot locate the Codex provider authentication section.")
    body, count = re.subn(r"(?m)^command\s*=.*$", "command = " + json.dumps(str(new_helper)), section[2])
    if count != 1:
        raise ValueError("The Codex provider must have exactly one credential command.")
    result = content[: section.start(2)] + body + content[section.end(2) :]
    expected = tomllib.loads(content)
    expected["model_providers"]["codex-lb"]["auth"]["command"] = str(new_helper)
    if tomllib.loads(result) != expected:
        raise ValueError("The prepared Codex configuration changes more than its credential helper.")
    return result


def data_signature(directory: Path) -> tuple[int, int]:
    database = directory / "store.db"
    with contextlib.closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        if connection.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise ValueError("The database integrity check failed. Original files were retained.")
        return (
            connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0],
            connection.execute("SELECT COUNT(*) FROM api_keys").fetchone()[0],
        )


def activate() -> None:
    root = service.installation_root()
    state_path = root / "activation.json"
    if state_path.exists():
        raise ValueError("An activation record already exists. Inspect it or run codex-lb-activate --rollback.")
    release = service.release_record()
    verify_release(release)
    staging = Path(json.loads((root / "migration-source.json").read_text())["staging"])
    native = staging / ".state/native"
    old_release = json.loads((native / "release.json").read_text())
    if old_release["source_commit"] != release["source_commit"]:
        raise ValueError("The prepared and running source selections differ. No service was stopped.")
    data = Path.home() / ".codex-lb"
    if data.exists() or data.is_symlink():
        raise ValueError("The permanent data directory already exists. No service was stopped or files replaced.")
    if service.plist_path().exists() or service.registered_job() is not None:
        raise ValueError("A codex-lb login service already exists. No service was replaced.")
    for filename in ("store.db", "encryption.key"):
        if not (native / "data" / filename).is_file():
            raise ValueError(f"The existing data is missing {filename}.")
    client_key = proxy_key(native / "codex-api-key.txt")
    config_path = Path.home() / ".codex/config.toml"
    original_config = config_path.read_text()
    proposed_config = migrated_config(
        original_config, staging / "bin/read-proxy-key", Path.home() / ".local/bin/codex-lb-read-key"
    )
    process = json.loads((native / "process.json").read_text())
    if process.get("release_dir") != old_release["release_dir"]:
        raise ValueError("The legacy process belongs to another release. No process was stopped.")
    validate_old_process(process)
    backup = root / "backups" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup.mkdir(parents=True, mode=0o700)
    state = {"phase": "preflight passed", "backup": str(backup), "staging": str(staging)}
    save(state_path, state)
    try:
        print("Stopping the verified legacy server. Existing proxy requests can be interrupted.")
        stop_old_process(process)
        state["phase"] = "legacy stopped"
        save(state_path, state)
        shutil.copytree(native / "data", backup / "data")
        (backup / "codex-api-key.txt").write_bytes(client_key)
        (backup / "codex-api-key.txt").chmod(0o600)
        (backup / "codex-config.toml").write_text(original_config)
        (backup / "codex-config.toml").chmod(0o600)
        signature = data_signature(backup / "data")
        shutil.copytree(backup / "data", data)
        data.chmod(0o700)
        (data / "codex-api-key.txt").write_bytes(client_key)
        (data / "codex-api-key.txt").chmod(0o600)
        if data_signature(data) != signature:
            raise ValueError("Account or client-key counts changed during migration.")
        for filename in ("store.db", "encryption.key"):
            if (backup / "data" / filename).read_bytes() != (data / filename).read_bytes():
                raise ValueError(f"The copied {filename} differs from its stopped backup.")
        state["phase"] = "data copied"
        save(state_path, state)
        selected = service.Service(Path(release["venv_python"]), data, Path.home() / "Library/Logs/codex-lb")
        service.install(selected)
        state["phase"] = "service registered"
        save(state_path, state)
        service.wait_ready()
        if config_path.read_text() != original_config:
            raise ValueError("Codex configuration changed during activation. Its new contents were preserved.")
        pending = config_path.with_name("config.toml.codex-lb-pending")
        with pending.open("w") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(proposed_config)
        pending.replace(config_path)
        state.update(phase="activated", config_sha256=hashlib.sha256(proposed_config.encode()).hexdigest())
        save(state_path, state)
        print("Activation complete. Run codex-lb status, then check a separate Codex session.")
        print(f"Original installation and rollback files were retained. Backup: {backup}")
    except BaseException:
        print(f"Activation stopped during: {state['phase']}. Original installation and backup files were retained.")
        print("Inspect codex-lb status and logs. To return to the original service, run codex-lb-activate --rollback.")
        raise


def rollback() -> None:
    root = service.installation_root()
    state_path = root / "activation.json"
    state = json.loads(state_path.read_text())
    if state["phase"] == "rolled back":
        raise ValueError("This activation was already rolled back. The original service was retained.")
    staging = Path(state["staging"])
    config_path = Path.home() / ".codex/config.toml"
    if state.get("config_sha256"):
        actual = hashlib.sha256(config_path.read_bytes()).hexdigest()
        if actual != state["config_sha256"]:
            raise ValueError("Codex configuration changed after activation. Resolve it before rollback.")
    service.stop()
    service.uninstall()
    service.require_free_port()
    current_data = Path.home() / ".codex-lb"
    if state["phase"] in {"data copied", "service registered", "activated"}:
        data_signature(current_data)
        old_data = staging / ".state/native/data"
        retained = Path(state["backup"]) / "legacy-before-rollback"
        old_data.rename(retained)
        try:
            shutil.copytree(current_data, old_data)
        except BaseException:
            # Keep the untouched legacy copy available if the copy is interrupted.
            print(f"Rollback data copy failed. The previous legacy data remains at {retained}.")
            raise
    if state.get("config_sha256"):
        shutil.copyfile(Path(state["backup"]) / "codex-config.toml", config_path)
        config_path.chmod(0o600)
    environment = {key: os.environ[key] for key in ("HOME", "TMPDIR") if key in os.environ}
    environment.update(PATH=service.SERVICE_PATH, LC_ALL="C")
    subprocess.run(
        ["/usr/local/bin/python3.13", "-I", "-B", str(staging / "bin/native.py"), "start"],
        env=environment,
        check=True,
    )
    state["phase"] = "rolled back"
    save(state_path, state)
    print("Restored the original service. Both data directories and all backups were retained.")


def main() -> int:
    parser = argparse.ArgumentParser(prog="codex-lb-activate", description=__doc__)
    parser.add_argument(
        "--rollback", action="store_true", help="Stop the new job and return to the original installation."
    )
    args = parser.parse_args()
    try:
        with service.operator_lock():
            if service.release_record().get("installation_mode") == "fresh":
                from scripts import native_activate

                if args.rollback:
                    native_activate.rollback()
                else:
                    native_activate.activate()
            elif args.rollback:
                rollback()
            else:
                activate()
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        print(f"Activation command failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
