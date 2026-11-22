# Context

The service manager already works from an installed copy outside Git.
Its builder and activation command still assume an existing staged deployment.
The new path separates fresh setup from that legacy migration.

The installation manifest pins application commit 84fde5a1ed5e0d5a58ccb3ec4b82938b059bf8c5 and its build tools.
The application remains version 1.24.0 during this change.
Generated credentials, data, installed environments, and machine paths stay outside Git.

For example, a user clones the personal fork, runs ./install, then runs the printed activation command.
Activation prompts for a dashboard password and creates a private local client key.
The user then signs in to provider accounts through the dashboard.

The installer can refresh the management tools for an already installed matching release.
It does not restart the running service or replace account data.
Changing the pinned application version requires a separate reviewed application upgrade.

The assistant must not execute live LaunchAgent commands in this session.
Tests use temporary installation paths and a simulated service manager.
