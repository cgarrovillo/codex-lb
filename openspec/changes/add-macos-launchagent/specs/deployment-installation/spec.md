## ADDED Requirements

### Requirement: Optional macOS user service

The project SHALL provide an optional macOS LaunchAgent installer for an existing
native SQLite deployment. The installer SHALL launch the selected installed
Python in the foreground with -I -B -m app.cli. It SHALL preserve a virtual
environment executable path without resolving its interpreter symlink.

The job SHALL bind to 127.0.0.1:2455. It SHALL start at user login and request
restart after process exit. The job SHALL use the selected existing data
directory. Installation SHALL require store.db and encryption.key to exist.

The generated job SHALL contain only paths and non-secret service settings.
The installer SHALL NOT read account tokens, encryption-key contents, or database
contents. It SHALL NOT copy the caller's environment into the generated job.
Generated property lists and runtime files SHALL remain outside version control.

Installation SHALL reject an occupied port, an existing job, or an existing
property list. A confirmed registration failure SHALL remove the newly written
property list. An ambiguous registration timeout SHALL retain the property list
for recovery. Removal SHALL preserve the database, encryption key, and logs.
A failed job removal SHALL preserve the property list for later recovery.

The installer SHALL provide a preview that performs no filesystem writes and
no launchctl mutations. Status SHALL distinguish an installed property list
from a registered launchd job.

#### Scenario: Existing native installation is supervised

- **GIVEN** an installed Python and an existing application data directory
- **AND** the service port and LaunchAgent label are available
- **WHEN** the operator installs the user service
- **THEN** the job runs the selected Python in the foreground
- **AND** launchd receives login startup and process restart instructions
- **AND** the existing credential files remain unchanged

#### Scenario: Caller credentials are excluded

- **GIVEN** the caller has authentication variables in its environment
- **WHEN** the operator previews or installs the job
- **THEN** those variables and values are absent from the property list

#### Scenario: Installation cannot register the job

- **WHEN** launchctl rejects registration
- **THEN** installation reports failure and removes its new property list
- **AND** existing application data remains unchanged

#### Scenario: Removal cannot unregister the job

- **WHEN** launchctl rejects removal of a registered job
- **THEN** removal reports failure and retains its property list
- **AND** existing application data remains unchanged
