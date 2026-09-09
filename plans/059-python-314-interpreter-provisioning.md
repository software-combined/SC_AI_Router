# Plan 059: Python 3.14 interpreter provisioning

> Planning only. This document authorises no implementation, no new release
> artefact, no third-party repository and no staff-machine change. The option
> chosen in "Decision required" is an owner call and is not assumed here.

Priority P0 for distribution; effort M; risk MEDIUM (a bundled runtime becomes
something we must keep patched).
Planned 2026-09-09 at `6840312`.
Blocks Plan 058 Stage 1 remedies and Plan 057 Stage 5.

## The problem in one line

The router genuinely requires Python 3.14, and most Linux machines cannot get
it from their own package archive, so the prerequisite - not the code - is what
stops us handing this to people.

## The requirement is real, not an arbitrary pin

`codex_router/router.py:11` imports `compression.zstd` and uses it at
`router.py:227-228` to decode `Content-Encoding: zstd` request bodies from
Codex. That module is stdlib from Python 3.14 only (PEP 784). `pyproject.toml`
declares `requires-python = ">=3.14"`, `packaging/service.py:59` sets
`MIN_PYTHON = (3, 14)`, and `find_python` probes candidates with
`import sys,compression.zstd`. Dropping to 3.13 would mean vendoring a zstd
decoder or refusing zstd bodies, which is a larger change than provisioning an
interpreter.

## Verified availability, 2026-09-09

The Linux rows were checked in containers on this host; `python3` is not
preinstalled on any of the base images, so those are archive contents rather
than image contents. The macOS and Windows rows are the known vendor routes,
not checks run here.

| Target | Python 3.14 from the distribution? | Evidence |
|---|---|---|
| Ubuntu 26.04 LTS | **Yes** | `python3.14` present in the archive |
| Fedora 42 | **Yes** | `python3.14.aarch64 3.14.5-1.fc42` in `updates` |
| Ubuntu 24.04 LTS | **No** - archive tops out at `python3.12` | deadsnakes PPA offers candidate `3.14.6-1+noble1` (verified), but adding a PPA to a managed machine is an IT policy decision, not an installer's |
| Debian 13 (trixie) | **No** - archive tops out at `python3.13` | No PPA equivalent. python.org, `pyenv` or a source build are the remaining routes, none tested |
| Arch | Untested here (no `linux/arm64` image on this host) | Rolling release; `docs/compatibility.md` records the contributor running the router under `python3.14`, so treat as available pending a real check |
| macOS | Yes, via Homebrew | `--install-python` already runs `brew install python@3.14` (`packaging/install.py:305-307`), macOS-only and non-root |
| Windows | Yes, via python.org or `winget` | Nothing automated; `install.ps1` does not even find an installed one (Plan 057 W6) |

The Linux lifecycle proof in Plan 058 was obtained by placing a 3.14 interpreter
into a Debian trixie container by hand. It proves the router and the systemd
units; it does not prove a recipient on Debian 13 can get that interpreter.

## Decision required from the owner

**"Should the installer install Python 3.14 itself?"** Yes in effect, but the
form matters, and the three forms have very different consequences.

| Option | What it means | Consequences |
|---|---|---|
| **A. Install through the system package manager** | Extend today's macOS `brew` path to `apt`/`dnf`/`pacman`/`winget` | Needs **root** on every Linux target. On Ubuntu 24.04 it also means adding the deadsnakes **PPA**, and on Debian 13 there is no package to install at all. Directly contradicts the deliberate design: per-user services, no privileged operation, no lingering. Distro-specific branches to maintain forever |
| **B. Ship a private relocatable interpreter** | The installer downloads a standalone CPython 3.14 build into `<home>/runtime/`, verifies its checksum, and points the service at it | **No root, no third-party repositories, no distro variance, identical on all three operating systems.** Also removes the Windows interpreter problem (Plan 057 W6) in the same stroke. Costs: one extra ~30-60 MB download per machine, and **we own patching that CPython**. The router is stdlib-only with zero third-party dependencies, so a private interpreter adds no other dependency surface |
| **C. Detect and instruct only** | Preflight names the exact remedy for the detected platform and stops | Zero privilege, zero new artefacts, smallest change. But on Debian 13 the honest instruction is "build Python from source or use pyenv", which most recipients will not do |

**Planning recommendation: C now, B as the target.**

C is needed regardless - even with B there must be a clear failure path when the
runtime download is blocked - and it is small enough to land inside Plan 058
Stage 1. B is what actually makes "hand this to a colleague" work on Ubuntu
24.04 and Debian 13, and it is one decision covering macOS, Windows and Linux
instead of six package-manager branches.

A is not recommended. Requiring root and a third-party APT source on managed
corporate machines is a bigger imposition than shipping our own runtime, and it
is the one option that breaks a design principle the router currently holds
everywhere.

## What B would involve, if chosen

Sketch only; not authorised by this document.

- Source: a relocatable CPython distribution published for
  `linux-x86_64`, `linux-aarch64`, `macos-aarch64`, `macos-x86_64` and
  `windows-x86_64`. Pin an exact build and record its checksum the same way
  `latest.json` pins the bundle, so the existing `verify_sha256` path is reused
  rather than a new trust mechanism invented.
- Placement: `<home>/runtime/`, versioned like `releases/`, so an interpreter
  upgrade is the same swap-and-verify operation as a bundle upgrade and can
  roll back the same way.
- Selection: `find_python` gains the private runtime as its **first** candidate
  and keeps every existing probe, so a machine that already has a suitable
  system 3.14 is unaffected and nothing regresses.
- Service wiring: unchanged. The launchd plist and systemd unit already take an
  absolute interpreter path (`_require_absolute`), which is exactly what a
  private runtime provides.
- Ongoing duty: a CPython security release means a new pinned build and a
  router release. This is the real cost of B and the reason it is an owner
  decision rather than an implementation detail.

## Risks and how each is bounded

| Risk | Bound |
|---|---|
| A bundled CPython goes unpatched | Make the pin visible in `latest.json` and treat a CPython security release like any other release trigger. If we will not commit to that, choose C and accept the narrower reach |
| The runtime download is blocked by a proxy or endpoint protection | The preflight from Option C stays in place as the fallback path and names the system-interpreter route |
| Bundle size makes updates painful on poor connections | Version the runtime separately from the release bundle so it downloads once, not on every router update |
| We build B and most machines never needed it | The table above already shows two of the four Linux targets actually checked cannot self-serve, including the most widely deployed LTS. Ubuntu 24.04 alone justifies it |

## Out of scope

Dropping the 3.14 requirement by vendoring a zstd decoder, the installer
refactor (Plan 056), the Windows service backend (Plan 057), and the feed
transport decision (Plan 054).
