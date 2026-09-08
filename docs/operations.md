# Router operations

## How to ship

Merge to `main`. The release workflow builds the bundle, runs the suite,
and publishes a `vMAJOR.MINOR.BUILD` release with `latest.json`. Every
router on the stable channel installs it within about fifteen minutes.

## Global subagent guidance

The installer adds one managed subagent-discovery block to the active global
Codex `AGENTS.md` (or non-empty `AGENTS.override.md`) beside `config.toml`.
It preserves existing content and symlinks; updates replace only that block,
and uninstall removes it. If its text or active file changed, installation
stops for review. Start a fresh Codex task to load the rule. It applies across
models without duplicating text in the catalogue and grants no new permission.

## How to test first

Push to `beta`. The workflow publishes a `vMAJOR.MINOR.BUILD-beta`
pre-release with `latest-beta.json`. Cyril's machine follows the `beta`
channel (`beta` in the `channel` file beside the state directory), so it
updates first; watch its `/health` version and `logs/update.log` before
merging to `main`.

## How to roll back

Push a revert to `main` (the next release supersedes the bad one), or pin
one machine with `python3 packaging/install.py --version X`. The installer
itself rolls back automatically when the new release fails its health
check.

## Restart behavior

On update the router stops accepting new requests (they get `503` with
`Retry-After: 2`), finishes in-flight requests up to the two-minute drain
deadline, then exits; launchd holds the listening socket so connections
wait instead of failing. `/health` reports `draining: true` during the
drain. Without socket activation (manual runs) there is a brief
refused-connection window at process start; the Codex request and stream
retry settings cover it.

## Layout of the state directory

`~/.codex/mixed-model-router/` holds `current` (symlink to the live
release), `releases/` (current plus previous), `logs/`,
`mixed-router-state.json` (port and token, mode 600),
`activation.json` (config receipt), and `openrouter.key` (mode 600).
The code may live anywhere; only this directory matters at runtime.

## Verification after a Codex upgrade

Run the suite, then the base probe against the installed router and
confirm discovery, one exact callback, and the marker in the final
answer. If the app-server protocol changed, probes fail before any
user task does; do not ship model changes until the base probe passes.

## Per-user OpenRouter keys (IT issue and revoke)

Owner decision 2026-09-09: IT issues one OpenRouter key per portco user;
there is no self-service provisioning. The flow per user:

1. IT creates the key in the OpenRouter dashboard with a monthly allowance
   and hands it to the user over an existing trusted channel (never commit
   it, never paste it into chat or email threads beyond that handoff).
2. The user installs with `--setup`, opens the setup link, and pastes the
   key once. The window validates it against OpenRouter before storing
   anything and shows remaining credit; the key lands in `openrouter.key`
   (mode 600), which the router reads per request.
3. Rotation: delete `openrouter.key` first (the setup window refuses to
   overwrite a file holding a real key with 409), then re-run the installer
   with `--setup` and paste the replacement. File-level alternative is under
   `Key rotation` below.
4. Revocation is at the OpenRouter dashboard: delete or pause the user's key,
   then confirm fail-closed by asking the user to run any OpenRouter request
   and checking the router log for a `request_completed` entry carrying the
   upstream 401 rather than a completion. Offboarding also removes the seat
   per the portco process; there is no local grant to unwind as long as no
   `OPENROUTER_API_KEY` env or OpenCode-auth fallback is set on that machine,
   because entitlement otherwise lives entirely in the dashboard key state.

## Key rotation

Replace the `openrouter.key` file contents. No restart is needed; the
router reads the key per request.

## Incidents

Check `/health`, then `logs/launchd.log`, then
`launchctl print` for the router agent. Roll back by re-running the
installer with `--version` pointing at the previous release.

## Decision log

Request cap removed. Compaction runs through a billable summariser
call. The catalogue is a generated snapshot from the registry (live
in-router catalogue pending); live model metadata refreshes weekly
into the registry. Model rows are data; new behaviour is always code.

## One-time cleanup after 0.4.0

Delete from the state directory on the author's machine:
`compatibility-release.json`, the `before-*` folders,
`config-before-*.toml`, `stdout.log`, `stderr.log`, and `retired/` after
one week. Keep `mixed-router-state.json`, `activation.json`,
`openrouter.key`, `current`, `releases/`, and `logs/`.
