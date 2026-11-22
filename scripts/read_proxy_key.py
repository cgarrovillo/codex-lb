"""Return the permanent local bearer key to the Codex credential helper."""

from __future__ import annotations

import os
import stat
import sys

from scripts import macos_launchagent as service


def main() -> int:
    path = service.runtime_path("data") / "codex-api-key.txt"
    metadata = path.stat()
    if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError("The local proxy key must be owned by you with mode 0600.")
    key = path.read_text().strip()
    if not key.startswith("sk-clb-") or any(character.isspace() for character in key):
        raise ValueError("The local proxy key has an invalid format.")
    sys.stdout.write(key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
