# Plan 057: Windows install and service support

> Planning only. This document authorises no implementation, no staff-machine
> change, no release and no Windows rollout. Each stage below names its own gate.

Priority P1; effort L; risk HIGH (a new service lifecycle plus credential
storage on an operating system with no current coverage).
Planned 2026-09-09 at `9262e5a9bf8bc14aa1b5b330168ed28d0e33fcd8`.
Dependencies are per stage, not per plan: **Stage 1 is independent of
Plan 056 and may land at any time**; Stages 3 to 6 need Plan 056 Stage 3; and
Stage 5's interpreter message additionally needs the Plan 059 owner decision;
and Stage 7 needs Plan 056 Stage 4, which is what adds the Windows CI runner.
Extends the Windows commitment in Plan 049.

## Outcome

A Windows staff member runs one command, gets a router that starts with their
session and keeps itself updated, and their OpenRouter key is protected on disk
to the same standard POSIX gets from mode `0600`.

First observable proof: on a Windows 11 machine, the installer completes, the
router answers `/health` with the installed version, the machine survives a
sign-out and sign-in with the router running again, one scheduled update
installs a newer bundle, a rollback restores the previous one, and the key file
is readable only by the installing user (verified with `icacls`, not with
`os.stat`).

## Verified current state: Windows is not supported today

The router core is portable. The install and service layer is not, and the
failure is a traceback rather than a refusal.

| Finding | Evidence (2026-09-09) |
|---|---|
| **W1 - Windows falls into the macOS path.** `systemd_manager()` returns a backend on `linux` and `None` elsewhere, and every caller reads `None` as "use launchd" | `packaging/install.py:78`, and the `if manager: ... else: ...` pairs at `:370-395`, `:414-424`, `:639-648` |
| **W2 - Hard crash on POSIX-only calls.** `restart_router()` and `stop_router()` call `os.getuid()`, which does not exist on Windows | Executed this session with `PLATFORM='win32'` and `os.getuid` removed: both raise `AttributeError: module 'os' has no attribute 'getuid'`. Same call at `install.py:643-644` (uninstall). `tools/disable.py:29` has it too but is unreachable from the installer, which always passes `ROUTER_RESTORE_ONLY=1` (see Stage 4) |
| **W3 - Partial install then traceback.** On first install the bundle extracts and `current` is written; the launchd probe then fails, health is marked failed, `_clear_current()` runs, and `stop_router()` raises uncaught | Traced through `install.py:373-455`. The Codex config block is written only after a healthy check, so `config.toml` is left untouched - the machine is left with an orphaned router home, not a broken Codex |
| **W4 - No autostart mechanism exists.** No Task Scheduler, Windows service, Startup-folder or registry Run entry anywhere in the source | `rg -i 'schtasks|winsw|nssm|Task Scheduler|pythonw|winreg|sc\.exe'` matches only plan and doc prose, never `packaging/` or `codex_router/` |
| **W5 - The API key is unprotected on Windows.** The owner-only gate is explicitly skipped there, and nothing replaces it with an ACL | `codex_router/credentials.py:27` reads `if os.name != 'nt' and key_file.stat().st_mode & 0o077`. Every writer (`install.py:160`, `codex_router/setup.py:120-131`) passes mode `0o600`, which Windows reduces to the read-only attribute |
| **W6 - The bootstrap picks the wrong interpreter.** `install.ps1` runs `python`, which on a stock Windows 11 profile resolves to the Microsoft Store stub and opens the Store instead of running | `packaging/install.ps1` (3 lines). `find_python` already knows the right answer - it has a `py -V:3.14` candidate at `service.py:116` - but the wrapper never gets that far |
| **W7 - macOS advice shown to Windows users.** The no-interpreter path prints `No Python 3.14 found: brew install python@3.14` on every platform | `packaging/install.py:305-309` |
| **W8 - No Windows CI.** The 2026-09-09 portability fix was verified once by hand and nothing guards it | `.github/workflows/check.yml` runs `ubuntu-latest` only. PR #18/`0682d3d` states the service layer "has no Windows equivalent" and skips 100 tests there |

W1-W3 mean the honest answer today is that the installer must not be run on
Windows at all. W5 means Windows support cannot ship on POSIX mode bits alone.

## Design decisions to settle before Stage 3

These change scope materially and are owner calls, not defaults to assume.
Only the key-protection row feeds Stage 2; the other four are backend inputs
and must not hold up the ACL work.

| Decision | Options | Planning recommendation |
|---|---|---|
| Autostart mechanism | (a) Scheduled Task at logon, (b) real Windows service via a wrapper, (c) Startup shortcut | **(a) Scheduled Task at logon**, run as the signed-in user with highest privileges off. It is per-user like launchd agents and systemd user units, needs no admin rights, no third-party wrapper, and matches the existing "one router per OS user" decision in Plan 049. A real service runs as SYSTEM or needs stored credentials, which conflicts with a per-user key file |
| Update scheduling | Second Scheduled Task on a 15-minute repeat, mirroring the launchd `StartInterval` and systemd timer | Same mechanism as the router task; no new moving parts |
| Restart-in-place semantics | launchd keeps the listening socket; systemd does not. Windows will not either | Accept the Linux behaviour: a connection attempted mid-handover fails until the new process binds. Document it rather than build socket inheritance |
| Key protection | `icacls` to grant the installing user only, and break inheritance | Must be enforced and **verified after writing**, then checked at read time by a Windows branch in `credentials.py`, so W5 cannot regress silently |
| Console window | `python.exe` shows a console for the lifetime of the router | Use `pythonw.exe` for the router task; keep `python.exe` for the updater so its output still reaches the task log |

## Stages

Ordering note: key protection comes **before** the first real-machine install.
A normal install writes `openrouter.key` (`install.py:ensure_credentials`) and
`mixed-router-state.json`, and until the ACL work lands both sit unprotected on
a staff machine. The router can boot keyless while a setup nonce is pending
(`codex_router/runtime.py:52-58`), so a key on disk is not strictly required to
reach `/health`, but the setup window writes the same unprotected file the
moment someone uses it. Harden first, then install.

**Stage 1 - fail closed before anything else.** Independent of Plan 056 and
worth landing on its own: make `systemd_manager()` (later `select()`) refuse an
unsupported platform with a clear message before the installer creates a router
home or extracts a bundle. Today Windows gets a traceback after a partial
install; it should get one sentence telling it Windows is not supported yet.
*Gate: on a Windows machine (or the simulated dispatch used above) the installer
exits non-zero with the message and leaves no router home behind. Plan 056
Stage 3 must carry this refusal across the refactor - see its gate.*

**Stage 2 - protect the key, before any real-machine install.** Add ACL
hardening where the key is created (`install.py:ensure_credentials`,
`codex_router/setup.py`) and a Windows read-time check in `credentials.py` that
replaces the POSIX gate skipped at `credentials.py:27`. Apply the same treatment
to `mixed-router-state.json`, which carries the loopback token. Create each file
inside a directory that already has the restricted ACL; never widen then narrow.
*Gate, deliberately not requiring an install: no Windows install can complete
until Stage 3 exists, because Stage 1 refuses the platform. Prove the write side
directly instead - drive `ensure_credentials` and the `codex_router/setup.py`
key window on a Windows machine, then `icacls` both `openrouter.key` and
`mixed-router-state.json` and see only the installing user - and prove the read
side by widening the ACL and confirming the router refuses the key, mirroring
POSIX. The same `icacls` check on a real install belongs to Stage 3's gate.*

**Stage 3 - the Windows backend.** Implement `packaging/platform/windows.py`
against the Plan 056 interface: create, replace and delete both Scheduled
Tasks; restart; stop; report whether the router task is registered. Uses
`schtasks` (present on every Windows edition) or the `win32com` task scheduler
API if a dependency is acceptable - `schtasks` is preferred for zero
dependencies. `router_launch.py` and `update_launch.py` already resolve the
active release at exec time and need no change.
*Gate: offline unit tests for XML/command generation, plus a real Windows 11
install reaching `/health` with the installed version. Stage 2 must have landed
first, so that install writes a protected key rather than an exposed one -
confirm with `icacls` on that first install. The task must also be verified
**registered and running** after creation, with any group-policy refusal
reported by name rather than read as success.*

**Stage 4 - Windows uninstall.** The uninstall path crashes at
`packaging/install.py:643-644`, where the `launchctl bootout` pair calls
`os.getuid()` because `manager` is `None`. Plan 056's `uninstall()` interface row
covers this once the backend exists; verify it end to end here. Note
`tools/disable.py:29` carries the same call but is **not** the uninstall
blocker: `install.py:630-632` always invokes it with `ROUTER_RESTORE_ONLY=1`, and
`disable.py:26` gates the `launchctl` block on that variable, so it never runs
from the installer. It bites only on a standalone `disable.py` run.
*Gate: uninstall completes on Windows, removes both Scheduled Tasks, restores
the Codex config, and leaves no registered task behind.*

**Stage 5 - bootstrap and messages.** Rewrite `install.ps1` to prefer
`py -3.14`, then `py -3`, then `python`, and to fail with an actionable message
naming the python.org download when none is a 3.14. Make the no-interpreter
message in `install.py` platform-aware (W7): `brew` on macOS, the distribution
or python.org on Linux, python.org or `winget install Python.Python.3.14` on
Windows. The exact wording depends on the Plan 059 decision: if a private
interpreter is adopted, the message changes from "install this yourself" to a
download the installer performs.
*Gate: on a Windows machine with no Python, the wrapper prints the actionable
message and does not open the Microsoft Store.*

**Stage 6 - lifecycle acceptance on a real machine.** Install, `/health`,
sign-out and sign-in, scheduled update to a newer bundle, rollback, uninstall,
and confirm uninstall leaves no registered tasks.
*Gate: the full sequence passes on a designated Windows staff machine and the
result is recorded in `docs/compatibility.md` with the Codex desktop version.*

**Stage 7 - unskip and guard.** Remove the `tests/_platform.py` skips for the
tests the Windows backend now satisfies, and make the Windows CI runner from
Plan 056 Stage 4 required.
*Gate: Windows CI green with the install-layer tests running, not skipped.*

## Risks and how each is bounded

| Risk | Bound |
|---|---|
| Scheduled Tasks are silently disabled by group policy on a managed device | Stage 3 verifies the task is registered *and* running after creation, and reports the policy failure by name rather than assuming success |
| The key is written before the ACL is applied, leaving a window | Stage 2 lands before any real-machine install and proves itself without one. Create the file in a directory that already carries the restricted ACL, then verify after writing; never widen-then-narrow |
| Antivirus or SmartScreen blocks an unsigned downloaded bundle | Surface as a named failure in Stage 6 acceptance. Code signing is out of scope here and becomes a separate decision if it bites |
| Windows work destabilises the two working platforms | Plan 056 Stage 1 characterisation tests plus three-runner CI. No shared-body edits in this plan beyond Stages 1, 2, 4 and 5; Stage 3 only adds a new backend file |
| A half-built Windows path ships to staff | Nothing is offered to Windows users until Stage 6 passes on a real machine. Stage 1 keeps the honest refusal in place until then |

## Out of scope

The installer refactor (Plan 056), recipient prerequisites and rollout
(Plan 058), code signing, Windows ARM, WSL as a target (a WSL install is a
Linux install and already works subject to Plan 058), and any change to routing
or model behaviour.
