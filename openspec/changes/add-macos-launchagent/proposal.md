# Add native macOS auto-start support

## Why

Native Codex LB stops when its unmanaged process exits. The current deployment
has no login startup or process supervisor. macOS launchd can own the foreground
server and restart it after an exit.

## What Changes

- Add an optional standard-library installer for a per-user LaunchAgent.
- Reuse an explicitly selected installed Python environment and existing data.
- Provide preview, installation, status, and removal commands.
- Keep credentials, runtime files, and generated property lists outside Git.
- Document operation, migration from manual startup, and verification limits.

## Impact

- Affected capability: deployment-installation.
- Affected files: scripts/macos_launchagent.py, deployment documentation, tests.
- Existing CLI, Docker startup, application code, and database schemas stay unchanged.
- Local activation requires permission to write the user's LaunchAgents directory.
