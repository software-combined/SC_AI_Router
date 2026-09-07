# Changelog

## 0.4.0 (Plan 041)

First installer release: `packaging/release.py` builds a deterministic
versioned bundle with `MANIFEST.json` and `latest.json`;
`packaging/install.py` (stdlib, Python 3.9+) verifies the checksum and
manifest, self-tests the bundle, swaps releases atomically with
health-check rollback, manages the LaunchAgents and daily update check,
and inserts the Codex config block. `packaging/install.sh` and
`packaging/install.ps1` are thin wrappers around the installer. GitHub
releases publish on `v*` tags with a beta channel.
