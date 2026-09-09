# Plan 057: One service-backend interface for launchd, systemd, and Windows

> REJECTED RETRY DRAFT. Do not execute. See this folder's README and the active parent plan index.

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 6840312..HEAD -- packaging tools`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/056-runtime-provider-client-domain-split.md
- **Category**: tech-debt
- **Planned at**: commit `6840312`, 2026-09-09

## Why this matters

Service management is currently split three ways with no shared
contract: `packaging/launchd.py` (114 lines, converge-and-verify
helpers), `packaging/systemd.py` (83 lines, a `Manager` class with
`check/install/start_updates/restart/stop/uninstall`), and a Windows
path that is two thin wrappers (`install.ps1`, `install.sh`-style) plus
`sys.platform == 'linux'` branches scattered through
`packaging/install.py` (`systemd_manager()`, `restart_router()`,
`stop_router()`, `do_uninstall()`) and a platform ternary in
`tools/disable.py` (lines 27-29: systemctl on Linux, `launchctl bootout`
otherwise). There is no Windows service backend at all: a Windows
install runs the router with no supervisor, no updater timer, and an
uninstall path that issues `launchctl bootout` on a machine without
launchctl. Adding Windows support today means copying the Linux
branches a third time. After this plan one `ServiceBackend` interface
exists, each OS implements it once, and `install.py`/`disable.py` call
the interface without a single `sys.platform` branch.

## Current state

The relevant files, each with one line on its role:

- `packaging/systemd.py` (83 lines) — Linux backend: `Manager(home, run)` with `check/install/start_updates/restart/stop/uninstall`, `SERVICE`/`UPDATE`/`TIMER` unit names
- `packaging/launchd.py` (114 lines) — macOS converge helpers: `plist_path/job_loaded/loaded_command/unload/load/reload_job`
- `packaging/service.py` (601 lines) — shared plist/feed/lock/health helpers plus `restart_service/ensure_updater/reload_main_service`
- `packaging/install.py` (699 lines, at the 700 entrypoint hard limit) — owns install/upgrade/rollback/uninstall; branches on `sys.platform == 'linux'` in `systemd_manager()` (~line 78), `restart_router()` (~line 83), `stop_router()` (~line 89), `do_install()` (~line 380), `do_uninstall()` (lines 619-651)
- `tools/disable.py` (31 lines) — config restore plus a platform ternary (lines 27-29) choosing systemctl vs launchctl
- `packaging/install.ps1` (3 lines) — thin wrapper delegating to install.py
- `packaging/install.sh` (3 lines) — thin wrapper delegating to install.py

Key excerpts as they exist today:

`packaging/systemd.py` exposes the de-facto interface every backend must match:

```python
class Manager:
    def __init__(self, home, run): ...
    def check(self): ...        # refuse without a user manager
    def install(self, python, release): ...
    def start_updates(self): ...
    def restart(self): ...
    def stop(self): ...
    def uninstall(self): ...
```

`tools/disable.py:27-29` — the branch this plan deletes:

```python
    command = (['systemctl', '--user', 'stop', 'codex-mixed-model-router.service']
               if sys.platform == 'linux' else
               ['launchctl', 'bootout', f'gui/{os.getuid()}/com.local.codex-mixed-model-router'])
```

Repo conventions that apply here, with exemplar:

- Backend modules run on Python 3.9+ (installer context), stdlib only.
  Follow `packaging/systemd.py` style: small module, one class, `run`
  injected for hermetic tests.
- Test pattern: `tests/test_systemd.py` and `tests/test_systemd_runtime.py`
  fake the `run` callable and assert unit-file writes and systemctl argv.
  New backends get the same treatment; never shell out in tests.
- `packaging/install.py` is at 699/700 lines: this plan must NET-REDUCE
  its size by moving branches into backends, never grow it.

## Commands you will need

| Purpose   | Command                                             | Expected on success |
|-----------|-----------------------------------------------------|---------------------|
| Tests     | `python3.14 -m unittest discover -s tests -t .`     | `OK`                |
| Compile   | `python3.14 -m compileall -q codex_router tools tests packaging` | exit 0   |
| Limits    | `python3.14 tools/check_source_limits.py`           | `failures=0`        |

## Scope

**In scope** (the only files you should modify):

- `packaging/service_backend.py` (create) — the `ServiceBackend` interface + `detect()` factory
- `packaging/launchd_backend.py` (create, from `launchd.py` + launchd halves of `service.py`) or keep `launchd.py` and add the adapter class there
- `packaging/systemd.py` — add the adapter so `Manager` satisfies the interface unchanged where possible
- `packaging/windows_backend.py` (create) — Task Scheduler backend (schtasks / XML task def), initially implementing `check/install/restart/stop/uninstall` with the updater as a scheduled task; see Step 2
- `packaging/install.py` — replace platform branches with backend calls only (must shrink)
- `tools/disable.py` — replace the systemctl/launchctl ternary with a backend call
- `tests/test_service_backend.py` (create), plus backend-specific tests

**Out of scope** (do NOT touch, even though they look related):

- Router request-path code (`codex_router/`) — Plan 056 owns that move
- Feed signing/verification (`codex_router/feed_verify.py`) — untouched
- `docs/`, `README.md`, `CHANGELOG.md` — no user-visible change ships here
- Actual Windows acceptance hardware runs — this plan lands the code seam with faked-`run` tests; live Windows proof stays a release gate per `docs/operations.md`

## Git workflow

- Branch: `advisor/057-service-backend-interface` off `develop`
- Commit per step; message style `<type>: <short summary>` (`feat`/`fix`/`refactor`/`test`/`chore`/`docs`)
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Define the interface and adapt the two existing backends

Create `packaging/service_backend.py` (target under 120 lines) with:

```python
class ServiceBackend:
    name = 'interface'  # 'launchd' | 'systemd' | 'windows'
    def check(self): raise NotImplementedError
    def install(self, python, release): raise NotImplementedError
    def start_updates(self): raise NotImplementedError
    def restart(self): raise NotImplementedError
    def stop(self): raise NotImplementedError
    def uninstall(self): raise NotImplementedError

def detect(home, run):
    import sys
    if sys.platform == 'linux': from .systemd import Manager; return Manager(home, run)
    if sys.platform == 'win32': from .windows_backend import Manager; return Manager(home, run)
    from .launchd_backend import Manager  # macOS default
    return Manager(home, run)
```

Wrap the existing `packaging/systemd.py:Manager` unchanged if it
already satisfies the six methods (it does: check/install/
start_updates/restart/stop/uninstall). Add a `packaging/launchd_backend.py`
`Manager(home, run)` class exposing the same six methods by composing
the existing `packaging/launchd.py` helpers (`load/unload/reload_job`)
with the plist renderers in `packaging/service.py` (`render_plist`,
`render_update_plist`, `write_plist`, `restart_service`,
`ensure_updater`). Do not change plist contents or unit contents in
this step.

**Verify**: `python3.14 -m compileall -q packaging` → exit 0

### Step 2: Implement the Windows backend against Task Scheduler

Create `packaging/windows_backend.py` (target under 200 lines,
Python 3.9+, stdlib only) with a `Manager(home, run)` class
implementing the six interface methods via `schtasks`:

- `check()`: `schtasks /Query /TN <router-task>` must execute (or
  `where schtasks` must resolve); else `SystemExit` with a message
  naming the missing Task Scheduler, mirroring systemd's
  `Linux installation requires a running systemd user manager` style.
- `install(python, release)`: create/update two tasks (router at logon
  + updater every 15 min) pointing at the stable home launchers
  (`router_launch.py`, `update_launch.py`), never per-release paths
  (same rule as `service.py:render_update_plist`).
- `restart()/stop()`: `schtasks /Run` and `/End` on the router task.
- `start_updates()`: enable the updater task.
- `uninstall()`: `/Delete /F` both tasks; leave the router home in
  place for the operator, mirroring the Linux/macOS message.

All subprocess access goes through the injected `run` callable so tests
stay hermetic. Quote interpreter paths with spaces (Windows default
`C:\Program Files\...`) — use `subprocess.list2cmdline`-safe argv
lists, never string concatenation.

**Verify**: `python3.14 -m compileall -q packaging` → exit 0

### Step 3: Rewire install.py and disable.py onto the interface

In `packaging/install.py`: delete `systemd_manager()`,
`restart_router()`, `stop_router()` and every `sys.platform` branch;
replace each call site with `service_backend.detect(home, run)`.
`do_uninstall()` keeps its config-restore-first ordering (restore
`tools/disable.py` with `ROUTER_RESTORE_ONLY=1`, fail closed when the
restore marker is absent) but delegates service removal to
`backend.uninstall()`. Net effect must be FEWER lines in install.py
than the 699 baseline — confirm with `wc -l packaging/install.py`.

In `tools/disable.py`: replace lines 27-29's ternary with:

```python
from packaging.service_backend import detect  # or equivalent import
detect(root, subprocess.run).stop()
```

keeping the `ROUTER_RESTORE_ONLY=1` early-return behavior (config-only
restore when set).

**Verify**: `rg -n "sys\.platform|os\.name" packaging/install.py tools/disable.py` → no hits

### Step 4: Tests and full gate

Add `tests/test_service_backend.py`:

- `detect()` returns the systemd Manager on faked linux, launchd
  Manager on faked darwin, Windows Manager on faked win32 (patch
  `sys.platform` the way `tests/test_systemd.py` fakes `run`).
- Windows Manager emits the expected `schtasks` argv for
  install/restart/stop/uninstall with a space-containing interpreter
  path, asserting argv-list (not string) invocation.
- install.py contains no `sys.platform` reference (source assertion,
  mirroring the Step 3 grep).
- `do_uninstall` ordering test: config restore runs before
  `backend.uninstall()`, and a failed restore leaves services running
  (extend the existing uninstall test in `tests/test_install_lifecycle.py`
  style with fakes).

**Verify**: `python3.14 -m unittest discover -s tests -t .` → `OK`;
`python3.14 tools/check_source_limits.py` → `failures=0`

## Test plan

- New `tests/test_service_backend.py` (4+ cases above), modeled on `tests/test_systemd.py` (fake `run`, assert argv + file writes).
- Existing `tests/test_systemd.py`, `tests/test_systemd_runtime.py`,
  `tests/test_launchd.py`, `tests/test_install_lifecycle.py` must stay
  green unmodified in intent (import-path updates only if Plan 056
  renamed modules).
- No real `schtasks`/`systemctl`/`launchctl` invocations in tests; no network.

## Maintenance note

A fourth OS backend (or a per-machine supervisor variant) is a new
module implementing the six methods plus one `detect()` line. Reviewers:
reject any new `sys.platform` branch in `install.py` or `disable.py` —
route it through the backend.

## STOP conditions

- If the drift check shows in-scope files changed since `6840312`, stop and reconcile.
- If `packaging/install.py` grows above 699 lines, stop: the plan
  requires a net reduction; split or simplify instead of growing.
- If any plist/unit/task content for macOS or Linux changes
  byte-for-byte behavior (unit-file golden tests fail), stop and report:
  this plan is a seam change, not a service-definition change.
- If the suite drops below its incoming pass count, stop and report.

## Done criteria

- [ ] `packaging/service_backend.py` defines the six-method interface + `detect()`
- [ ] No `sys.platform`/`os.name` branch remains in `packaging/install.py` or `tools/disable.py`
- [ ] `packaging/install.py` is shorter than 699 lines
- [ ] `python3.14 -m unittest discover -s tests -t .` → `OK`
- [ ] `python3.14 tools/check_source_limits.py` → `failures=0`
- [ ] Status row for this plan updated in `plans/README.md`
