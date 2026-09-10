# Plan 103: Move launchd-specific helpers out of the 680-line service module

> Planning only. Implement only under a later implementation instruction.
> Drift check: `git diff --stat a985197..HEAD -- packaging/service.py packaging/launchd.py packaging/platforms/darwin.py tests/test_launchd.py tests/test_interpreter_resolution.py tests/test_install.py`
> Read changed code and preserve current behavior before edits.

## Status and first proof

- Priority P3; effort M; risk MED; confidence HIGH; category tech-debt; depends on none (run after 101).
- Planned at `a985197`, 2026-09-10.
- First proof: `packaging/service.py` drops below its 680-line count, launchd rendering/reload lives
  in `packaging/launchd.py`, and the launchd + installer suites stay green.

## Why this matters

`packaging/platforms/darwin.py:27-87` delegates every lifecycle step back into
`packaging/service.py` (`render_plist`, `render_update_plist`, `write_plist`,
`main_plist_needs_reload`, `reload_main_service`, `ensure_updater`, `loaded_updater_release`, ...),
while the Linux backend wraps a dedicated `packaging/systemd.py` (`platforms/linux.py:11-14`). The
architecture document (`docs/architecture.md:55-56`) still records this as transitional debt with
Plan 056 already DONE, so nobody owns it. `service.py` (680 lines) mixes launchd rendering with
feed, state, log and bundle-home helpers; a Darwin change requires reading all of it.

## Current state (verified at a985197; line refs refreshed at 12c834b)

- `packaging/service.py` owns: `render_plist` (:228), `render_update_plist` (:248),
  `write_plist`, `plist_differs`, `main_plist_needs_reload` (:374-438), `command_matches`,
  `same_interpreter`, `running_under`, `reload_main_service` (:539-549), `restart_service` (:360-372),
  `ensure_updater`, `loaded_updater_release` (:509-521), `_require_absolute` — alongside
  `health`, `wait_version`, `ensure_serving` (:524-536), `install_lock` (:327-357),
  `rotate_log` (:552-576), feed helpers (:297-357) and state writes (:604-636).
- `packaging/launchd.py` already owns domain primitives `job_loaded`, `loaded_command`, `unload`,
  `load`, `reload_job`, `plist_path` and takes `run`/`sleep` as parameters (114 lines).
- `packaging/install.py:89-99` binds module-level seams from `_svc`, including `restart_service` and
  `write_plist`; `_sync_seams` (`:301-310`) mirrors `run/health/wait_version/ensure_serving`.
- Callers that must keep working: `packaging/install.py:79-94` binds nine launchd names from `_svc`
  at module level (`main_plist_needs_reload`, `same_interpreter`, `ensure_updater`,
  `loaded_updater_release`, `reload_main_service`, `render_plist`, `render_update_plist`,
  `restart_service`, `write_plist`). Tests call through `svc.*`
  (`tests/test_interpreter_resolution.py:56-70`), `install_mod.*` (`tests/test_install.py:203,433`;
  `tests/test_interpreter_resolution.py:218-220`), and `install_mod.same_interpreter`
  (`tests/test_launchd.py:249-251`). Enumerate before moving; never rely on this list alone.

## Scope

**In scope**: `packaging/service.py`, `packaging/launchd.py`, `packaging/platforms/darwin.py`,
the call sites the seam enumeration identifies (test updates only), `config/source-limits-baseline.json`,
`plans/README.md` (status row only). `packaging/install.py` is NOT edited: its bindings stay
satisfied by delegations.
**Out of scope**: `health`, `wait_version`, `ensure_serving`, `install_lock`, `rotate_log`, feed and
state helpers (stay in service.py), `packaging/systemd.py`, behavior of any plist content.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Enumerate seams | `rg -n "(svc\|_svc\|install_mod)\.(render_plist\|render_update_plist\|write_plist\|plist_differs\|main_plist_needs_reload\|command_matches\|same_interpreter\|running_under\|ensure_updater\|reload_main_service\|restart_service\|loaded_updater_release)" packaging tests tools ai_router` | every hit reconciled before any move |
| Focused | `python3.14 -B -m unittest tests.test_launchd tests.test_interpreter_resolution tests.test_install tests.test_install_lifecycle` | pass before and after |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | exit 0; baseline updated for `service.py` (680 → new) |

## Steps

### Step 1: move the launchd helpers into launchd.py (commit 1)

Move these implementations verbatim, converting module-global references (`run`, `_sleep`,
`LABEL`, `UPDATE_LABEL`, `UNLOAD_TIMEOUT_S`, `LOAD_TIMEOUT_S`, `_agents`) into parameters or
module-level constants in `launchd.py` as appropriate (it is a leaf; it must not import `service`):

`render_plist`, `render_update_plist`, `write_plist`, `plist_differs`, `main_plist_needs_reload`,
`command_matches`, `same_interpreter`, `running_under`, `ensure_updater`, `reload_main_service`,
`restart_service`, `loaded_updater_release`, `_require_absolute`.

In `service.py`, keep thin delegations for **every** name `packaging/install.py` binds at module
level (`install.py:79-94`: `main_plist_needs_reload`, `same_interpreter`, `ensure_updater`,
`loaded_updater_release`, `reload_main_service`, `render_plist`, `render_update_plist`,
`restart_service`, `write_plist`). Do not edit `install.py`: the delegations keep it importing.
Update every other call site the enumeration finds. Carry `run`, `_sleep`, labels and timeouts into
the moved functions as explicit parameters or launchd-level module state; moved code must never fall
back to `time.sleep` or hardcoded timeouts that tests patch on `service`. `platforms/darwin.py` then
calls `launchd` for the moved helpers (like `platforms/linux.py` calls `systemd`), while
`ensure_serving`/labels still come from `svc`.

**Verify**: focused suites pass. Run the seam-enumeration command first and reconcile every hit
(`svc.`, `_svc.`, `install_mod.`) before any move; do not add catch-all aliases.

### Step 2: update the test call sites (same commit)

Update every call site the enumeration identified to the new owner. The known set includes
`tests/test_interpreter_resolution.py:56-70` (`svc.*`) and `:218-220` (`install_mod.*`),
`tests/test_install.py:203,433`, and `tests/test_launchd.py:249-251`
(`install_mod.same_interpreter`). Keep the tests' assertions identical, and keep the patch targets
(`_patch_attrs`, `_svc` mirrors) reaching the moved code.

### Step 3: baseline and docs hook (same commit)

Run the size checker; update the `packaging/service.py` baseline entry to the new count (service.py
stays above the 400 soft limit, so the entry must match the new exact count).
Do not edit `docs/architecture.md` here; plan 104 retargets that line.

**Verify**: `python3.14 tools/check_source_limits.py` exits 0; `rg -n "render_plist" packaging/service.py`
shows no implementation (delegation or nothing).

## Done criteria

- [ ] Launchd rendering/reload/updater helpers live in `launchd.py`; `service.py` count is lower.
- [ ] All nine `install.py` bindings resolve (`main_plist_needs_reload`, `same_interpreter`, `ensure_updater`, `loaded_updater_release`, `reload_main_service`, `render_plist`, `render_update_plist`, `restart_service`, `write_plist`); `_sync_seams` unchanged.
- [ ] All launchd/installer suites pass with only the named call-site edits.
- [ ] Compile and limit gates pass; only in-scope files changed.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- The seam enumeration finds more than the named call sites: stop and report the list before
  updating anything; the move may need splitting.
- A moved function needs a value that only `service` can supply at import time: stop; that function
  stays in `service.py`.
- The seam enumeration finds a name the delegation list does not cover, or a patch target that no longer applies after the move: stop and report before editing anything.

## Maintenance notes

- New launchd behavior belongs in `launchd.py`; `service.py` keeps cross-platform concerns only.
- If the `systemd`/`launchd` asymmetry returns (a new backend), follow the linux pattern.
- Reviewers: verify no behavior changed in plist bytes or reload ordering.
