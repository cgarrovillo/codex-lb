# Native macOS service

Use the optional native tools to run an installed release independently of the source checkout.
The operator installs and controls the macOS login service.

## Set up another Mac

Install Codex CLI separately if the laptop does not have it.
Use a Mac with Git and access to GitHub and the package registries.
The installer obtains its own pinned Python, uv, and Bun versions.
Homebrew, Node, an existing staging directory, and copied account data are unnecessary.

Clone the fork on the other laptop:

```sh
git clone https://github.com/cgarrovillo/codex-lb.git
cd codex-lb
./install
```

For an existing checkout, use:

```sh
git switch main
git pull --ff-only origin main
./install
```

Run the activation command printed by the installer:

```sh
~/.local/bin/codex-lb-activate
```

Activation requests a new dashboard password and creates local encryption and client keys.
It registers the service and configures Codex to use the local proxy.
It preserves unrelated Codex settings and saves a backup before changes.
If `CODEX_HOME` selects another Codex directory, activation uses that directory.
If a default profile is selected, activation updates that profile's provider and model defaults too.

Open [localhost:2455](http://127.0.0.1:2455), enter the dashboard password, and add your provider accounts.
Then start a new session with `codex`.
Each Mac has separate account data and credentials.
Git distributes the installation recipe and shared defaults; account tokens stay local.

Preparation runs no macOS service commands and changes no Codex configuration.
Activation performs those changes only when the operator runs it.
The committed manifest selects application version 1.24.0 and the default model and reasoning effort.
The installer supports Apple Silicon and Intel archive selection.
Live installation verification currently covers Apple Silicon; Intel requires a target-machine check.

Use the full helper path if `~/.local/bin` is absent from the shell's `PATH`:

```sh
~/.local/bin/codex-lb status
```

The installer does not edit shell startup files.

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

Run these commands from any directory when `~/.local/bin` is on `PATH`.
Otherwise, use `~/.local/bin/codex-lb` in place of `codex-lb`.
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
| Source checkout | Any directory selected during clone |
| Installed release and manager | `~/Library/Application Support/codex-lb/` |
| Account data and encryption key | `~/.codex-lb/` |
| Protected client key | `~/.codex-lb/codex-api-key.txt` |
| Server log | `~/Library/Logs/codex-lb/server.log` |
| Management helpers | `~/.local/bin/` |
| Login service | `~/Library/LaunchAgents/io.github.codex-lb.server.plist` |

Source edits do not prevent service restart.
The release record identifies the version, source commit, installed paths, and hashes.

## Migrate an existing staging installation

This path applies only to the original staging installation.
New laptops use `./install` above.
Legacy preparation requires the reviewed source commit, Python, Bun, and the existing staging directory:

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

### Legacy operator activation

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

For a fresh installation, rollback removes the new service and restores the previous Codex configuration.
It preserves local account data and credentials.
A later activation can reuse successfully initialized data.
Partial initialization remains available for inspection and is never overwritten.

For a staging migration, rollback stops and unregisters the new job before restarting the original installation.
It copies the stopped permanent data back to the legacy installation to retain newer account state.
It retains the original backup and permanent data directory.
It restores the original Codex credential-helper configuration.

Rollback refuses to overwrite Codex configuration changed after activation.
A failed activation prints its phase and rollback command.
It retains recovery files instead of starting a competing server.
Inspect the activation record if a filesystem failure interrupts rollback itself.

## Git and updates

The local checkout uses the fork as `origin` and the original project as `upstream`.
New clones need only `origin` to install.
The fork's default branch is `main`.
The committed manifest selects the application release independently of the checkout branch.
A fetch, push, source edit, start, or restart does not deploy an application update.

Pull management changes and run `./install` again to refresh the installed helpers.
A matching release is verified and reused without a rebuild, restart, or credential change.
An older migration receipt retains its existing activation and rollback behavior.
An incompatible release requires a separate application upgrade.

Review updates separately.
Build a new release at its final path before a user-run service replacement.
Preserve a stopped database backup and its encryption key before changing versions.
The current tools handle the pinned version only.

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

Spec: [deployment-installation](https://github.com/cgarrovillo/codex-lb/tree/main/openspec/specs/deployment-installation)
