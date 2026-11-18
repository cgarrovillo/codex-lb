#!/usr/bin/env python3
"""Install a user LaunchAgent for an existing native Codex LB deployment."""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

LABEL = "io.github.codex-lb.server"
SERVICE_PATH = "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"


@dataclass(frozen=True)
class Service:
    python: Path
    data_dir: Path
    log_dir: Path

    def plist(self) -> bytes:
        environment = {
            "HOME": str(Path.home()),
            "PATH": SERVICE_PATH,
            "CODEX_LB_DATA_DIR": str(self.data_dir),
            "CODEX_LB_OAUTH_CALLBACK_HOST": "127.0.0.1",
            "CODEX_LB_TELEMETRY_ENABLED": "false",
            "CODEX_LB_CONVERSATION_ARCHIVE_ENABLED": "false",
        }
        if Path("/etc/ssl/cert.pem").is_file():
            environment["SSL_CERT_FILE"] = "/etc/ssl/cert.pem"
        return plistlib.dumps(
            {
                "Label": LABEL,
                "ProgramArguments": [
                    str(self.python),
                    "-I",
                    "-B",
                    "-m",
                    "app.cli",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "2455",
                ],
                "WorkingDirectory": str(self.data_dir),
                "EnvironmentVariables": environment,
                "RunAtLoad": True,
                "KeepAlive": True,
                "ThrottleInterval": 30,
                "ExitTimeOut": 90,
                "ProcessType": "Background",
                "Umask": 0o077,
                "StandardOutPath": str(self.log_dir / "server.log"),
                "StandardErrorPath": str(self.log_dir / "server.log"),
            },
            sort_keys=False,
        )


def plist_path() -> Path:
    return Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"


def service_target() -> str:
    return f"gui/{os.getuid()}/{LABEL}"


def launchctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["/bin/launchctl", *args], capture_output=True, text=True, timeout=20, check=False)


def registered_job() -> subprocess.CompletedProcess[str] | None:
    result = launchctl("print", service_target())
    if result.returncode == 0:
        return result
    if "Could not find service" in result.stderr:
        return None
    raise RuntimeError("Cannot inspect the launchd job. Run this command in your macOS login session.")


def validate_service(args: argparse.Namespace) -> Service:
    # Resolving this symlink would select the base interpreter and lose the venv.
    python = Path(args.python).expanduser().absolute()
    data_dir = Path(args.data_dir).expanduser().resolve()
    log_dir = Path(args.log_dir).expanduser().resolve()
    if not python.is_file() or not os.access(python, os.X_OK):
        raise ValueError("Select an executable Python from your installed Codex LB environment.")
    if not all((data_dir / name).is_file() for name in ("store.db", "encryption.key")):
        raise ValueError("Select existing application data containing store.db and encryption.key.")
    probe = (
        "import sys; from importlib.metadata import distribution; "
        "assert sys.version_info >= (3, 13); "
        "assert distribution('codex-lb').locate_file('app/cli.py').is_file()"
    )
    result = subprocess.run(
        [str(python), "-I", "-B", "-c", probe],
        env={"HOME": str(Path.home()), "PATH": SERVICE_PATH},
        cwd=data_dir,
        capture_output=True,
        timeout=15,
        check=False,
    )
    if result.returncode:
        raise ValueError("The selected Python must be version 3.13+ with Codex LB installed.")
    return Service(python, data_dir, log_dir)


def require_free_port() -> None:
    try:
        connection = socket.create_connection(("127.0.0.1", 2455), timeout=1)
    except ConnectionRefusedError:
        return
    except OSError as error:
        raise RuntimeError("Cannot check port 2455. Installation did not start another server.") from error
    connection.close()
    raise RuntimeError("Port 2455 is occupied. Stop the existing server before installing the LaunchAgent.")


def install(service: Service) -> None:
    target = plist_path()
    if target.exists() or target.is_symlink():
        raise ValueError("The LaunchAgent property list already exists. Uninstall it before installing a replacement.")
    if registered_job() is not None:
        raise ValueError("The launchd job already exists. Uninstall it before installing a replacement.")
    require_free_port()
    target.parent.mkdir(parents=True, exist_ok=True)
    service.log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    log_path = service.log_dir / "server.log"
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW
    descriptor = os.open(log_path, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(service.plist())
    except BaseException:
        target.unlink()
        raise
    # If launchctl times out, keep the plist: registration may have succeeded.
    result = launchctl("bootstrap", f"gui/{os.getuid()}", str(target))
    if result.returncode:
        if registered_job() is None:
            target.unlink()
        raise RuntimeError("launchctl could not confirm registration. Check service status before retrying.")
    print(f"Registered {LABEL}. Check status and /health/ready before using the proxy.")


def uninstall() -> None:
    if registered_job() is not None:
        result = launchctl("bootout", service_target())
        if result.returncode:
            raise RuntimeError("launchctl could not remove the job. The property list was retained.")
    plist_path().unlink(missing_ok=True)
    print("Removed the LaunchAgent. Application data and logs were preserved.")


def status() -> None:
    result = registered_job()
    summary: dict[str, str | bool] = {
        "installed": plist_path().is_file(),
        "registered": result is not None,
    }
    if result is not None:
        for line in result.stdout.splitlines():
            name, separator, value = line.strip().partition(" = ")
            if separator and name in {"state", "pid", "last exit code"}:
                summary[name] = value
    print(json.dumps(summary, indent=2))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    installer = commands.add_parser("install", help="Install and register the login service.")
    installer.add_argument("--python", required=True, help="Installed Codex LB Python; keep its venv path.")
    installer.add_argument("--data-dir", default=str(Path.home() / ".codex-lb"))
    installer.add_argument("--log-dir", default=str(Path.home() / "Library/Logs/codex-lb"))
    installer.add_argument("--dry-run", action="store_true", help="Print the property list without installing it.")
    commands.add_parser("status", help="Report property-list and launchd registration state.")
    commands.add_parser("uninstall", help="Remove the job and preserve application data.")
    args = parser.parse_args(argv)
    try:
        if sys.platform != "darwin":
            raise ValueError("This installer requires macOS.")
        if args.command == "install":
            service = validate_service(args)
            if args.dry_run:
                print(service.plist().decode(), end="")
            else:
                install(service)
        elif args.command == "status":
            status()
        else:
            uninstall()
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"LaunchAgent command failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
