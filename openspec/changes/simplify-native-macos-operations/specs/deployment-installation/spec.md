## ADDED Requirements

### Requirement: Native macOS operator commands

The optional native management command SHALL provide status, start, stop, restart, logs, and open operations.
It SHALL operate from any directory without Git, clean source, or package resolution.
Status SHALL distinguish installation, registration, process, and HTTP readiness states and identify canonical paths.

#### Scenario: Readiness does not prove process ownership

- **GIVEN** a server responds on port 2455 without the managed job
- **WHEN** the operator requests status
- **THEN** status identifies an unmanaged listener instead of a managed ready service

### Requirement: Native service lifecycle commands

Restart SHALL require a replacement managed process and HTTP readiness before reporting success.
Stop SHALL unregister the job while preserving its property list and application data.
Start SHALL reload that property list and reject an unrelated port owner.
Mutating commands SHALL use an exclusive operator lock.

#### Scenario: Development work does not block restart

- **GIVEN** an installed release and a registered native service
- **AND** the source checkout has local edits
- **WHEN** the operator restarts from another directory
- **THEN** restart uses the installed service without checking Git
- **AND** success requires a replacement managed process and HTTP readiness

#### Scenario: Intentional stop is preserved

- **WHEN** the operator stops the service
- **THEN** the job cannot immediately respawn through KeepAlive
- **AND** its property list, data, and login autostart preference remain present

### Requirement: Native release preparation

Preparation SHALL build a selected full source commit with locked dependencies into its permanent release path.
It SHALL record source provenance and installed application hashes.
It SHALL NOT register a service, change Codex routing, migrate live data, or stop a process.
Installed management helpers SHALL operate independently of the source checkout and staging directory.

#### Scenario: Preparation preserves the live service

- **WHEN** a native release is prepared
- **THEN** the existing process, account data, Codex configuration, and service registration remain unchanged

### Requirement: Legacy process ownership recovery

Operator-run migration SHALL normalize legacy process date formatting before comparing identities.
It SHALL refuse a conflicting process or existing destination data before stopping the legacy server.
It SHALL preserve protection against PID reuse and SHALL reject invalid PIDs.

#### Scenario: Date order changes between sessions

- **GIVEN** a legacy receipt uses Fri 20 Nov 15:03:10 2026
- **AND** current process output uses Fri Nov 20 15:03:10 2026
- **AND** the PID, start time, executable, and arguments otherwise match
- **WHEN** the operator activates the prepared installation
- **THEN** identity comparison recognizes the same process
- **AND** a different start time or command prevents termination

#### Scenario: Existing destination data is protected

- **GIVEN** the destination data directory already exists
- **WHEN** the operator requests migration
- **THEN** migration stops before signaling the old server or replacing files

### Requirement: Native migration preserves account data

Migration SHALL preserve a stopped data backup, encryption key, client key, and Codex configuration backup.
It SHALL preserve account and client-key records during the copy.
It SHALL update only the selected provider's credential-helper command after service readiness.

#### Scenario: Existing accounts remain usable

- **WHEN** the operator activates the permanent installation
- **THEN** it retains the original account database, encryption key, and client key
- **AND** only the Codex credential-helper path changes in its configuration

### Requirement: Native activation failure and rollback

Activation failure SHALL preserve recovery files and report the failing phase.
It SHALL NOT start a competing legacy server.
Rollback SHALL require a separate operator invocation and stop the new job before starting the old server.
Rollback SHALL retain current account state and SHALL refuse to overwrite later Codex configuration edits.

#### Scenario: Service activation fails

- **WHEN** service registration or readiness fails
- **THEN** migration reports the phase and rollback command
- **AND** backups and original data remain available

#### Scenario: Account state changes after activation

- **GIVEN** the permanent installation has newer account state
- **WHEN** the operator requests rollback
- **THEN** rollback stops the new server before copying that state to the legacy installation
- **AND** it retains both the original backup and newer data
