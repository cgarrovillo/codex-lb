# Native macOS auto-start

Use a user LaunchAgent to start an existing native installation at login.
macOS launchd supervises the foreground server and restarts it after exit.
The service stops when you log out. It does not run while the Mac sleeps.

## Prepare the installation

Configure Codex LB, its accounts, and dashboard authentication before installing the service.
Keep the existing data directory. It must contain `store.db` and `encryption.key`.
The installer checks their presence without reading their contents.

Select the Python executable from the installed environment.
For example, use `/absolute/path/to/codex-lb-venv/bin/python`.
Keep the virtual environment path, including its interpreter symlink.
The service runs that installed version without downloading packages or updating source.

Run these commands from a checkout containing `scripts/macos_launchagent.py`.
The selected application installation can be in another directory.

## Preview and install

1. Preview the property list:

   ```sh
   python3 scripts/macos_launchagent.py install \
     --python /absolute/path/to/codex-lb-venv/bin/python \
     --data-dir /absolute/path/to/existing-data \
     --dry-run
   ```

2. Stop your manually started Codex LB server with its existing control command.

3. Install the service from a terminal in your macOS login session:

   ```sh
   python3 scripts/macos_launchagent.py install \
     --python /absolute/path/to/codex-lb-venv/bin/python \
     --data-dir /absolute/path/to/existing-data
   ```

Installation refuses an occupied port or an existing job or property list.
It does not stop an unidentified process or replace another job.
Remove an existing job before installing a replacement with different paths.

The installer writes `~/Library/LaunchAgents/io.github.codex-lb.server.plist`.
It then registers the job with `launchctl bootstrap`.
`RunAtLoad` starts it when loaded, including at login.
`KeepAlive` requests restart after exit. `ThrottleInterval` limits repeated starts to one per 30 seconds.
Registration success does not prove that application startup succeeded.

The server listens on `127.0.0.1:2455` and uses the selected existing data directory.
The job uses the macOS certificate bundle when `/etc/ssl/cert.pem` exists.
Telemetry and conversation archiving are disabled in the generated job.
The job does not copy the installer's shell environment.
Custom database URLs, outbound proxies, and other shell-only settings need a separate reviewed service configuration.

The property list and log file have owner-only access.
Logs default to `~/Library/Logs/codex-lb/server.log`.
Use `--log-dir /absolute/path/to/log-directory` to select another log directory.
Existing log content is preserved.

## Check and remove

Check the registration and application readiness:

```sh
python3 scripts/macos_launchagent.py status
curl --fail --max-time 5 http://127.0.0.1:2455/health/ready
```

Status reports property-list installation separately from launchd registration.
It includes the process ID and job state when launchd reports them.
Use the log when registration succeeds but readiness fails.

Remove the service before returning to manual startup:

```sh
python3 scripts/macos_launchagent.py uninstall
```

Removal unregisters the job and deletes its property list.
It preserves application data, the encryption key, and logs.
If unregistering fails, the installer retains the property list for recovery.
If registration times out, check status before retrying. The job may already be registered.

## Credentials and verification

Commit the installer, tests, documentation, and specifications only.
Keep generated property lists, databases, encryption keys, logs, and environment files outside Git.
The installer does not embed credentials or copy account data.
Application logs can contain request material or authentication setup details.

The automated CLI tests use a temporary home and a simulated `launchctl`.
They verify lifecycle calls, failure cleanup, file permissions, and credential exclusion.
Confirm login startup and crash restart on the target Mac after installation.
Process supervision does not detect a responsive process with stalled requests.
Account quota and stream-capacity limits still apply.

---

Spec: [deployment-installation](https://github.com/Soju06/codex-lb/tree/main/openspec/specs/deployment-installation)
