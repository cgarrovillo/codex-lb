# Add a fresh Mac installation path

The existing tools migrate one Mac and require its old staging files.
A clone on another Mac cannot reproduce the installation.

Add one optional installer with committed application and tool versions.
Download verified tools for Apple Silicon or Intel and build the pinned application with locked dependencies.
Generate local helpers and configuration without requiring a staging directory.
Preserve existing installations when the installer runs again.

The operator retains control of macOS service activation.
Fresh activation creates local credentials, preserves unrelated Codex configuration, and starts the prepared service.
Accounts remain local and require provider sign-in on each Mac.
