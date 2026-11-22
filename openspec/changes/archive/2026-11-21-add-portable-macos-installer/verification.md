# Portable macOS installation verification

Verified on 2026-11-22 with Apple Silicon macOS.
The tested implementation is commit `d4c44955`, following `25820e9a`.
The application remains version `1.24.0` at `84fde5a1ed5e0d5a58ccb3ec4b82938b059bf8c5`.

## Results

| Check | Result |
|---|---|
| Focused service, legacy migration, preparation, portable installation, and offline authentication tests | 51 passed |
| `make lint` | Passed architecture checks, migration topology, Ruff, and formatting |
| `make typecheck` | Passed |
| Strict change validation | Passed |
| Main specification validation | 67 capabilities passed; existing length warnings remain |
| Staged Gitleaks scans | No leaks found |
| Fresh GitHub clone and root installer | Passed |
| Repeated root installer | Reused one release; protected local state remained identical |
| Deliberately invalid uv archive digest | Rejected before creating the installation |
| Apple Silicon and Intel Bun archive selection | Passed mocked archive and digest checks |

## Clean clone procedure

The verification cloned `cgarrovillo/codex-lb` from GitHub with `--depth 1` and the feature branch selected.
The clone contained neither staging state nor an existing application release.
The test ran `./install --prefix` with an empty destination and only `/usr/bin:/bin` on `PATH`.
It preserved the real home directory instead of substituting another `HOME`.

The installer downloaded and verified uv and Bun.
It selected managed Python 3.13.7 and fetched the pinned application commit missing from the shallow clone.
It built the frontend using Bun and installed the locked Python environment.
The installed package reported version 1.24.0 and contained the dashboard.
No external Node, Homebrew, staging baseline, staging process receipt, or migration-source record was required.

The test loaded the installed manager with the installed interpreter.
It ran the real offline initializer while simulating service registration and readiness.
It selected the local provider and model for both root configuration and a selected default profile.
Unrelated preferences and tool configuration remained intact.
Rollback restored the original configuration and retained the database, encryption key, and client key.
Activation retry reused those credentials without another password prompt.
No launchctl command ran during these checks.

A separate integration test ran real application migrations and both authentication services.
The dashboard password and client key validated successfully.
The account table was empty and the client-key table contained one key.
The database, encryption key, and client-key file had mode 0600.
Repeated initialization failed without changing those files.
Passwords and keys did not appear in initializer output.

The root installer then ran again against the activated fixture.
The release receipt, activation record, database, keys, Codex configuration, and property list retained identical hashes.
Only one release existed, and the source clone remained clean.

## Reproduce focused checks

Run from the repository root:

```sh
python3.13 -B -m unittest \
  tests.unit.test_macos_launchagent \
  tests.unit.test_native_migrate \
  tests.unit.test_prepare_native \
  tests.unit.test_install_native -q
```

To exercise real offline authentication, set `CODEX_LB_TEST_PYTHON` to the prepared release's `venv/bin/python`.
Then run `python3.13 -B -m unittest tests.integration.test_native_installation -q`.
The integration test creates and removes its own private temporary data.

## Limits and publication

The owner authorized committing, pushing, and merging into the personal fork's `main`.
The implementation was published on `feature/macos-autostart` before the clean GitHub clone test.
GitHub Actions is disabled on this fork, and no pull request or cloud review exists for this change.
Local checks do not establish cloud CI success.
Full CI remains unavailable because Rust/cargo, Trivy, kubeconform, and kind are missing.

No live LaunchAgent was installed, stopped, started, or restarted during this work.
The current account data and Codex configuration were not changed.
The target laptop still needs Codex CLI, operator activation, and provider account sign-in.
Actual login startup, crash recovery, and Intel execution require target-machine checks.
