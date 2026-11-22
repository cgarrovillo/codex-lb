# Simplify native macOS operation

The native trial became the default Codex provider without a permanent installation or complete service management.
Its process receipt uses locale-dependent dates and can report a running server as stopped.

Extend the existing optional macOS service tools with status, start, stop, restart, logs, and dashboard access.
Prepare an immutable native release outside the source checkout.
Provide a separate operator-run migration that preserves accounts, credentials, and rollback files.

The user owns all live service commands and LaunchAgent installation.
Preparation and automated tests must not mutate the live service or Codex routing.
Application routing, account selection, dependencies, and the selected application version remain outside this change.
