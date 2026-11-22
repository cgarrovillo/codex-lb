# Native macOS service

Use the optional native tools to run an installed release independently of the source checkout.
The operator installs and controls the macOS login service.
In the current migration, the assistant prepares files and tests without running service-changing commands.

## Daily use

After activation, start Codex normally:

```sh
codex
```

macOS starts the proxy at login.
The dashboard remains at [localhost:2455](http://127.0.0.1:2455).

| Command | Behavior |
|---|---|
| `codex-lb` or `codex-lb status` | Show registration, process state, readiness, installed version, and permanent paths. |
| `codex-lb restart` | Stop gracefully, start the installed release, and wait for a new ready process. |
| `codex-lb logs` | Show the last 60 log lines. |
| `codex-lb logs -f` | Follow new log output. |
| `codex-lb open` | Open the ready dashboard. |
| `codex-lb stop` | Stop for this login session while preserving data and login autostart. |
| `codex-lb start` | Reload the service definition and wait for readiness. |

Run these commands from any directory.
They do not install packages, query Git, or update the application.
A lock prevents concurrent service changes.

The optional global `codex-lb` command manages the service.
The private Python environment retains the application's original server entry point.
The service runs `python -I -B -m app.cli` directly.

The Codex provider ID is `codex-lb`, but its display name is `openai` in the current configuration.
The pinned upstream client guide requires this name for remote-compaction compatibility.
An OpenAI display label alone does not identify the request destination.
The configured proxy endpoint is `http://127.0.0.1:2455/backend-api/codex`.
The fresh-session verification record confirms a successful response through that endpoint.

### Continue conversations created under another provider

Changing the global default does not migrate a saved conversation's provider.
An existing `openai` conversation can still use direct OpenAI routing when reopened.
An HTTP 401 must be checked against that conversation's request URL.
Successful tests of another session do not establish that the affected conversation works.

Use a history-preserving fork to continue an existing conversation through the pool:

```sh
codex -c model_provider=codex-lb fork <SESSION_ID> --no-daemon
```

Quit the failing client before opening its continuation.
The fork gets a separate conversation ID and preserves the original history.
The exact authentication-failure recovery was verified with an ephemeral fork and a successful proxy response.
This operation does not require restarting the macOS service.

Codex documents the provider boundary and fork path in its
[app-server guide](https://developers.openai.com/codex/app-server/).

## Permanent paths

| Item | Location |
|---|---|
| Local source checkout | `~/workbench/codex-lb/` |
| Installed release and manager | `~/Library/Application Support/codex-lb/` |
| Account data and encryption key | `~/.codex-lb/` |
| Protected client key | `~/.codex-lb/codex-api-key.txt` |
| Server log | `~/Library/Logs/codex-lb/server.log` |
| Management helpers | `~/.local/bin/` |
| Login service | `~/Library/LaunchAgents/io.github.codex-lb.server.plist` |

Source edits do not prevent service restart.
The release record identifies the version, source commit, installed paths, and hashes.

## Preparation

Preparation requires the reviewed full source commit, Python, Bun, and the existing staging directory.
Run the preparation script from the source checkout:

```sh
/usr/local/bin/python3.13 -I -B scripts/prepare_native.py \\
  --commit 84fde5a1ed5e0d5a58ccb3ec4b82938b059bf8c5 \\
  --python /usr/local/bin/python3.13 \\
  --bun ~/.codex/staging/codex-lb/.state/native/tools/bun-1.3.14/bun \\
  --from-staging ~/.codex/staging/codex-lb
```

Preparation exports committed application source and builds the dashboard with frozen dependencies.
It installs locked Python dependencies without editable links.
It records hashes and archives the original controls history as a Git bundle.
It installs management helpers without changing the live service or Codex configuration.

Preparation does not install a LaunchAgent or copy live account data.
It rejects a different source selection or an existing prepared release.
The current migration retains application version 1.24.0.

## Operator activation

The operator runs this command from a normal macOS terminal:

```sh
~/.local/bin/codex-lb-activate
```

This command performs the live cutover and can interrupt proxy requests.
Before stopping the server, it checks the release, destination, process identity, client-key permissions, and credential-helper configuration.

It then performs these steps:

1. Stop only the verified legacy process with SIGTERM.
2. Wait for the server to exit and release port 2455.
3. Back up stopped data, the encryption key, client key, and Codex configuration.
4. Copy existing account data to its permanent location.
5. Check database integrity, account counts, client-key counts, and copied credentials.
6. Install the property list in the user's LaunchAgents directory.
7. Register the foreground server with macOS.
8. Wait for its process and HTTP readiness.
9. Update only the Codex provider's credential-helper path.

Existing destination data or a different process blocks migration before termination.
The command normalizes the legacy receipt's date fields while preserving identity checks.
It does not copy shell credentials into the job.

Backups and activation phase records remain under the permanent installation directory.
The original installation remains available until manual verification succeeds.
Registration alone does not prove readiness.

After activation, check:

```sh
codex-lb status
```

Then verify the dashboard and a separate Codex session.
Login startup and recovery after process exit require live operator checks.
KeepAlive cannot detect every stalled request.

## Rollback

The operator runs:

```sh
~/.local/bin/codex-lb-activate --rollback
```

Rollback stops and unregisters the new job before restarting the original installation.
It copies the stopped permanent data back to the legacy installation to retain newer account state.
It retains the original backup and permanent data directory.
It restores the original Codex credential-helper configuration.

Rollback refuses to overwrite Codex configuration changed after activation.
A failed activation prints its phase and rollback command.
It retains recovery files instead of starting a competing server.
Inspect the activation record if a filesystem failure interrupts rollback itself.

## Git and updates

The local checkout uses the fork as `origin` and the original project as `upstream`.
Preparation selects a reviewed release commit independently of the feature branch.
A fetch, push, source edit, start, or restart does not deploy an application update.

Review updates separately.
Build a new release at its final path before a user-run service replacement.
Preserve a stopped database backup and its encryption key before changing versions.
The current migration tool handles the existing version only.

## Other existing native installations

The original explicit installer remains available:

```sh
python3 scripts/macos_launchagent.py install \\
  --python /absolute/path/to/installed-venv/bin/python \\
  --data-dir /absolute/path/to/existing-data \\
  --dry-run
```

Remove `--dry-run` to install from a terminal in the macOS login session.
The installer requires existing `store.db` and `encryption.key` files.
It refuses an occupied port or an existing job or property list.
Removal preserves data and logs:

```sh
python3 scripts/macos_launchagent.py uninstall
```

A user LaunchAgent runs while its user is logged in and the Mac is awake.
The job uses localhost, the macOS certificate bundle, disabled telemetry, and disabled conversation archiving.
Generated definitions and credential-bearing runtime files stay outside Git.
Logs can contain request material and authentication setup details.

---

Spec: [deployment-installation](https://github.com/Soju06/codex-lb/tree/main/openspec/specs/deployment-installation)
