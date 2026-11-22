#!/usr/bin/env python3
"""Manage an installed native Codex LB service."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import plistlib
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

LABEL = "io.github.codex-lb.server"
SERVICE_PATH = "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
URL = "http://127.0.0.1:2455"


def installation_root() -> Path:
    return Path.home() / "Library/Application Support/codex-lb"


def release_record() -> dict:
    path = installation_root() / "release.json"
    if not path.is_file():
        raise ValueError("No prepared release exists. Prepare the native installation first.")
    return json.loads(path.read_text())


@contextlib.contextmanager
def operator_lock():
    directory = Path.home() / "Library/Caches/codex-lb"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / "operator.lock").open("a") as lock:
        os.fchmod(lock.fileno(), 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("Another codex-lb command is changing the service. Wait for it to finish.") from error
        yield


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


def job_fields(result: subprocess.CompletedProcess[str] | None) -> dict[str, str]:
    fields: dict[str, str] = {}
    if result is not None:
        for line in result.stdout.splitlines():
            name, separator, value = line.strip().partition(" = ")
            if separator and name in {"state", "pid", "last exit code"}:
                fields[name] = value
    return fields


def http_ready() -> bool:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(URL + "/health/ready", timeout=2) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def wait_ready(previous_pid: str | None = None) -> None:
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        fields = job_fields(registered_job())
        if fields.get("pid") and fields["pid"] != previous_pid and http_ready():
            print(f"codex-lb is ready at {URL} (PID {fields['pid']}).")
            return
        time.sleep(0.5)
    raise RuntimeError("Service did not become ready within 45 seconds. Run codex-lb status and codex-lb logs.")


def installed_plist() -> dict:
    path = plist_path()
    if not path.is_file():
        raise ValueError("The login service is not installed. Run the prepared activation command first.")
    record = plistlib.loads(path.read_bytes())
    if record.get("Label") != LABEL:
        raise ValueError("The installed property list does not belong to codex-lb.")
    return record


def start(previous_pid: str | None = None) -> None:
    installed_plist()
    job = registered_job()
    if job is None:
        require_free_port()
        result = launchctl("bootstrap", f"gui/{os.getuid()}", str(plist_path()))
    elif not job_fields(job).get("pid"):
        result = launchctl("kickstart", service_target())
    else:
        wait_ready(previous_pid)
        return
    if result.returncode:
        raise RuntimeError("macOS could not start the service. Run codex-lb status and codex-lb logs.")
    wait_ready(previous_pid)


def stop() -> None:
    if registered_job() is not None:
        result = launchctl("bootout", service_target())
        if result.returncode:
            raise RuntimeError("macOS could not stop the service. Its property list and data were retained.")
        deadline = time.monotonic() + 95
        while time.monotonic() < deadline:
            try:
                require_free_port()
                break
            except RuntimeError:
                time.sleep(0.5)
        else:
            raise RuntimeError("The service port is still occupied after shutdown. Inspect status before retrying.")
    else:
        require_free_port()
    print("codex-lb is stopped. Data and login autostart were preserved.")


def restart() -> None:
    installed_plist()
    job = registered_job()
    if job is None:
        start()
        return
    previous_pid = job_fields(job).get("pid")
    stop()
    start(previous_pid)


def operator_status() -> None:
    job = registered_job()
    fields = job_fields(job)
    ready = http_ready()
    if ready and not fields.get("pid"):
        state = "unmanaged listener"
    elif fields.get("pid"):
        state = "ready" if ready else "running but unready"
    else:
        state = "stopped" if plist_path().exists() else "not installed"
    settings = installed_plist() if plist_path().is_file() else {}
    summary = {
        "state": state,
        "installed": plist_path().is_file(),
        "registered": job is not None,
        "http_ready": ready,
        "url": URL,
        "data_directory": settings.get("WorkingDirectory", str(Path.home() / ".codex-lb")),
        "log": settings.get("StandardOutPath", str(Path.home() / "Library/Logs/codex-lb/server.log")),
        "installation": str(installation_root()),
        **fields,
    }
    # launchd's raw state is separate from the operator-facing readiness state.
    if "state" in fields:
        summary["launchd_state"] = fields["state"]
        summary["state"] = state
    if (installation_root() / "release.json").is_file():
        record = release_record()
        summary.update(version=record["version"], source_commit=record["source_commit"], python=record["venv_python"])
    print(json.dumps(summary, indent=2))


def logs(follow: bool) -> None:
    settings = installed_plist() if plist_path().is_file() else {}
    path = Path(settings.get("StandardOutPath", str(Path.home() / "Library/Logs/codex-lb/server.log")))
    if not path.is_file():
        raise ValueError("No service log exists yet. Run codex-lb status.")
    arguments = ["/usr/bin/tail", "-n", "60"]
    if follow:
        arguments.append("-f")
    subprocess.run([*arguments, str(path)], check=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="codex-lb", description=__doc__)
    commands = parser.add_subparsers(dest="command")
    installer = commands.add_parser("install", help="Install and register the login service.")
    installer.add_argument("--python", required=True, help="Installed Codex LB Python; keep its venv path.")
    installer.add_argument("--data-dir", default=str(Path.home() / ".codex-lb"))
    installer.add_argument("--log-dir", default=str(Path.home() / "Library/Logs/codex-lb"))
    installer.add_argument("--dry-run", action="store_true", help="Print the property list without installing it.")
    commands.add_parser("status", help="Report property-list and launchd registration state.")
    commands.add_parser("uninstall", help="Remove the job and preserve application data.")
    commands.add_parser("start", help="Start the installed service and wait for readiness.")
    commands.add_parser("stop", help="Stop the service for this login session and retain its property list.")
    commands.add_parser("restart", help="Restart the installed service and wait for a new ready process.")
    log_parser = commands.add_parser("logs", help="Show recent server logs.")
    log_parser.add_argument("--follow", "-f", action="store_true")
    commands.add_parser("open", help="Open the local dashboard.")
    args = parser.parse_args(argv)
    try:
        if sys.platform != "darwin":
            raise ValueError("This installer requires macOS.")
        if args.command is None:
            operator_status()
        elif args.command == "install":
            service = validate_service(args)
            if args.dry_run:
                print(service.plist().decode(), end="")
            else:
                with operator_lock():
                    install(service)
        elif args.command == "status":
            operator_status()
        elif args.command == "logs":
            logs(args.follow)
        elif args.command == "open":
            if not http_ready():
                raise RuntimeError("The dashboard is not ready. Run codex-lb status.")
            subprocess.run(["/usr/bin/open", URL], check=True)
        else:
            with operator_lock():
                {"start": start, "stop": stop, "restart": restart, "uninstall": uninstall}[args.command]()
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"LaunchAgent command failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
