# Context

The existing local deployment uses separate application and controls repositories.
Startup requires both development checkouts to remain clean, even though it runs an installed snapshot.
The new commands read installed state instead of Git state.

Preparation builds the same selected commit into its final location.
It installs management helpers without registering a service or migrating live data.
The operator runs one activation command when a brief interruption is acceptable.

Activation validates the legacy process identity using normalized date fields.
It stops only the matching process, preserves a stopped data backup, and copies existing account data.
It registers the prepared service before updating the Codex credential-helper path.
On failure, it records the phase and preserves rollback files instead of starting a competing server.

For example, `codex-lb restart` uses the installed LaunchAgent and waits for a new process and HTTP readiness.
Editing this repository does not alter the selected installed release.

The assistant must not execute activation or service-changing commands in this session.
Tests simulate launchctl and use temporary homes and databases.
