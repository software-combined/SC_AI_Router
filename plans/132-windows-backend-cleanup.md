# Plan 132: Clean up the Windows backend (real launcher file, shared health, one wrapper)

> Planning only. Implement only under a later implementation instruction.
> Drift check: `git diff --stat b642de9..HEAD -- packaging/platforms/windows.py packaging/task_launch.py packaging/service.py packaging/release.py tests/test_windows_backend.py tests/test_windows_portability.py tests/test_packaging.py`
> Read changed code and preserve current behavior before edits.

> **Amendment 2026-09-12.** From the external router review
> (`plans/2026-09-12-external-router-review.md`): add `packaging/task_launch.py`
> to `packaging/release.py`'s inventory and the 3.9 parse-surface list in the
> same commit that creates it, and to `tests/test_packaging.py`'s required list
> so a dropped entry fails the bundle gate. CI now parses the shipped `.ps1`
> files (`.github/workflows/check.yml`), so a syntax error in a touched Windows
> script fails on the pull request instead of on a staff machine.

## Status and first proof

- Priority P3; effort S-M; risk MED; confidence HIGH; category tech-debt; depends on 123 (single
  inventory); run before or with 116 (Windows acceptance).
- Planned at `b642de9`, 2026-09-11.
- First proof: the Windows task launcher is a real, checked-in, parse-checked file; the backend uses
  the injected service's health; one CREATE_NO_WINDOW wrapper remains.

## Why this matters

`packaging/platforms/windows.py` (440 lines) carries three avoidable defects:

- `:108-137` embeds ~30 lines of Python inside `TASK_LAUNCHER_SOURCE` (written at `:145`), while the
  macOS equivalents are real shipped files copied by `service.install_launcher` (`:593-600`). The
  embedded source is invisible to `compileall` and the 3.9 surface parser.
- `:274` stores `self._svc` but never reads it; `:245-256` `_health` duplicates
  `service.health` (`service.py:262-273`) verbatim, so the two polls can drift.
- `:186-188` (`_run`) and `:278-280` (`Backend._call`) are two copies of the CREATE_NO_WINDOW
  subprocess wrapper.

## Scope

**In scope**: `packaging/platforms/windows.py`, new `packaging/task_launch.py`,
`packaging/release.py` + `tests/test_packaging.py` (inventory), Windows tests.
**Out of scope**: Windows install behaviour, Task Scheduler semantics, ACL code (`ai_router/winacl.py`),
plan 131's service changes.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Focused | `python3.14 -B -m unittest tests.test_windows_backend tests.test_windows_portability tests.test_windows_acl tests.test_packaging` | pass before and after |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | exit 0; windows.py baseline lowered |
| Surface | 3.9 parse test | pass; task_launch.py listed |

## Steps

1. **Real launcher file (commit 1).** Move `TASK_LAUNCHER_SOURCE` verbatim into
   `packaging/task_launch.py`. Write it like the other launchers: `service.install_launcher`
   copies the real file (or the backend copies it), so the installed artifact is byte-identical to
   the tested one. Update the release inventory (123) and the 3.9 surface list. Verify the file
   passes the same parse gate as the other packaging modules.
2. **Shared health (commit 2).** Replace `_health` with the injected `svc.health`; delete the
   copy. Keep timeout semantics identical (`timeout=20` default) and the call sites' behaviour.
3. **One wrapper (commit 3).** Collapse `_run`/`_call` into a single helper used by both paths;
   keep CREATE_NO_WINDOW flags and error handling identical.

**Verify**: focused tests; `rg -n 'TASK_LAUNCHER_SOURCE' packaging/` → no matches (or only a
comment); `wc -l packaging/platforms/windows.py` reduced.

## Done criteria

- [ ] Launcher is a real file, listed in the inventory and surface lists, parse-checked.
- [ ] Windows backend uses `svc.health`; one subprocess wrapper remains.
- [ ] No Windows behaviour change; offline tests green.
- [ ] Full suite, compile and limit gates pass; only in-scope files changed.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- The embedded launcher differs from what a real file would produce (indentation/encoding): stop
  and diff before switching; the installed bytes must not change except file provenance.
- Any Task Scheduler behaviour depends on the write path: stop and report.

## Maintenance notes

- Windows launcher edits now go through normal review and parsing like the other platforms.
- Real-machine acceptance stays with plan 116; this plan is offline-only.
- Reviewers: confirm the installed launcher bytes and the task XML are unchanged.
