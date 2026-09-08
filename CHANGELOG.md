# Changelog

## 0.4.2 (Plan 047)

Router correctness and installer fixes, committed on
`chore/no-request-cap-guard`, not yet deployed (live router still runs
the pre-restructure prototype; see Plan 047 section 2):

- Compaction keeps the newest transcript tail and names tools; runs
  before request preparation and holds a drain slot, so a release
  landing mid-compaction no longer loses the work.
- Discovered tools survive compaction; catalogue stubs are completed
  from discovered schemas instead of blocking them.
- Upstream 429 maps to retryable 503 with `Retry-After`.
- Summariser pinned to the lowest supported effort with a higher
  output cap; unreadable reasoning blobs stripped for OpenRouter
  models; image blocks stripped for text-only models.
- Installer seeds the picker catalogue (`catalogue --merge`) and
  writes `model_catalog_json` only with `--static-catalogue`.
- `/health` reports `served_models` (which upstream model actually
  served); tilde aliases display upstream alias names.
- CI fails if a request cap is reintroduced; `packaging/VERSION` is
  semver (`0.4.2`) and matches `pyproject.toml`.
- Internal router bugs surface as 500 with a traceback instead of 400.
- Upstream `openai-model` header is pinned to the requested slug so a
  rerouted model never triggers a mismatch warning; `/health` keeps
  reporting which model actually served.

## 0.4.0 (Plan 041)

First installer release: `packaging/release.py` builds a deterministic
versioned bundle with `MANIFEST.json` and `latest.json`;
`packaging/install.py` (stdlib, Python 3.9+) verifies the checksum and
manifest, self-tests the bundle, swaps releases atomically with
health-check rollback, manages the LaunchAgents and daily update check,
and inserts the Codex config block. `packaging/install.sh` and
`packaging/install.ps1` are thin wrappers around the installer. GitHub
releases publish on `v*` tags with a beta channel.
