# Plan 056: Refactor the installer into platform backends

> Planning only. This document authorises no implementation, no staff-machine
> change, no release and no cutover. Each stage below names its own gate.

Priority P1; effort M; risk MEDIUM (the installer owns service lifecycle and
Codex configuration on every staff machine).
Planned 2026-09-09 at `9262e5a9bf8bc14aa1b5b330168ed28d0e33fcd8`.

## Outcome

`packaging/install.py` stops being a macOS installer with a Linux branch bolted
on. Each supported platform owns a backend module behind one interface, the
shared install/verify/update logic calls only that interface, and adding a
platform is a new backend plus its tests rather than another branch inside the
main install function.

First observable proof: `do_install` contains no `launchctl`, no `os.getuid()`
and no `Library/LaunchAgents` path; macOS and Linux both still pass a full
install, scheduled update, rollback and uninstall cycle; and
`tools/check_source_limits.py` reports `packaging/install.py` well under its
budget with room for a third backend.

## Why this is a prerequisite, not tidying

| Evidence (verified 2026-09-09, read-only) | Consequence |
|---|---|
| `packaging/install.py` is **699 lines** at `6840312` (696 before commit `4e87e5c`); `tools/check_source_limits.py` sets the `packaging` HARD limit at **700**. `packaging/service.py` is 601 | **One line of headroom.** The next line added to `install.py` fails the gate. A Windows backend cannot be added inline, and neither can anything else. The refactor is no longer optional |
| `packaging/install.py:78` `systemd_manager()` returns a manager on `linux` and `None` everywhere else; every `if manager: ... else: ...` treats `None` as "macOS" | Platform dispatch is a two-valued flag, so any third platform silently inherits the macOS path. This is exactly how Windows currently ends up writing launchd plists (Plan 057) |
| `packaging/install.py:86, 94, 643, 644` and `tools/disable.py:29` call `os.getuid()` unguarded on the non-Linux path | POSIX-only calls sit in code reached by every non-Linux platform, not in a macOS module where they belong |
| `packaging/install.py:370-395` computes `uid` and a `LaunchAgents` path in the shared body before dispatching | macOS specifics leak into shared code even where a manager exists |
| `packaging/service.py` already carries portable pieces (`install_lock` handles `fcntl` and `msvcrt`; `find_python` has a `win32` branch) | The shared layer is already partly portable. The gap is concentrated in `install.py`'s dispatch, which is what this plan moves |

## Verified current state

Read-only inspection of `9262e5a`, plus executed checks this session:

| Check | Observed |
|---|---|
| Test suite, macOS 15 / Python 3.14.4 | `Ran 471 tests` `OK` |
| Test suite, `python:3.14-slim` Linux container | `Ran 471 tests` `OK`, zero skips |
| Linux lifecycle, Debian trixie + real systemd user manager (container) | install, `/health` ok, scheduled update `0.6.8.0` to `0.6.8.7`, rollback, uninstall all succeeded (see Plan 058 for the evidence table) |
| Windows dispatch, simulated (`PLATFORM='win32'`, `os.getuid` removed) | `systemd_manager()` returns `None`; `restart_router()` and `stop_router()` both raise `AttributeError: module 'os' has no attribute 'getuid'` |
| CI platform coverage | `.github/workflows/check.yml` runs `ubuntu-latest` only; no macOS or Windows runner |

## Target shape

One interface, three implementations, no platform conditionals in the shared body.

```
packaging/
  install.py        shared: feed, download, verify, extract, self-test,
                    swap, config block, rollback, prune  (no platform code)
  service.py        shared helpers (unchanged responsibilities)
  platform/
    __init__.py     select() -> backend for sys.platform, or None
    darwin.py       launchd: plists, reload, updater job  (from install.py + launchd.py)
    linux.py        systemd user units and timer          (today's systemd.py)
    windows.py      Plan 057 lands here
```

Backend interface, derived from the calls the installer makes today:

| Method | Replaces |
|---|---|
| `check()` | `Manager.check()`; on macOS a no-op, on Windows the Plan 057 precondition |
| `install(python, release, state)` | `Manager.install()` and the whole `else:` plist branch at `install.py:373-395` |
| `restart()` / `stop()` | `restart_router()` / `stop_router()` |
| `ensure_updater()` / `start_updates()` | `ensure_updater()` and `Manager.start_updates()` |
| `ensure_serving(state, version)` | `ensure_serving()` in the rollback path |
| `uninstall()` | `Manager.uninstall()` and the `launchctl bootout` pair at `install.py:643-644` |
| `pinned_release()` | `loaded_updater_release()`, which exists only because launchd caches its loaded command |

`pinned_release()` returning `None` on Linux and Windows keeps `prune_releases`
honest without a platform test at the call site.

## Coordination with the concurrent updater split

A second review stream (lanes on `7581cc8` and `4e87e5c`) independently reached
the same 700-line wall and proposed a different cut: move `do_check_update` and
its helpers into a new `packaging/updater.py`. Both cuts are correct and they do
not conflict - one removes the update loop, the other removes platform dispatch -
but they touch the same file, so they must not run concurrently.

| | This plan's cut | The updater cut |
|---|---|---|
| Removes | Platform dispatch: launchd branch, `systemd_manager`, `uid`/`agents`, `restart_router`/`stop_router` | The scheduled-update loop: `do_check_update`, `_park`, failure accounting |
| Motivated by | Windows cannot be added while `None` means "macOS" | Immediate hard-limit relief; the code is already logically separate |
| Unblocks | Plan 057 | Any further edit to `install.py` at all |

**Sequencing:** the updater split should land **first**. It is smaller, it is
already specified, and it buys the headroom that makes this refactor comfortable
rather than surgical. Whichever lands first, the second rebases onto it; one
writer at a time, and the loser of the race does not start until the winner
merges.

Both cuts share the same mechanics, and both must honour them:

- A new module must be added to `bundle_files` in `packaging/release.py` and
  asserted in `tests/test_packaging.py::test_release_bundle_contains_deploy_list`,
  or installed bundles ship without it.
- It must be loaded the way `install.py` loads `service.py` and `systemd.py`,
  via `importlib.util.spec_from_file_location`. A plain `import packaging.x`
  collides with the third-party `packaging` distribution.
- The `_patch_attrs` / `_sync_seams` test seam model must keep working.

## Stages

Each stage is independently reviewable and testable, ordered so the installer
keeps working after every one. Sizes are estimates against the 800-line
staged-commit budget in the global instructions.

**Stage 1 - characterisation tests before any move.** Capture today's observable
behaviour of `do_install`, `do_check_update`, `do_rollback` and `do_uninstall`
on both current platforms, at the level of "which service calls happen in which
order". The existing `tests/test_install_lifecycle.py` and `tests/test_launchd.py`
already cover much of this; the gate is that the new tests fail if a call is
reordered or dropped, because that is exactly the regression a refactor risks.
*Gate: new tests pass on macOS and Linux and demonstrably fail against a
deliberately reordered copy.*

**Stage 2 - extract the interface and the two existing backends.** Create
`packaging/platform/`, move `systemd.py` to `linux.py` behind the interface, and
lift the launchd branch out of `do_install` into `darwin.py`. Behaviour identical;
no new features. `packaging/release.py:bundle_files` must be updated to ship the
new package, or installed bundles will be missing their backend - check this
explicitly, it is the one change that a passing test suite would not catch.
*Gate: full suite on macOS and Linux; the container lifecycle run from Plan 058
repeats clean; `check_source_limits` shows the new headroom.*

**Stage 3 - remove platform conditionals from the shared body.** Delete
`systemd_manager()`, the `uid`/`agents` computation, and every `if manager:`
pair. `select()` returns a backend or `None`, and `None` means unsupported
rather than macOS - which is the actual defect Plan 057 depends on being fixed.
*Gate: `rg 'launchctl|getuid|LaunchAgents' packaging/install.py` returns nothing;
both platforms pass the lifecycle run; and - if Plan 057 Stage 1 has already
landed - its unsupported-platform refusal still fires. `select()` returning
`None` must refuse before any router home is created, proven by a unit test on
the existing runners driving the simulated `PLATFORM='win32'` dispatch this plan
already uses for its own evidence. That test must **not** carry `unix_only` from
`tests/_platform.py`, and must not wait on the Stage 4 Windows job, which lands
after this stage and skips the install layer. Deleting `systemd_manager()` deletes the
function that refusal currently lives in, and no macOS or Linux lifecycle run
can detect its loss.*

**Stage 4 - guard it with CI.** Add macOS and Windows runners to
`.github/workflows/check.yml`. Windows runs the test suite only (the install
layer is skipped there until Plan 057). Without this the refactor is unprotected
on two of three targets, and the 2026-09-09 Windows fix already sits unguarded.
*Gate: all three runners green on a pull request.*

## Risks and how each is bounded

| Risk | Bound |
|---|---|
| A silent behaviour change strands a staff machine with no loaded service | Stage 1 lands before any code moves; the launchd convergence logic in `packaging/launchd.py` is moved verbatim, not rewritten |
| The new package is not included in release bundles | Called out explicitly in Stage 2; add a bundle-contents assertion to `tests/test_release.py` |
| Refactor and Windows work collide | Plan 057's backend work starts only after Stage 3 merges; its Stage 1 fail-closed refusal is independent and may land first. One writer per stream |
| Stage 3 silently removes Plan 057 Stage 1's Windows refusal | Stage 3's gate requires the refusal to survive the move. `check()` is defined on a backend, so a `None` return has no object to call it on: the shared body needs its own explicit refusal, not an implied one |
| Scope creep into rewriting the update logic | Out of scope below. This plan moves code and changes dispatch; it changes no feed, verification or rollback behaviour |

## Out of scope

Windows support (Plan 057), recipient prerequisites and platform gating
(Plan 058), the feed and signature model, the Codex configuration block format,
and any change to `codex_router/`.
