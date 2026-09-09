# Plan 060: Windows and Linux parity audit (read-only, then fix list)

> REJECTED RETRY DRAFT. Do not execute. See this folder's README and the active parent plan index.

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 6840312..HEAD -- codex_router packaging tools tests`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: plans/057-service-backend-interface.md
- **Category**: tests
- **Planned at**: commit `6840312`, 2026-09-09

## Why this matters

The audit found concrete POSIX assumptions in the request path and
lifecycle that will fail on Windows even after the service backend
exists — but several are load-bearing subtleties (mtime-ordering
tricks, advisory locking, permission bits) where a naive "fix" breaks
macOS/Linux. This plan first PROVES each gap with a failing-then-fixed
characterization test run through the Windows backend fake, then fixes
only the gaps with clean cross-platform answers, leaving genuine
platform differences declared in the backend. It depends on Plan 057
because the fixes land in the backend interface, not in scattered
`os.name` branches.

## Current state

Known POSIX assumptions with exact evidence (verify each yourself before fixing):

1. `codex_router/discovered.py:_stamp_after` (lines ~50-62) —
   hand-rolled mtime step/widen loop compensating for filesystem
   timestamp rounding ("Windows FILETIME has 100 ns granularity").
   The comment claims Windows awareness but no Windows test exercises
   it; the rounding-compensation loop is unverified against NTFS/ReFS.
2. `codex_router/credentials.py:28` — `if os.name != 'nt'` skips the
   owner-only permission check on Windows, silently accepting a
   world-readable key file. No test asserts the Windows behavior.
3. `packaging/service.py:install_lock` — uses `fcntl` on POSIX,
   `msvcrt.locking` on Windows, else warns and yields unserialized.
   The `msvcrt` leg has no test (no Windows CI leg exists).
4. `codex_router/activation.py` — `ctypes.CDLL(None).launch_activate_socket`
   wrapped in a broad `except Exception: pass` that returns None on any
   platform; correct on Windows only by accident (every Windows boot
   logs `socket_activation inherited=False`).
5. `packaging/install.py:do_install` — `os.getuid() if hasattr(os,
   'getuid') else 0` (~line 377) fabricates uid 0 on Windows for the
   launchd branch; after Plan 057 the launchd branch is gone but the
   `webbrowser.open(setup_url)` call and `os.chmod` calls need Windows
   verification.
6. `tools/disable.py` — `os.open(temp, O_WRONLY|O_CREAT|O_EXCL, 0o600)`
   and `os.replace`: atomic-restore semantics on Windows need proof
   (open-file replace behavior differs).

Repo conventions that apply here: characterization-test-first (prove the
gap with a red test through fakes, then fix), stdlib only, no network
in tests, `tests/_platform.py` + `tests/fakes.py` for platform faking.

## Commands you will need

| Purpose   | Command                                             | Expected on success |
|-----------|-----------------------------------------------------|---------------------|
| Tests     | `python3.14 -m unittest discover -s tests -t .`     | `OK`                |
| Compile   | `python3.14 -m compileall -q codex_router tools tests packaging` | exit 0   |
| Limits    | `python3.14 tools/check_source_limits.py`           | `failures=0`        |

## Scope

**In scope** (the only files you should modify):

- `tests/test_windows_parity.py` (create) — one characterization test per gap above
- Small, proven fixes in `codex_router/discovered.py`, `codex_router/credentials.py`, `packaging/service.py`, `codex_router/activation.py`, `tools/disable.py` — ONLY the gaps the red tests prove
- `packaging/windows_backend.py` — declare genuine platform differences there (e.g. ACL note instead of chmod)

**Out of scope** (do NOT touch, even though they look related):

- New features, new clients, new providers
- Live Windows machine acceptance — stays a release gate per `docs/operations.md`
- `docs/`, `README.md`, `CHANGELOG.md` — no user-visible change ships here

## Git workflow

- Branch: `advisor/060-windows-linux-parity` off `develop`
- Commit per step; message style `<type>: <short summary>`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Write the six red characterization tests

Create `tests/test_windows_parity.py` with one test per gap, all
hermetic (fake `run`, temp home, patched `os.name`/`sys.platform`
where the module under test branches on it — follow
`tests/_platform.py`):

1. discovered-stamp-ordering: simulate coarse-mtime filesystem (wrap
   `os.utime`/`stat` via stub) and assert `_stamp_and_prune` still
   evicts oldest-first.
2. credentials-permissions: with `os.name == 'nt'` faked, a
   world-readable key file must either raise or log a warning naming
   the Windows ACL remediation — assert whichever the fix chooses, but
   assert SOMETHING (today: silently accepted).
3. install-lock: exercise the `msvcrt` leg with a stubbed `msvcrt`
   module asserting second-holder yields False.
4. activation: assert `inherited_listener()` returns None WITHOUT
   logging a misleading event on non-macOS (or logs at most once at
   debug level).
5. install-uid: assert no `getuid`-fallback value reaches any Windows
   backend call (source + runtime assertion through the Plan-057
   `detect()` path).
6. disable-atomicity: assert the config-restore write is atomic under a
   stubbed Windows `os.replace` semantic (or document why it already is).

Run: all six must FAIL on the unmodified code (that failure is the
proof of the gap). Record each failure message in the commit message.

**Verify**: `python3.14 -m unittest tests.test_windows_parity -v` → 6 failures, each naming its gap

### Step 2: Fix only what Step 1 proved, one gap at a time

For each red test, implement the smallest fix that turns it green:

- discovered: if the widen-loop already survives the coarse-mtime
  stub, DELETE the test's false assumption and document why (valid
  outcome — not every characterization test proves a bug).
- credentials: prefer warning-plus-ACL-guidance over hard failure
  (a hard failure bricks existing Windows installs on upgrade).
- activation: early-return None on `sys.platform != 'darwin'` before
  touching ctypes (one branch, at the top, tested).
- install/disable: route through the Plan-057 backend; delete the
  `hasattr(os, 'getuid')` fallback if nothing references it after.

**Verify**: `python3.14 -m unittest tests.test_windows_parity` → `OK` (6 tests)

### Step 3: Full gate

**Verify**: `python3.14 -m unittest discover -s tests -t .` → `OK`;
`python3.14 tools/check_source_limits.py` → `failures=0`

## Test plan

- The six characterization tests ARE the test plan (red-then-green,
  committed red first in Step 1, green in Step 2).
- Full suite regression in Step 3.

## Maintenance note

Genuine platform differences (ACLs vs chmod, schtasks vs timers) live
in `packaging/windows_backend.py` with tests in
`tests/test_service_backend.py`, never as inline `os.name` branches in
shared code. Reviewers: any new `os.name`/`sys.platform` check outside
`service_backend.detect()` and `activation.py`'s darwin guard is a
rejection.

## STOP conditions

- If the drift check shows in-scope files changed since `6840312`, stop and reconcile.
- If a characterization test cannot be made to fail OR pass without
  touching production semantics you cannot prove (e.g. real NTFS
  behavior), convert it to a documented `skipUnless(sys.platform ==
  'win32')` live-acceptance test and move on — do not guess filesystem semantics.
- If any fix changes macOS/Linux golden behavior (existing tests fail),
  stop and report: Windows parity must not regress the proven platforms.

## Done criteria

- [ ] Six characterization tests, each either green-by-fix or converted to a named live-acceptance skip with evidence
- [ ] No silent Windows acceptance of world-readable keys
- [ ] No `getuid`-fallback or untested `msvcrt` leg remains
- [ ] `python3.14 -m unittest discover -s tests -t .` → `OK`
- [ ] `python3.14 tools/check_source_limits.py` → `failures=0`
- [ ] Status row for this plan updated in `plans/README.md`
