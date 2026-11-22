"""Build a permanent native release without changing the running service."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ("__init__.py", "macos_launchagent.py", "native_migrate.py", "read_proxy_key.py")


def tree_digest(path: Path) -> str:
    result = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        if item.is_file() and "__pycache__" not in item.parts:
            result.update(item.relative_to(path).as_posix().encode() + b"\0")
            result.update(item.read_bytes())
    return result.hexdigest()


def write_private(path: Path, content: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
    with os.fdopen(descriptor, "w") as output:
        os.fchmod(output.fileno(), mode)
        output.write(content)


def install_tools(destination: Path, python: Path) -> None:
    manager = destination / "manager"
    launchers: dict[Path, str] = {}
    for name, module in (
        ("codex-lb", "macos_launchagent"),
        ("codex-lb-activate", "native_migrate"),
        ("codex-lb-read-key", "read_proxy_key"),
    ):
        code = (
            f"import sys; sys.path.insert(0, {str(manager)!r}); "
            f"from scripts.{module} import main; raise SystemExit(main())"
        )
        command = f'#!/bin/sh\nexec {shlex.quote(str(python))} -I -B -c {shlex.quote(code)} "$@"\n'
        target = Path.home() / ".local/bin" / name
        if target.is_symlink() or (target.exists() and target.read_text() != command):
            raise ValueError(f"Refusing to replace an existing command: {target}")
        launchers[target] = command
    for name in SCRIPTS:
        write_private(manager / "scripts" / name, (ROOT / "scripts" / name).read_text())
    for target, command in launchers.items():
        write_private(target, command, 0o700)


def prepare(commit: str, python: Path, bun: Path, staging: Path) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Select the full reviewed source commit.")
    destination = Path.home() / "Library/Application Support/codex-lb"
    if (destination / "release.json").exists():
        raise ValueError("A prepared release already exists. Inspect it before preparing a replacement.")
    baseline = json.loads((staging / "baseline.json").read_text())
    if baseline["source_commit"] != commit:
        raise ValueError("The selected commit must match the existing reviewed deployment for this migration.")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    release = destination / "releases" / f"{commit[:12]}-{stamp}"
    source = release / "source"
    source.mkdir(parents=True, mode=0o700)
    destination.chmod(0o700)
    archive = subprocess.run(
        ["git", "-C", str(ROOT), "archive", "--format=tar", commit], capture_output=True, check=True
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as files:
        files.extractall(source, filter="data")
    environment = {key: os.environ[key] for key in ("HOME", "TMPDIR", "LANG", "LC_ALL") if key in os.environ}
    environment.update(
        PATH=f"{bun.parent}:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin",
        SSL_CERT_FILE="/etc/ssl/cert.pem",
        UV_PROJECT_ENVIRONMENT=str(release / "venv"),
        UV_LINK_MODE="copy",
        NODE_OPTIONS="--max-old-space-size=1536",
        GOMAXPROCS="2",
    )
    node = shutil.which("node")
    if node:
        environment["PATH"] = str(Path(node).parent) + ":" + environment["PATH"]
    locks = [source / "uv.lock", source / "frontend/bun.lock"]
    before = [hashlib.sha256(path.read_bytes()).hexdigest() for path in locks]
    for command in (
        [str(bun), "install", "--frozen-lockfile", "--ignore-scripts"],
        [str(bun), "run", "build"],
    ):
        subprocess.run(command, cwd=source / "frontend", env=environment, check=True)
    uv = shutil.which("uv")
    if uv is None:
        raise ValueError("uv is required to prepare the installed release.")
    subprocess.run(
        [
            uv,
            "--no-config",
            "sync",
            "--locked",
            "--no-dev",
            "--no-editable",
            "--extra",
            "metrics",
            "--extra",
            "tracing",
            "--python",
            str(python),
            "--no-managed-python",
            "--no-python-downloads",
        ],
        cwd=source,
        env=environment,
        check=True,
    )
    if before != [hashlib.sha256(path.read_bytes()).hexdigest() for path in locks]:
        raise ValueError("The build changed a dependency lockfile.")
    installed_python = release / "venv/bin/python"
    query = (
        "import importlib.metadata as m,json;d=m.distribution('codex-lb');"
        "print(json.dumps({'version':d.version,'root':str(d.locate_file('')),'origin':"
        "json.loads(d.read_text('direct_url.json'))}))"
    )
    metadata = json.loads(
        subprocess.run(
            [str(installed_python), "-I", "-B", "-c", query],
            capture_output=True,
            text=True,
            check=True,
            env=environment,
            cwd=release,
        ).stdout
    )
    if metadata["version"] != baseline["release"].removeprefix("v"):
        raise ValueError("The installed application version differs from the selected version.")
    if metadata["origin"]["url"].rstrip("/") != source.as_uri() or metadata["origin"].get("dir_info", {}).get(
        "editable"
    ):
        raise ValueError("The application must be a non-editable installation from the selected local source.")
    package_root = Path(metadata["root"])
    app = package_root / "app"
    config = package_root / "config"
    if not (app / "static/index.html").is_file():
        raise ValueError("The installed dashboard is missing.")
    record = {
        "source_commit": commit,
        "version": metadata["version"],
        "release_dir": str(release),
        "venv_python": str(installed_python),
        "app_dir": str(app),
        "config_dir": str(config),
        "app_sha256": tree_digest(app),
        "config_sha256": tree_digest(config),
        "built_at": datetime.now(timezone.utc).isoformat(),
        "lock_sha256": before,
    }
    write_private(destination / "release.json", json.dumps(record, indent=2) + "\n")
    write_private(destination / "migration-source.json", json.dumps({"staging": str(staging.resolve())}) + "\n")
    archives = destination / "archives"
    archives.mkdir(mode=0o700)
    subprocess.run(
        ["git", "-C", str(staging), "bundle", "create", str(archives / "staging-controls.bundle"), "--all"], check=True
    )
    install_tools(destination, installed_python)
    print("Prepared the permanent release and commands. The running service and Codex routing were unchanged.")
    print(f"Activate when ready: {Path.home() / '.local/bin/codex-lb-activate'}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--bun", required=True, type=Path)
    parser.add_argument("--from-staging", required=True, type=Path)
    args = parser.parse_args()
    prepare(args.commit, args.python, args.bun, args.from_staging)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
