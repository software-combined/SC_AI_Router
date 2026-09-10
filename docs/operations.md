# Router operations

## How to ship

Work lands on `develop` via `fix/*`/`feat/*` branches, then `develop`
merges to `main` via PR. Tag the merge `v$(cat packaging/VERSION)` (or
`v*-beta` for pre-releases): the release workflow runs on `v*` tags
only, builds the bundle, runs the suite, and publishes the release with
`latest.json`. Every router on the stable channel installs it within
about fifteen minutes. Never push to `main` directly for a release;
a direct push runs checks but publishes nothing.

## Global subagent guidance

The installer adds one managed subagent-discovery block to the active global
Codex `AGENTS.md` (or non-empty `AGENTS.override.md`) beside `config.toml`.
It preserves existing content and symlinks; updates replace only that block,
and uninstall removes it. If its text or active file changed, installation
stops for review. Start a fresh Codex task to load the rule. It applies across
models without duplicating text in the catalogue and grants no new permission.

## How to test first

Tag `v*-beta` from `develop`. The workflow publishes a pre-release with
`latest-beta.json`. Cyril's machine follows the `beta` channel (`beta`
in the `channel` file beside the state directory), so it updates first;
watch its `/health` version and `logs/update.log` before merging
`develop` to `main` and tagging stable.

## How to roll back

Revert through `develop` to `main` and tag (the next release supersedes
the bad one), or pin one machine with
`python3 packaging/install.py --version X`. The installer itself
restores the old pointer automatically when the new release fails its
health check.

A release before 0.6.9 recorded a `--feed` install's own build number in
`<home>/feed-serial`, so a local build could leave a number the published
feed has not reached. Every scheduled check then refuses the real feed with
`stale feed serial N is older than M`. Delete `<home>/feed-serial` to clear
it; the next unpinned update records the channel's own serial. Installs from
0.6.9 on leave that file alone.

## Safe update, restart, reinstall

Updates do not wait for idle traffic. Activation swaps the `current`
pointer, then sends one `TERM`: launchd `KeepAlive` restarts the router on
the held socket into the new release, so new connections queue in the
kernel while the outgoing process finishes the requests it already
accepted. An in-flight chat completes on the old release, and on macOS
nothing is refused. Linux has no socket activation (see below): the
outgoing process owns the port and stops accepting for the length of its
drain, so a connection attempted mid-handover fails until the new process
binds. One writer at a time, enforced by an advisory lock on
`install.lock` in the router home, so a scheduled pass and a manual run
cannot interleave.

Prefer `TERM` over `bootout` for a live service: `bootout` unloads the
definition, and if the following `bootstrap` does not take, the machine is
left with no router and no `KeepAlive` to recover it. A reload is only for
a plist launchd has actually loaded differently (a changed interpreter or
port), and it must wait for the label to leave the domain before
bootstrapping: `bootout` returns success while the job is still draining,
and a `bootstrap` issued in that window fails with `Bootstrap failed: 5`.
The installer never boots out the scheduled updater from inside it, since
that job is what runs the installer.

On failed health the installer restores the old pointer, TERMs again, and
then verifies a loaded job is serving the restored version, bootstrapping
it if launchd has none; it says the router is not serving rather than
reporting a clean rollback over a dead machine. A version that fails three
times is parked, so a bad release stops costing a service restart every
fifteen minutes; run the installer by hand to retry. The count lives in the
state file, which is what parks it on the production feed -- that feed is
read through the GitHub CLI and carries no ETag to save. Linux uses
systemd user service restart with a 150-second stop timeout; the launcher
opens the same loopback port after the old process drains. It does not use
launchd socket activation. Failed upgrades restore the prior catalogue too.

Releases are installed only when feed version, manifest version and the
bundled `packaging/VERSION` marker all agree; any mismatch aborts
before any file, pointer or launchd change. `--feed` selects one run's
source and is never pinned, so a local test feed cannot freeze future
updates. Run local feed experiments in a disposable OS user session or VM,
with its own service manager and Codex configuration. A different `--home`
alone does not isolate the fixed user service names or client configuration;
see [Linux upgrade and verification](linux-upgrade.md).

## Layout of the state directory

`~/.codex/mixed-model-router/` holds `current` (pointer to the live
release), `releases/` (current plus two priors for rollback depth), `logs/`,
`mixed-router-state.json` (port and token, mode 600),
`activation.json` (config receipt), and `openrouter.key` (mode 600).
The code may live anywhere; only this directory matters at runtime.

## Verification after a Codex upgrade

Run the suite, then the base probe against the installed router and
confirm discovery, one exact callback, and the marker in the final
answer. If the app-server protocol changed, probes fail before any
user task does; do not ship model changes until the base probe passes.

## Latency phase fields (aggregate-only comparison recipe)

`request_completed` carries per-phase durations in milliseconds plus the
long-standing cumulative fields (`local_prepare_ms`,
`upstream_headers_ms`, `first_chunk_ms`, `total_ms`), whose meanings are
unchanged:

| Field | Meaning |
|---|---|
| `read_ms` | Socket read plus body decode |
| `prepare_ms` | Provider selection plus body preparation |
| `connect_ms` | Upstream connection establishment (`connect()`) |
| `send_ms` | Request upload (`request()`) |
| `headers_ms` | Wait for upstream response headers (`getresponse()`) |
| `first_data_ms` | First upstream read-return inside adaptation (not provider TTFB on buffering paths) |
| `first_write_ms` | First successful downstream write (forwarding delay, not network TTFB) |
| `response_kind` | `sse`, `json`, or `other` (fixed values only) |
| `response_encoding` | `identity`, `gzip`, `deflate`, `br`, `zstd`, or `other` (fixed values only) |

`transport_error` carries the phases that completed before the failure;
absent later phases mean the request never got that far. To compare
builds, group by version/provider/model/stream/encoding over approved
existing logs, include failed/aborted counts with sample size and time
window, and use per-request ratios, never ratios of unrelated
percentiles. Paid direct-versus-router comparisons need separate
explicit authority.

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

## Client activation and subscription policy

`--client codex` (the default) manages the Codex config block, picker
preservation, global guidance, and the activation receipt.
`--client none` installs, updates, rolls back, and uninstalls the router
lifecycle without touching any client file; uninstall needs no receipt.
Switching an active Codex install to `none` restores the exact owned block
first, or refuses when the block was edited. The choice persists in router
state and survives scheduled updates.

Subscription routing is independent per client: `openai_mode` governs
Responses, `anthropic_mode` governs Messages when explicitly set, otherwise
Messages follows the legacy `openai_mode` fallback. Neither mode widens
access on migration; unsets keep prior behavior.

## Key rotation

Replace the `openrouter.key` file contents. No restart is needed; the
router reads the key per request.

## Per-portco model policy

Onboarding: add the user to the portco subgroup, resolve the slug subset
centrally against the current `models.json` (a department list must stay
within its portco list), and deliver `<home>/model-policy.json` (`0600`,
atomic write) with `portco`, `department`, `allowed_models`, `version`,
and `updated_at`. The router loads it at startup into
`state['allowed_models']`; both protocol policies gate OpenRouter slugs
on it, subscription rows unaffected. Offboarding: remove the user from
the subgroup and delete their OpenRouter key by id; the policy file goes
with the machine's decommissioning, never as a revocation control.

## Windows (Task Scheduler)

The Windows backend (`packaging/platforms/windows.py`) registers two
per-user tasks, `CodexMixedModelRouter` and `CodexMixedModelRouterUpdate`,
from XML it writes to `logs\*.task.xml`. Facts the design rests on, all
verified on Windows 11 on 2026-09-10: a logon trigger must name the
installing user (an unscoped one needs elevation and fails with "Access is
denied"); a repeating trigger needs a `StartBoundary`; `schtasks /delete`
leaves a running instance alive, so uninstall ends the tasks first;
re-registering a running task keeps its instance, so the updater can refresh
its own definition; and an interactive-token console task shows its window,
so both tasks run `pythonw.exe` through `task_launch.py` in the router home
(rewritten on every install), which appends stdout and stderr to
`logs\launchd.log` and `logs\update.log` (rotated at 1 MB, one backup). Every console child (`schtasks`, `icacls`, `whoami`, `python`,
`gh`) is spawned without a window.

Restart and update: the task allows one instance (`IgnoreNew`), so a
handover posts the authenticated `/shutdown`, waits for the instance to
leave the Running state (up to 180 seconds), then runs the task again; a
process still alive after that deadline is ended. `schtasks /query /tn
CodexMixedModelRouter /fo list /v` shows status, last run and last result
(`267009` means running). Key protection: the router home carries an
inheritable owner-only grant and the key and state files a plain one; a
widened ACL makes the router refuse the key at read time.

## Incidents

Check `/health`, then `logs/launchd.log`, then
`launchctl print` for the router agent (`schtasks /query` on Windows). Roll
back by re-running the installer with `--version` pointing at the previous
release.

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
