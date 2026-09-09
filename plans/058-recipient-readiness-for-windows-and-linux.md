# Plan 058: Recipient readiness for Windows and Linux

> Planning only. This document authorises no implementation, no staff-machine
> change, no distribution and no release. Each stage below names its own gate.

Priority P1; effort M; risk MEDIUM (the failure mode is a colleague stuck at a
prerequisite, not a broken machine).
Planned 2026-09-09 at `9262e5a9bf8bc14aa1b5b330168ed28d0e33fcd8`.
Complements Plan 054 (group distribution) and Plan 049 (three-OS install).
Windows readiness depends on Plan 057.

## Outcome

Someone who is handed this router can get it working without reading the
source, and anyone who cannot is told exactly why before anything is installed.

First observable proof: a colleague on a stock machine, given only a link and
one command, either reaches a healthy router or receives a single message
naming the one prerequisite they are missing and how to get it. No traceback,
no partial install, no silent no-op.

## Verified state: Linux works, Windows does not

Executed this session, not recalled.

### Linux - full lifecycle passed

Debian trixie container with a **real systemd user manager** (privileged,
host cgroups, `loginctl enable-linger`), Python 3.14.7, source at `9262e5a`
built into a local unsigned feed.

| Step | Result |
|---|---|
| Test suite, `python:3.14-slim` | `Ran 471 tests` `OK`, **zero skips** (macOS runs the same 471; Windows skips 100) |
| `systemctl --user show-environment` | rc=0, user manager available |
| Install `0.6.8.0` | `installed 0.6.8.0; health ok` |
| Service and timer | both `active` and `enabled` |
| `ExecStart` | `/usr/local/bin/python3.14 <home>/router_launch.py` - the pointer-file layout, not the legacy symlink |
| `/health` | `{"status": "ok", "version": "0.6.8.0", "inflight": 0, "draining": false}` |
| One-shot `--feed` persisted? | No `feed` file written - correct, the pin is not leaked into the timer |
| Scheduled update | `systemctl --user start ...update.service` installed `0.6.8.7`; `/health` confirmed the new version; service stayed `active` |
| Rollback | `--version 0.6.8.0` restored it; `/health` confirmed |
| Uninstall | config restored, service `inactive`, timer `not-found` |

This closes the gap `docs/compatibility.md` currently records as open ("no
successful automatic update or rollback was demonstrated"). Update that file.

**Caveat, stated plainly:** a container is not a desktop session. It proves the
code, the units, the timer and the update chain. It does not prove behaviour
under a real login session, a graphical desktop, or the contributor's Arch
machine. Stage 3 below is that gate, and it is not optional.

### Linux is not one platform

Owner question 2026-09-09: "is it good for all Linux - Ubuntu, Arch, Debian?"
The code is. The prerequisite is not, and that is the whole difference.

| Distribution | Router code | systemd user services | Python 3.14 from its own archive |
|---|---|---|---|
| Ubuntu 26.04 LTS | Expected fine | Yes | **Yes** |
| Fedora 42 | Expected fine | Yes | **Yes** (`3.14.5-1.fc42`) |
| Ubuntu 24.04 LTS | Expected fine | Yes | **No** (3.12) - a PPA has it, but that is an IT decision |
| Debian 13 (trixie) | **Verified** - the lifecycle table above ran here | **Verified** | **No** (3.13), and no PPA route at all |
| Arch | Reported working by the contributor (`docs/compatibility.md`) | Expected fine | Untested here - no `linux/arm64` image on this host. Rolling, so expected yes |

Two caveats that matter more than they look:

- The Debian lifecycle proof used a 3.14 interpreter **placed into the container
  by hand**, because Debian 13 has none. It proves the router, the units and the
  update chain. It does not prove a Debian recipient can reach that starting point.
- Only Debian was exercised end to end. Ubuntu, Fedora and Arch are reasoned
  from shared systemd behaviour, not observed. Stage 3 is where that stops being
  an assumption.

### Windows - not installable

See Plan 057 W1-W8. In short: the installer takes the macOS path, crashes on
`os.getuid()`, leaves an orphaned router home, and there is no autostart
mechanism or key protection. **Do not send the current build to Windows users.**

## Prerequisites a recipient actually needs

These are the real distribution blockers, and none of them is currently checked
up front.

| Prerequisite | Why it bites | Current behaviour |
|---|---|---|
| **Python 3.14** | Genuinely required: `codex_router/router.py:11` imports `compression.zstd` (3.14 stdlib) to decode Codex's zstd request bodies, and the table above shows the two most widely deployed Linux targets cannot supply it. **This is the single biggest obstacle to handing the router to someone.** Owner decision and options in [Plan 059](059-python-314-interpreter-provisioning.md) | `find_python` probes sensible paths, then prints `No Python 3.14 found: brew install python@3.14` - macOS advice, on every platform |
| **GitHub CLI, signed in, with read access to a private repo** | `FEED_URL` points at releases in the private `software-combined/SC_OpenRouter_adapter`; anonymous asset URLs 404, so `fetch` shells out to `gh release download` | Fails at download time with "Private router updates require GitHub CLI (gh)" - correct message, but discovered late and repeated silently every 15 minutes by the timer |
| **A systemd user manager (Linux)** | Headless servers, some containers and minimal WSL setups have none | Already refused cleanly and early by `Manager.check()`. This one is right |
| **Codex desktop or Claude Code installed and signed in** | The router configures a client that must exist | Not checked; the config block is written regardless |
| **Login-session persistence (Linux)** | `packaging/systemd.py` deliberately does not enable lingering, so a user service stops at logout. Fine for a desktop, wrong for a headless box | The README says lingering is not enabled; the consequence at logout is unstated |

## Stages

**Stage 1 - one preflight, before anything is written.** A `--preflight` path (and
the same checks run at the top of a normal install) that reports every missing
prerequisite at once, with the platform-correct remedy, and exits without
creating a router home. Platform-aware interpreter guidance replaces the `brew`
string (Plan 057 Stage 5 covers the same line; land it once, in whichever plan
executes first).
*Gate: on a machine with no Python 3.14 and no `gh`, the output names both, and
`~/.codex/mixed-model-router` does not exist afterwards.*

**Stage 2 - decide and document how recipients get the bundle.** The private-repo
plus `gh` requirement is the single largest friction point, and it is a
distribution decision rather than a code one.

| Option | Trade-off |
|---|---|
| Keep private repo, require `gh` | No new infrastructure; every recipient must install `gh` and hold repo read. Ties distribution to GitHub org membership |
| Private feed behind the Entra group gate in Plan 054 | Matches the group-distribution direction already planned; needs that work to land first |
| Signed public bundles, private feed metadata | Widest reach, largest change; reopens the signature question that was deliberately closed |

*Recommendation: fold into Plan 054 rather than solving twice. This plan's job
is to make the requirement visible at Stage 1, not to pick the transport.*
*Gate: owner decision recorded here and in Plan 054.*

**Stage 3 - Linux acceptance on a real desktop.** Run the checklist in
`docs/linux-upgrade.md` on the contributor's Arch machine and one Ubuntu or
Fedora desktop: install, health, log out and back in, scheduled update,
rollback, uninstall, both client paths. The container run above is the
rehearsal, not the acceptance.
*Gate: results recorded in `docs/compatibility.md` with distribution, Python
version and Codex desktop version. Only then does Linux count as supported.*

**Stage 4 - a recipient-facing install page.** The README is written for someone
with the repository checked out; it opens with `python3 packaging/release.py`,
which is a maintainer action. A recipient needs: what they must have first, one
command, what to expect, how to check it worked, and how to remove it. One page
per supported platform, no build step.
*Gate: someone who has not seen the repository follows it start to finish
without asking a question.*

**Stage 5 - rewrite the README for recipients, not maintainers.** The README is
186 lines written for someone who already has the repository checked out, and
several of its claims no longer hold. Owner direction 2026-09-09: it is
outdated as a whole and the platform matrix is rewritten only once Windows is
proven (Plan 057 Stage 6), so this stage lands in two parts.

Audited 2026-09-09 against the verified state above:

| README location | Problem | Correct position |
|---|---|---|
| "Install on macOS or Linux" | The only install path shown is `python3 packaging/release.py --out dist` then install from a `file://` feed. That is a maintainer building their own release. A recipient has no checkout and no build step | A recipient needs one command against the published feed. This is the single biggest gap for handing the router to someone |
| `packaging/install.sh` and `packaging/install.ps1` | Both exist and neither is mentioned anywhere in the README | Document the supported entry point, or delete the wrappers. `install.ps1` must not be advertised before Plan 057 Stage 5 fixes its interpreter lookup |
| "The router itself runs on macOS, Windows, and Linux; the managed installer provisions macOS `launchd` or Linux `systemd`" | Literally true and practically misleading. A Windows reader will try, and gets the Plan 057 W1-W3 traceback | An explicit table: per platform, is the **router** supported, and is the **installer** supported. Two separate columns |
| Requirements section | Names Python 3.14 but not the GitHub CLI. The `gh` requirement appears only at `README.md:37-38`, inside the "Linux: managed systemd user services" subsection, though every platform's updates go through the same private feed | Prerequisites belong in one place that applies to all platforms |
| Arch Linux AUR instructions | A vendor-specific AUR command is the first thing any Linux reader meets, above the generic install section | Move below the generic path |
| Security: "the key file is owner-only" | True on macOS and Linux, false on Windows: `codex_router/credentials.py:27` skips the check when `os.name == 'nt'`, and the `0o600` writers only set the read-only attribute there | Qualify per platform until Plan 057 Stage 2 makes it true everywhere |
| "Runtime files" list of 27 files | Stale and would produce a broken install. It names `packaging/router_launch.py` alone, while `packaging/release.py:bundle_files` ships `install.py`, `launchd.py`, `service.py`, `systemd.py`, `update_launch.py` and `VERSION` as well (verified against a built tarball this session). A test pins the `codex_router/` and `tools/` half of the list, but nothing pins the `packaging/` half, which is where it is wrong | Delete or generate the list, **and update its guard test in the same change**: `tests/test_packaging.py::test_readme_runtime_list_matches_files` scrapes every backticked `codex_router/` and `tools/` path out of the README and asserts the set equals `FILES`, so deleting the list alone turns the suite red. The list does not drift silently today - that test is what stops it - but it duplicates `bundle_files`, which is the real answer |
| Linux session persistence | `packaging/systemd.py` deliberately does not enable lingering, so the router stops at logout. The README says lingering is not enabled but never what that means at logout | State it, with the `loginctl enable-linger` remedy for anyone who wants it running headless |

**Stage 5a (now):** correct the claims that are wrong today - the platform
matrix marking Windows installer as unsupported, prerequisites in one place,
the Windows key-file qualification, the stale runtime-files list, and a
recipient install path for macOS and Linux.
*Gate: no claim in the README that a reader could act on and fail. Every
statement about a platform matches a row in `docs/compatibility.md`.*

**Stage 5b (after Plan 057 Stage 6):** flip Windows to supported, document its
install command and service model, and remove the Windows caveats added in 5a.
*Gate: Plan 057 Stage 6 acceptance recorded first. The README is never the
place a platform is first declared supported.*

## Risks and how each is bounded

| Risk | Bound |
|---|---|
| Someone sends the current build to a Windows colleague | Plan 057 Stage 1 (fail closed) is the cheapest guard and should land first, independent of the rest |
| The container result is read as Linux acceptance | Stated as a caveat above and gated by Stage 3. Do not update the support matrix before Stage 3 |
| `gh` requirement discovered only when the first update fires | Stage 1 checks it at install time, when a person is present to fix it |
| Recipients on distributions with no 3.14 package give up | Stage 1 names the concrete remedy per platform; bundling an interpreter is Plan 059's owner decision, not taken here |

## Out of scope

The installer refactor (Plan 056), the Windows backend (Plan 057), key
federation (Plan 055), the group-distribution transport itself (Plan 054),
code signing, and bundling a Python interpreter (Plan 059).
