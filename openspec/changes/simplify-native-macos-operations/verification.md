# Verification and operating limits

The operator completed activation on 2026-11-20.
Login startup and recovery after process exit remain unverified on the live Mac.
Automated lifecycle checks use a simulated service manager.

## Completed checks

- The focused unittest suite passed 34 tests.
- Ruff lint and formatting checks passed for the changed Python files.
- Git whitespace checks passed.
- Strict OpenSpec validation passed for this change.
- Main specification validation passed all 57 capabilities, with existing purpose and requirement-length warnings.
- The selected application's dashboard built with Bun 1.3.14 and the frozen frontend lockfile.
- Uv installed locked dependencies into the permanent virtual environment without editable links.
- Installed provenance, dashboard presence, unchanged lockfiles, and application/configuration hashes were checked.
- Installed management commands passed help checks from a directory outside the source checkout.

The focused tests cover process date formatting, PID mismatch, concurrent commands, graceful restart, failed registration, and existing destination protection.
Migration tests preserve credentials and account records.
Rollback tests preserve newer account records and reject later Codex configuration edits.
Installed-command tests cover paths containing spaces.

The complete application CI suite was not run during the original installation work.
Its database, Docker, Kubernetes, and application integration jobs exceed the focused service-tool checks.
This record does not claim full application CI coverage.

## Live activation evidence

The activation record reported the completed phase.
The new process listened on localhost port 2455, and its readiness endpoint returned HTTP 200.
The installed service definition selected the permanent release and account data directory.
Existing database, encryption-key, client-key, and Codex-configuration backups remained available.
The Codex credential helper selected the permanent helper path.

The tested application version was 1.24.0.
Its source commit was 84fde5a1ed5e0d5a58ccb3ec4b82938b059bf8c5.
Activation did not upgrade the selected application version.

Machine-specific process IDs, conversation IDs, request IDs, file hashes, and backup timestamps remain in a private local verification record.
Credentials, generated service definitions, installed environments, databases, and logs remain outside Git.

## Codex session routing checks

A fresh terminal-session response passed through the proxy using CLI version 0.167.2 and the normal global configuration.
The proxy recorded successful WebSocket requests for the same conversation.

A saved conversation with provider ID `openai` later failed authentication.
Its actual destination was `https://api.openai.com/v1/responses`, and the response was HTTP 401.
The proxy had no record of that failed request.
The global provider setting did not migrate the saved conversation.

A separate ephemeral fork of that exact conversation successfully answered through the proxy.
The original conversation file's hash remained unchanged.
Proxy correlation used the fork's conversation ID because session lineage metadata retained the original session ID.

The display name `openai` is also used by the custom `codex-lb` provider for pinned upstream compatibility.
That label alone cannot establish routing.
Check the affected conversation's saved provider and request destination.

For a saved conversation that must continue through the pool, quit the failing client and run:

```sh
codex -c model_provider=codex-lb fork <SESSION_ID> --no-daemon
```

This creates a separate continuation while preserving the original conversation.
The history-transfer response was verified; an operator must open the interactive continuation.
The operation does not require a macOS service restart.

## Execution ownership

The user reserved macOS service commands for manual execution.
The assistant prepared and tested the files without running launchctl, installing a LaunchAgent, or changing live service state.
The operator later ran activation, including the stopped backup, data migration, service registration, and credential-helper update.

Operator commands and rollback instructions are in `docs/deployment/macos.md`.
Do not repeat activation after it has completed successfully.

## Cross-Mac portability limits

The current preparation command requires the original staging directory, baseline, and controls history.
Activation requires legacy release and process receipts, existing account data, and a matching Codex credential helper.
This is an existing-installation migration.
A fresh clone on another Mac cannot complete the same workflow without those files.

Fresh installation still requires these changes:

1. Separate fresh installation from legacy migration.
2. Commit an installation manifest with the application commit, tool versions, and service defaults.
3. Detect or install the required Python, uv, and Bun for the target Mac.
4. Generate paths, helpers, and the service definition for that Mac.
5. Generate Codex provider configuration without copying unrelated personal configuration.
6. Provide local account setup and client-key creation.
7. Verify installation without the staging directory.

Keep accounts, login tokens, passwords, encryption keys, and client keys outside Git.
Recreate installed Python environments on each destination Mac.

## Remaining manual verification

- Verify login startup.
- Verify recovery after process exit.
- Verify any required compaction and account-failover behavior separately.
- Retire the original installation only after recovery checks pass.

The OpenSpec change remains active until the required live lifecycle verification is complete.
