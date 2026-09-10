# Plan 105: Provision and maintain a private CPython 3.14 runtime

> Planning only. No download execution, system changes, publication or
> staff-machine action is authorised here. Reconciled at `96db57f`, 2026-09-09.
> Read current instructions and compare in-scope source before implementation.

Priority P0 for distribution; effort M; risk MEDIUM. This plan implements the
runtime/bootstrap contract already selected in Plan 112 section 2 and Plan 106
sections 3/5. Plan 056 owns OS backends; 106 owns private hosting; 117 owns
recipient preflight and documentation. One runtime lock and one native
bootstrap per OS family serve all of them.

## Decision and first proof

Use a pinned, private, relocatable CPython 3.14 runtime. Automatic `apt`, PPA,
`dnf`, `pacman`, `winget`, Homebrew installation and system-Python replacement
are excluded from managed bootstrap. Existing interpreter detection stays as
a preflight/failure aid and an explicit verified override. This resolves the
old "C now, B later" choice: B is the delivery target, with C's diagnostics.

First proof: on a clean Mac without Python 3.14, the native wrapper verifies
and extracts the locked runtime in the router home, proves `compression.zstd`,
and starts the canonical installer. The same contract then works on qualified
Linux and Windows targets. No admin or system-PATH change.

The repository requires 3.14: `router.py:11` imports `compression.zstd`;
`service.py` probes that module as well as the version. The old archive table
was a dated container observation, not a portable dependency strategy. A
private runtime removes that prerequisite variance, but does not remove libc,
CPU, OS policy or native library limits.

## Runtime source and qualified targets

Use reviewed `astral-sh/python-build-standalone` install-only distributions,
as already specified in 112/106. Its [distribution metadata](https://gregoryszorc.com/docs/python-build-standalone/main/distributions.html)
records target triples, interpreter paths and native runtime requirements;
the [project](https://github.com/astral-sh/python-build-standalone) publishes
redistributable builds. Verify each selected archive and licences at
implementation time; no mutable runtime URL or invented checksum.

Initial pins: macOS arm64/x86_64, Linux x86_64/glibc and Windows x64.
Linux arm64 may have a pin only after qualification; it is not a first-release
requirement. Keep Windows ARM, musl and unsupported variants refused. Linux
acceptance covers Arch plus the Ubuntu or Fedora desktop in 117; a Debian
clean-start test preserves the earlier no-system-3.14 case. This is not
universal Linux support.

## Scope and conventions

Canonical repo: `/Users/cyrilallart/Documents/Github/SC_Codex_openRouter_adapter`.
Use one owned worktree targeting `develop`; never the primary checkout.
Runtime is stdlib-only; native shell/PowerShell bootstrap works without
Python. Preserve standalone file-based installer imports. Read
`packaging/install.{sh,ps1,py}`, `service.py`, `release.py`, stable launchers,
`tests/test_interpreter_resolution.py` and installer tests.

In scope: new `packaging/runtime.lock`, wrappers, a small generator for
lock-derived tables, interpreter selection/activation helpers, necessary
launcher integration, related tests, a release-workflow pin check, docs and
CHANGELOG/VERSION. Coordinate with 056/116/117/063/067. Hosting consumes 106;
do not create another feed, installer or infrastructure stack.

## Stages

### 1. Define and validate one lock

Record exact CPython/build versions, OS/CPU/libc constraints, immutable source
URL, private mirror path, archive format, SHA-256, executable-relative path
and licence files. Generate wrapper pin tables from it. Test missing/duplicate
target, invalid digest and table drift. Runtime versioning is independent of
router bundle version so unchanged interpreters are not downloaded repeatedly.

Gate: offline lock/generator tests pass; each target maps to one entry;
unsupported targets refuse. Synthetic archives unblock source before AWS.

### 2. Implement native bootstrap and safe extraction

Native preflight checks OS/CPU, current-user home, download/hash/extraction
tools, policy and selected delivery route before creating the router home.
A Python `--preflight` cannot be the first step on a machine without Python.
105 owns native entry; 117 owns the shared prerequisite results/remedies.

Fetch through 106's authorised private path, verify before execution, stage
under `<home>/runtime/<sha>/`. Match archive format to available native tools.
Reject traversal, absolute paths and links escaping the target; Windows ACL
protection precedes secret-bearing writes. Never disable TLS, execution
policy, quarantine or endpoint controls. Do not pipe downloads to a shell.
Invoke the canonical installer only after exact version and module checks.

Gate: wrong-hash/platform/traversal fixtures never execute; partial downloads
leave the active runtime untouched; a no-Python sandbox reaches the installer.
Blocked downloads report a concrete remedy.

### 3. Select and update without losing the working interpreter

Managed installs use the lock. A verified explicit `--python` is an
operator-owned override; preserve it across updates and report that its patch
lifecycle is external. Never alter system Python or global PATH. Persist the
effective absolute interpreter choice for scheduled operations.

Stage a candidate, prove version/native modules and candidate-bundle smoke
before activation. Coordinate existing idle/drain and stable launchers.
Rollback restores both bundle and interpreter selections. Keep runtimes
referenced by active and retained rollback releases; never prune by age alone.
Windows cannot overwrite/delete a running interpreter. Router and updater
must both use the intended interpreter after their next launch.

Gate: repeat install avoids unchanged downloads; candidate failure preserves
the old pair; update/rollback restores the intended pair; loaded schedulers
reference retained paths. Native lifecycle proof follows 056/116/117; it does
not block offline implementation.

### 4. Own CPython patch maintenance

SCG IT's router release maintainers own the lock/security updates, with Cyril
accountable for release decisions. Include CPython and bundled native
dependencies in the maintenance runbook. Add a weekly CI check that detects
newer compatible 3.14/security builds and creates or updates one review item.
It must not change pins, execute unreviewed binaries, publish or update staff
machines automatically. Use reviewed lock changes, beta qualification, then
approved stable publication.

A relevant security advisory triggers an out-of-cycle patch candidate. Apply
SCG's applicable patch deadlines and record exceptions before fleet rollout.
Preserve licences, provenance and rollback compatibility. Runtime downloads
change only when the reviewed lock changes.

Gate: synthetic new-build/advisory input produces one actionable review item
and no publication; pin-update tests verify new-runtime download and recovery
from activation failure. Do not create a schedule in the planning session.

### 5. Qualify clean-machine setup

Prove clean/repeat install, runtime patch, bundle update, rollback and uninstall
on designated macOS, Windows and Linux targets. Record OS/CPU/libc, Python
build, bundle and client versions. Windows source/CI may proceed before its
staff machine is named; staff acceptance remains open. Reuse 106's mirror and
117's walkthrough.

## Checks and STOP conditions

Run focused interpreter/bootstrap tests, then:

```sh
python3.14 -m unittest discover -s tests -t .
python3.14 -m compileall -q ai_router tools tests packaging
python3.14 tools/check_source_limits.py
git diff --check
```

Tests protect the contracts above. Run current pre-commit review for bounded
commits; integrate into `develop`, verify and clean the owned worktree.
Live publication, staff changes and paid probes retain their authority gates.

STOP for absent archives, unverified provenance/checksum/licence, unsupported
native requirements, policy bypass, writer conflict or inability to restore
the prior interpreter/bundle pair. No source-build or privileged package-manager
fallback is implied. Report source, native qualification, deployment and
maintenance readiness separately.
