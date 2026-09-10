# Plan 092: Make the default test suite offline and cover the untested ingress guards

> Planning only. Implement only under a later implementation instruction.
> Drift check: `git diff --stat a985197..HEAD -- tests/test_runtime_lock.py tests/test_providers.py tests/test_handler.py tests/test_tool_adapter.py tools/ .github/workflows/release.yml packaging/release.py tests/test_packaging.py`
> Read changed code and preserve current behavior before edits.

## Status and first proof

- Priority P1; effort S; risk LOW; confidence HIGH; category tests; depends on none.
- Planned at `a985197`, 2026-09-10.
- First proof: `python3.14 -m unittest discover -s tests -t .` runs with no network access (no
  skipped pin test hiding a failure), the suite touches no real router home, and the three ingress
  guards are covered by failing-if-removed tests.

## Why this matters

1. `tests/test_runtime_lock.py:92-161` downloads all four pinned CPython archives
   (~226 MB total) inside the default suite and `skipTest`s on `OSError` (`:122-123`). The repo
   rule is "no network calls in tests" (AGENTS.md §1); offline runs silently skip, so a stale pin
   passes green. `release.yml:26` is the only CI job that runs the suite, so the download happens
   on every local gate run and every release build.
2. `tests/test_providers.py:259-271` (`test_compact_remembers_discovered_tools`) patches only
   `summarize`; `compact` calls `remember` (`ai_router/providers.py:300`) which writes
   `~/.codex/mixed-model-router/discovered-tools/` and prunes the oldest entry above 16
   (`ai_router/discovered.py:32-42,63-82`). Running the suite pollutes or evicts real operator state.
3. Three ingress guards have no tests: websocket 426 (`ai_router/router.py:159-161`),
   `Transfer-Encoding` rejection (`:291`), and the zstd decoded-too-large bound (`:294-301`).

## Current state (verified at a985197)

- `tests/test_runtime_lock.py:92-103` holds the expected size/exec/licence table; `:112-116`
  `urllib.request.urlopen(entry['url'], timeout=30)` capped read; `:117-121` re-raises `HTTPError`;
  `:122-123` skips on `OSError`; `:124-161` asserts size, sha256, exec/licence members, and tar
  member path safety.
- `tests/test_tool_adapter.py:18-26` defines the isolation pattern:
  ```python
  def _isolated_home(test):
      tmp = tempfile.mkdtemp()
      test.addCleanup(shutil.rmtree, tmp, True)
      _MEMORY.clear()
      test.addCleanup(_MEMORY.clear)
      patcher = mock.patch.dict(os.environ, {'ROUTER_HOME': tmp})
      patcher.start()
      test.addCleanup(patcher.stop)
      return tmp
  ```
- `tests/test_handler.py:123-142` shows the raw-connection and `zstd.compress` patterns already in use.

## Scope

**In scope**: `tests/test_runtime_lock.py`, `tests/test_providers.py`, `tests/test_handler.py`,
new `tools/verify_runtime_pins.py`, `.github/workflows/release.yml`, `packaging/release.py` and
`tests/test_packaging.py` only if their file lists are explicit.
**Out of scope**: `packaging/runtime.lock` content, `ai_router/router.py` behavior, the router
runtime, any change to `tests/fakes.py`.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Offline proof | `python3.14 -B -m unittest tests.test_runtime_lock` | pass with **no network**, zero skips |
| Focused | `python3.14 -m unittest tests.test_providers tests.test_handler tests.test_runtime_lock` | pass |
| Full suite (offline) | `python3.14 -m unittest discover -s tests -t .` | exit 0, no downloads |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | exit 0 (tools budget 400/700; new file fits) |

## Steps

### Step 1: isolate the discovered-tools test (commit 1)

In `tests/test_providers.py:259-271`, wrap the test body with the `_isolated_home` pattern. Reuse
the existing helper by importing it (`from tests.test_tool_adapter import _isolated_home` — there is
precedent for cross-test imports in this repo) or by moving it to `tests/fakes.py` and updating both
callers; prefer the smallest diff that leaves one definition.

**Verify**: run the focused module; then `ls ~/.codex/mixed-model-router/discovered-tools/` before
and after a run shows no new file (do not delete existing operator files).

### Step 2: cover the three ingress guards (commit 2)

Add to `tests/test_handler.py`, following its existing helpers (`_start_server`, `_post`) and
asserting both the status and that no upstream call is recorded:

- websocket 426: `GET` on an authenticated non-health path with `Upgrade: websocket` → 426
  (`WEBSOCKET_REJECTED`).
- `Transfer-Encoding: chunked` on `POST /…/responses` with a body → 413 `INVALID_REQUEST_SIZE`.
- zstd oversize: patch `ai_router.router.MAX_BODY` to a small value inside the test, POST a
  `Content-Encoding: zstd` body that decodes past it → 413 `BODY_TOO_LARGE`.

**Verify**: each new test fails if its guard branch is removed; focused module passes.

### Step 3: move the pin download to a release qualification tool (commit 3)

Create `tools/verify_runtime_pins.py` (stdlib only, no router imports) that:
- reads `packaging/runtime.lock` and downloads each pinned archive with the capped read and the
  existing size / sha256 / exec / licence / tar-member-safety assertions (port them verbatim from
  the test, including the link-target depth walk);
- exits non-zero on any mismatch; treats network `OSError` as a hard failure (never skip);
- supports `--dry-run` to print the four URLs without fetching, so a local executor can validate
  the script shape without network.

Then in `tests/test_runtime_lock.py`: delete only the download leg (the `urlopen`/size/sha256/tar
assertions). Keep the fully-offline assertions: `provisionable` checks, the exec/licence path table,
`select` mapping, and any lock-schema coverage — these must still pass with no network.
Wire the new tool into `.github/workflows/release.yml` before the build step (pinned actions only;
use the same `python-version: "3.14"` setup). Do NOT add the tool to the runtime closure lists in
`tests/test_packaging.py` (FILES/README are runtime-only; adding it breaks
`test_readme_runtime_list_matches_files`). `packaging/release.py` bundles `tools/` by glob; confirm
that, and only if the bundle list enumerates all tools explicitly, add it there.

**Verify**: `python3.14 -B -m unittest tests.test_runtime_lock` passes with network disabled
(e.g. `ROUTER_OFFLINE=1` is not needed — simply confirm no skip paths remain in the module);
`python3.14 tools/verify_runtime_pins.py --dry-run` exits 0 and prints four URLs.

## Done criteria

- [ ] No `urlopen`/`skipTest` in `tests/` for runtime pins (`rg -n "skipTest|urlopen" tests/test_runtime_lock.py` → no matches).
- [ ] `python3.14 -B -m unittest tests.test_runtime_lock` passes offline with no skips.
- [ ] Three new handler tests exist and fail against a guard-removal patch.
- [ ] `tools/verify_runtime_pins.py` wired into `release.yml`; bundle list updated only if it enumerates tools explicitly (never the runtime FILES/README lists).
- [ ] Full suite, compile and limit gates pass; only in-scope files changed.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- Release-time pin verification cannot be added to `release.yml` (workflow constraints): stop and
  report before deleting the test leg; losing both would ship unverified pins.
- `tools/` files are not available to the release job checkout: stop and report.
- Moving the helper breaks other tests' import order: stop; prefer duplicating the six-line helper
  locally over a fragile import graph.

## Maintenance notes

- Pin updates now follow: edit `runtime.lock` and the expected table in `tools/verify_runtime_pins.py`,
  run the tool with network, then release.
- The suite must stay runnable on a fully offline machine; any future test needing bytes belongs in
  `tools/` behind an explicit invocation.
- Reviewers: confirm no skip path remains and the CI step ordering (pins verified before build).
