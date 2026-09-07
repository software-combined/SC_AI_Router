# Plan 045: Every push to `main` becomes a release that reaches every router within minutes, with a restart nobody notices

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 749a6b8d..HEAD -- <ROUTER_ROOT>`
> On any in-scope change, compare the "Current state" excerpts against the
> live code first; on a mismatch, STOP.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED (touches the service lifecycle on every machine; mitigated by drain, health check, rollback and a beta channel that Cyril's own machine follows first)
- **Depends on**: Plan 041 (installer, releases, update agent). This plan supersedes Plan 041 Step 6 (update cadence) and Step 8 (release trigger); Plan 041's amendment note points here.
- **Category**: dx / direction
- **Planned at**: commit `749a6b8d`, 2026-09-07

## Path convention

Repository root post-Plan 034 (`codex_router/...`, `packaging/...`, `tests/...`).

## Why this matters

Cyril's operating model is: push to `main`, everyone's router updates. Plan 041 gives a safe installer and a daily update check, but it still needs a manual version bump and a tag, and it restarts the router by stopping and starting it, which the README warns "interrupts requests in flight". For a tool that sits between a person and every model call they make, an update must arrive within minutes of a push, must never be applied while a request is in flight, and must not produce a single failed request when the process is replaced. This plan makes the release automatic on push, checks for updates every fifteen minutes with a beta channel for Cyril's own machine, drains in-flight requests before exit, and keeps the listening socket open across the restart so new connections wait instead of failing.

## Current state

- Plan 041 as written: release on tag `v*` with a manual `packaging/VERSION` bump; update agent `com.local.codex-mixed-model-router.update` runs daily at 10:00 and hands over to the downloaded bundle's installer; restart is `launchctl bootout` then `bootstrap`; the installer waits for `/health` `inflight == 0` before restarting.
- Router (`Router(ThreadingHTTPServer)`, `daemon_threads = True`, `router.py:69-76` at the planned commit) binds `('127.0.0.1', state['port'])` in `__init__`. `serve_forever()` runs in the main thread. There is no signal handling; `SIGTERM` from launchd kills the process immediately, including in-flight streams.
- LaunchAgent plist (author's machine): `KeepAlive true`, `RunAtLoad true`, `ThrottleInterval 10`, no `Sockets` key.
- Python 3.14 `socketserver.TCPServer` has `allow_reuse_port` (verified: `True` on the author's interpreter). macOS `launchd` supports socket activation through the plist `Sockets` dictionary and the C function `launch_activate_socket(const char *name, int **fds, size_t *cnt)` in `libSystem`, callable from Python with `ctypes`.
- Plan 035 added `inflight` to `/health` and `self.server.lock`.
- The Codex client has configurable request and stream retry behaviour (config keys `request_max_retries` and `stream_max_retries` are documented Codex options; confirm in the Codex config reference during Step 4 rather than assuming values).
- Repository CI policy (Plan 034 Step 5): top-level `permissions`, `concurrency` group, `timeout-minutes`, pinned action SHAs; deploy-style workflows use `cancel-in-progress: false`.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Tests | `python3.14 -m unittest discover -s tests -t . -v` | `OK` |
| Graceful restart by hand | `launchctl kill TERM gui/$(id -u)/com.local.codex-mixed-model-router` | router logs `draining` then `exit`, launchd restarts it; `/health` answers within 2 s |
| Watch the socket | `lsof -nP -iTCP:18749 -sTCP:LISTEN` | during a restart the listener is held by `launchd` (socket activation) or briefly absent (fallback) |
| Release status | `gh run list --workflow release.yml --limit 3` | `success` rows for pushes to `main` |

## Scope

**In scope**: `.github/workflows/release.yml`, `packaging/VERSION` (becomes `MAJOR.MINOR`), `packaging/release.py` (version composition), `packaging/install.py` (update cadence, ETag, jitter, graceful restart, channel), `codex_router/__main__.py` and `codex_router/router.py` (signal handling, drain, socket activation), LaunchAgent templates inside `install.py`, `tests/test_install.py`, `tests/test_lifecycle.py` (new), `README.md` "Updating" section, `docs/operations.md` release section.

**Out of scope**: Windows lifecycle (Plan 041 phase 2), any change to request handling, the catalogue, credentials.

## Git workflow

- Branch `codex/router-continuous-release-<yyyymmdd>`; commits `feat:`/`test:`/`chore:`. Do not push unless instructed. The first push to `main` after merge is itself the first automatic release, so merge only when Cyril says so.

## Steps

### Step 1: Version from the tree, release on push

- `packaging/VERSION` holds `MAJOR.MINOR` only (start `0.4`). `packaging/release.py` composes the full version as `MAJOR.MINOR.<build>` where `<build>` is `--build N` (CI passes `${{ github.run_number }}`) or `0` locally. `MANIFEST.json` gains `"git_sha"` (CI passes `${{ github.sha }}`) and `"channel"`.
- `.github/workflows/release.yml`: `on: push: branches: [main, beta]`; top-level `permissions: contents: read`; `concurrency: {group: release-${{ github.ref }}, cancel-in-progress: false}`; one job, `timeout-minutes: 15`, job-scoped `permissions: contents: write`; steps: checkout and setup-python 3.14 (pinned SHAs), unit tests, `python packaging/release.py --out dist --build "$GITHUB_RUN_NUMBER" --sha "$GITHUB_SHA" --channel "$( [ "$GITHUB_REF_NAME" = main ] && echo stable || echo beta )"`, then create the tag and release: for `main`, `gh release create "v$VERSION" dist/*.tar.gz dist/latest.json --generate-notes --latest`; for `beta`, `gh release create "v$VERSION-beta" dist/*.tar.gz dist/latest-beta.json --prerelease --generate-notes` where `latest-beta.json` is the same document under the other name. The installer already compares 3-tuples, so `0.4.57` supersedes `0.4.56`.
- Keep `CHANGELOG.md` as a human log per notable change; it is no longer a release gate (the commit log is).

**Verify**: push a trivial docs change to `beta` (with Cyril's go-ahead): `gh release list --limit 1` shows `v0.4.<N>-beta` as a pre-release with two assets; `curl -sL https://github.com/software-combined/codex-model-router/releases/download/v0.4.<N>-beta/latest-beta.json` returns JSON with that version.

### Step 2: Fifteen-minute checks, ETag, jitter, channel

In `install.py`:

- The update agent plist uses `StartInterval 900` and `RunAtLoad true` instead of `StartCalendarInterval`.
- `--check-update` reads `home/channel` (`stable` default; Cyril writes `beta` on his machine), picks `latest.json` or `latest-beta.json` at `https://github.com/software-combined/codex-model-router/releases/latest/download/<name>` for stable and the newest pre-release asset for beta (resolve via `https://api.github.com/repos/software-combined/codex-model-router/releases?per_page=5` and take the first `prerelease: true` entry; anonymous API access is enough for a public repository, 60 requests per hour per IP, well above one per 15 minutes).
- Send `If-None-Match` with the ETag saved in `home/update-etag` and treat `304` as `up to date` without downloading. Sleep a random 0 to 120 seconds before the request so a hundred machines do not hit GitHub in the same second.
- Everything else in `--check-update` is unchanged from Plan 041 (verify, self-test, wait idle, hand over to the downloaded installer).

**Verify**: `tests/test_install.py::test_check_update_uses_etag_and_treats_304_as_current`, `::test_channel_beta_resolves_prerelease_feed`, `::test_jitter_bounded` pass; `launchctl print gui/$(id -u)/com.local.codex-mixed-model-router.update | grep -E "interval|StartInterval"` shows 900.

### Step 3: Drain on `SIGTERM`

In `codex_router/__main__.py` and `router.py`:

- `Router` gains `self.draining = False` and `self.drain_deadline_s = 120` (the upstream timeout).
- Install a `SIGTERM` handler in `__main__` that sets `server.draining = True`, logs `log_event('draining', inflight=server.inflight)`, and starts a thread that calls `server.shutdown()` (stops accepting), then waits until `server.inflight == 0` or the deadline passes, logs `log_event('exit', inflight=server.inflight, forced=<bool>)`, and calls `os._exit(0)` (daemon threads still streaming past the deadline are abandoned; that is the bounded worst case).
- While `draining` is true, new requests that still arrive (already accepted connections) get `503` with `Retry-After: 2`. `/health` reports `"draining": true`.

**Verify**: `tests/test_lifecycle.py::test_sigterm_waits_for_inflight_then_exits` (drive `Router` with a fake inflight counter and a patched `os._exit`), `::test_requests_during_drain_get_503_with_retry_after`.

### Step 4: Keep the socket open across the restart (socket activation)

- LaunchAgent template gains:

```xml
<key>Sockets</key><dict><key>Listeners</key><dict>
  <key>SockNodeName</key><string>127.0.0.1</string>
  <key>SockServiceName</key><string>18749</string>
  <key>SockFamily</key><string>IPv4</string>
  <key>SockType</key><string>stream</string>
</dict></dict>
```

  (the port comes from state).
- `codex_router/activation.py` (about 30 lines): `def inherited_listener() -> int | None` uses `ctypes.CDLL(None).launch_activate_socket(b"Listeners", byref(fds_ptr), byref(count))`; returns the first fd when the call returns 0 and count is at least 1, else `None`. Never raises; logs `log_event('socket_activation', inherited=<bool>)`.
- `Router.__init__(state, fileno=None)`: when `fileno` is given, construct with `bind_and_activate=False`, set `self.socket = socket.socket(fileno=fileno)`, and skip `server_bind`/`server_activate`; otherwise bind as today with `allow_reuse_port = True`.
- `__main__` passes `activation.inherited_listener()` to `Router`.
- The updater's restart becomes: swap `current`, `launchctl kill TERM gui/<uid>/<label>`, then poll `/health` until `version` equals the new version (up to drain deadline plus 30 s). Because launchd holds the listening socket, connections that arrive during the gap wait in the backlog and are served by the new process. Rollback path unchanged (swap back, kill again, poll for the old version).
- Fallback: when `inherited_listener()` returns `None` (tests, manual runs, Windows), the router binds itself, and the refused-connection window is the process start time (about 300 ms). Document it.

**Verify**: on the author's machine after installing: `lsof -nP -iTCP:18749 -sTCP:LISTEN` shows the socket owned by `launchd`; run the graceful restart command while a probe turn is streaming (`python3.14 tools/probe_codex_runtime.py z-ai/glm-5.3-flash --installed` in another terminal): the probe reports `desktop_runtime_tool_round_trip: passed`, the router log shows `draining`, `exit`, `socket_activation inherited=true`, and a client `curl` to `/health` issued in the gap returns 200 (it waits, never refuses). Record the observed gap.

### Step 5: Prove the seamless path with Codex, then document

Run a real short task in the Codex desktop app on an OpenRouter model while triggering `--check-update` against a beta release: the task must finish without a visible error. Also confirm in the Codex configuration reference what `request_max_retries` and `stream_max_retries` default to, and note them in `docs/operations.md` as the client-side safety net for the fallback (non-activation) case.

Update `README.md` "Updating": updates arrive within about fifteen minutes of a release; the router finishes what it is doing, then swaps; nothing to do. `docs/operations.md` gains: how to ship (merge to `main`), how to test first (push to `beta`, Cyril's machine is on the beta channel), how to roll everyone back (push a revert to `main`, or `install.py --version X` on one machine), and the drain deadline.

**Verify**: `grep -n "beta" docs/operations.md README.md` shows both; Cyril confirms the desktop task ran clean during an update.

## Test plan

- `tests/test_lifecycle.py`: drain waits then exits; forced exit at the deadline is logged with `forced: true`; 503 with `Retry-After` while draining; `Router(state, fileno=<socketpair fd>)` does not bind a port; `inherited_listener()` returns `None` when the symbol is missing (patch `ctypes.CDLL`).
- `tests/test_install.py` additions: ETag and 304; beta channel resolution from a fake API payload; jitter within bounds; plist contains `Sockets` and `StartInterval 900`; restart sequence issues `launchctl kill TERM` and polls for the new version (fake `run` and fake `fetch`).
- `tests/test_packaging.py`: `release.py --build 57` yields `0.4.57` and writes `git_sha` and `channel` into the manifest.

Verification: full suite `OK`.

## Done criteria

- [ ] A push to `beta` produced a pre-release with `latest-beta.json`; a push to `main` (when authorised) produced a release with `latest.json`.
- [ ] Author's machine on channel `beta` updated itself within 15 minutes of the beta push (`/health` shows the new version; `home/logs/update.log` has the run).
- [ ] During the restart, a streaming probe completed and a `/health` request in the gap returned 200; router log shows `draining`, `exit`, `socket_activation inherited=true`.
- [ ] Full suite `OK` including the new lifecycle and installer tests.
- [ ] `README.md` and `docs/operations.md` updated.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- `launch_activate_socket` is unavailable through `ctypes` or returns an error on the author's machine: implement the fallback path only, measure the refused window with a tight `curl` loop during a restart, and report the number before enabling automatic updates for staff.
- A Codex task shows a user-visible error during the update test in Step 5.
- The release workflow cannot create releases (permissions): do not widen `permissions` beyond job-scoped `contents: write`; report.
- Cyril has not authorised the first push to `main`.

## Maintenance notes

- The build number is the GitHub run number, so a re-run of a failed workflow produces a new version; the updater treats it as an update. That is intended.
- Reviewers should check that `os._exit` is only reachable from the drain thread after `shutdown()` and that the 503 path is exercised by a test.
- Deferred: signed manifests (Plan 041 note), a "pause updates" switch (`home/updates-paused` file honoured by `--check-update`) if a staff member ever needs to freeze a version; add when asked, it is five lines.
