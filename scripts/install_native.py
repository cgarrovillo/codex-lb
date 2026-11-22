"""Prepare a pinned native installation from a clone, without service changes."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shlex
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

# The bootstrap uses isolated Python, independently of the checkout environment.
sys.path.insert(0, str(Path(__file__).absolute().parents[1]))
from scripts import macos_launchagent as service  # noqa: E402
from scripts import native_migrate, prepare_native  # noqa: E402


def install_bun(root: Path, manifest: dict, architecture: str) -> Path:
    selected = manifest["bun"][architecture]
    destination = root / "tools" / f"bun-{manifest['bun']['version']}"
    executable = destination / "bun"
    # Verify a new archive even when replacing an interrupted download.
    with tempfile.TemporaryDirectory(prefix="codex-lb-bun-") as temporary:
        archive = Path(temporary) / "bun.zip"
        subprocess.run(
            [
                "/usr/bin/curl",
                "--fail",
                "--location",
                "--silent",
                "--show-error",
                "--retry",
                "2",
                "--connect-timeout",
                "15",
                "--max-time",
                "180",
                f"https://github.com/oven-sh/bun/releases/download/bun-v{manifest['bun']['version']}/{selected['asset']}",
                "-o",
                str(archive),
            ],
            check=True,
        )
        if hashlib.sha256(archive.read_bytes()).hexdigest() != selected["sha256"]:
            raise ValueError("The Bun download failed its checksum check.")
        with zipfile.ZipFile(archive) as files:
            member = selected["asset"].removesuffix(".zip") + "/bun"
            prepare_native.write_private(executable, "", 0o700)
            executable.write_bytes(files.read(member))
    return executable


def paths_for(root: Path, isolated: bool) -> dict[str, str]:
    if isolated:
        return {
            name: str(root / relative)
            for name, relative in {
                "data": "data",
                "bin": "bin",
                "codex_config": "codex/config.toml",
                "logs": "logs",
                "plist": f"LaunchAgents/{service.LABEL}.plist",
                "locks": "locks",
            }.items()
        }
    return {name: str(service.runtime_path(name)) for name in ("data", "bin", "codex_config", "logs", "plist", "locks")}


def prepare(root: Path, uv: Path, isolated: bool) -> None:
    manifest = json.loads((prepare_native.ROOT / "deploy/macos-native.json").read_text())
    application = manifest["application"]
    architecture = platform.machine()
    if platform.system() != "Darwin" or architecture not in ("arm64", "x86_64"):
        raise ValueError("This installer requires an Apple Silicon or Intel Mac.")
    receipt = root / "release.json"
    if receipt.is_file():
        record = json.loads(receipt.read_text())
        if (record["source_commit"], record["version"]) != (application["commit"], application["version"]):
            raise ValueError(
                "The installed release differs from the manifest. Review an application upgrade separately."
            )
        native_migrate.verify_release(record, root)
        python = Path(record["venv_python"])
        bins = Path(record["paths"]["bin"]) if "paths" in record else Path.home() / ".local/bin"
        prepare_native.install_tools(root, python, bins)
        print(
            "Reused the verified release and refreshed management commands. "
            "Local data and service state were preserved."
        )
    else:
        paths = paths_for(root, isolated)
        data = Path(paths["data"])
        if data.exists() or data.is_symlink():
            raise ValueError(f"Existing data has no installation receipt: {data}. No data was replaced.")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        bun = install_bun(root, manifest, architecture)
        available = subprocess.run(
            ["git", "-C", str(prepare_native.ROOT), "cat-file", "-e", application["commit"] + "^{commit}"],
            capture_output=True,
            check=False,
        )
        if available.returncode:
            subprocess.run(
                ["git", "-C", str(prepare_native.ROOT), "fetch", "--depth=1", "origin", application["commit"]],
                check=True,
            )
        record = prepare_native.build_release(
            application["commit"], Path(sys.executable), bun, root, uv, application["version"]
        )
        record.update(installation_mode="fresh", paths=paths, codex=manifest["codex"])
        prepare_native.write_private(receipt, json.dumps(record, indent=2) + "\n")
        bins = Path(paths["bin"])
        prepare_native.install_tools(root, Path(record["venv_python"]), bins)
        print("Prepared the pinned release. Run activation to create local credentials and configure Codex.")
    print(f"Activation: {shlex.quote(str(bins / 'codex-lb-activate'))}")
    print(f"Management commands: {bins}")
    print("Activation asks for a dashboard password. Add your accounts in the dashboard afterward.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uv", type=Path, required=True)
    parser.add_argument(
        "--prefix", type=Path, help="Use an isolated installation directory, including data and commands."
    )
    args = parser.parse_args()
    root = args.prefix.expanduser().absolute() if args.prefix else service.installation_root()
    try:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Preparation has a separate lock and never inspects or controls launchd.
        import fcntl

        with (root / "prepare.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            prepare(root, args.uv, args.prefix is not None)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        print(f"Preparation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
