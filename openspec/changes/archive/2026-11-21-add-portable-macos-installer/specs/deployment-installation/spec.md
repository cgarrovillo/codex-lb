## ADDED Requirements

### Requirement: Fresh Mac installation entry point

An optional installer SHALL prepare the committed application version without requiring staging files.
It SHALL obtain pinned uv, Python, and Bun versions and verify downloaded uv and Bun archive hashes.
It SHALL support Apple Silicon and Intel macOS hosts.
It SHALL generate local helpers and a release receipt outside the checkout.

#### Scenario: A second Mac has no previous installation

- **GIVEN** a clone of the fork and no staging directory or application data
- **WHEN** the operator runs the installer
- **THEN** it prepares the selected release and management helpers
- **AND** prints one operator activation command
- **AND** does not install or change a macOS service

### Requirement: Fresh activation initializes local authentication

Fresh activation SHALL initialize a new private data directory using the pinned application's migrations and services.
It SHALL configure dashboard password authentication and proxy client-key authentication before starting the service.
It SHALL generate a local encryption key and client key without publishing their values.
It SHALL NOT import account tokens from another Mac.

#### Scenario: Account setup is local

- **WHEN** the operator activates a fresh installation
- **THEN** it requests a dashboard password and creates local client credentials
- **AND** provider accounts remain empty until the operator signs in

### Requirement: Generated Codex configuration preserves other settings

Activation SHALL back up the existing Codex configuration before changing its provider defaults.
It SHALL select the committed model and the local codex-lb endpoint and credential helper.
It SHALL preserve unrelated configuration and reject unsupported or conflicting credential layouts before changing a service.

#### Scenario: A laptop already has Codex preferences

- **GIVEN** an existing Codex configuration with unrelated preferences and tools
- **WHEN** fresh activation configures the local pool
- **THEN** those unrelated settings remain unchanged
- **AND** a backup of the previous configuration remains available

### Requirement: Repeated preparation preserves installed state

The installer SHALL reuse a matching verified release and refresh its known management helpers without rebuilding.
It SHALL preserve account data, client keys, Codex configuration, and running service state during preparation.
It SHALL reject an incompatible installed release or unrelated command at an installation path.
Legacy migration receipts SHALL remain supported.

#### Scenario: The user pulls updated service tools

- **GIVEN** an existing matching application release and local accounts
- **WHEN** the user pulls the repository and runs the installer again
- **THEN** the known helpers are refreshed without service restart or account changes
