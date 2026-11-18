# Design and operating constraints

The fork's default branch is deployment/staged-v1.24.0. The running release
checks that branch's source receipt. This change uses a separate checkout based
on that default branch. It does not update the running application package.

launchd must own the actual server process. The LaunchAgent invokes the selected
Python with -I -B -m app.cli. It does not invoke a background launcher, uvx,
a dependency installer, a shell, or a Git command.

The installer supports an existing native SQLite deployment. Operators configure
accounts and dashboard authentication before installing auto-start. The installer
checks that store.db and encryption.key exist. It does not read their contents.

The generated property list contains executable paths and non-secret service
settings. It does not copy the caller's environment or store credential values.
The database, encryption key, logs, and generated property list remain local.

A user LaunchAgent starts at login and stops at logout. KeepAlive restarts the
process after exit. It does not detect an unresponsive process, prevent sleep,
or correct account quota and stream-capacity failures.

Installation must reject an occupied service port and an existing job or property
list. It must not stop an unidentified process or overwrite another job.
Removal must preserve the application data and logs.

The coding session can inspect launchd but cannot write Library/LaunchAgents.
Tests verify the lifecycle through a simulated launchctl.
A real login and crash-restart check remains separate runtime evidence.
