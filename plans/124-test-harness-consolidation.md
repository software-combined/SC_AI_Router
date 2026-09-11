# Plan 124: Consolidate the test harnesses into shared test-support modules

> Planning only. Implement only under a later implementation instruction.
> Drift check: `git diff --stat b642de9..HEAD -- tests/`
> Read changed tests and keep every assertion identical unless the plan says otherwise.

## Status and first proof

- Priority P2; effort M; risk MED; confidence HIGH; category tech-debt; depends on plan 092
  (run after it; 092 adds the three ingress tests to `tests/test_handler.py`).
- Planned at `b642de9`, 2026-09-11.
- First proof: one HTTP/auth harness module serves the server-based tests; `test_install.py` is no
  longer a 500-line fixture library; the suite stays green with no assertion changes.

## Why this matters

The suite is 71 modules / ~13.6k lines, and its fixtures are spread across peer test files:

- `tests/test_mixed_router.py:143-169` defines `_test_state` / `_start_server` /
  `_start_auth_server`; 10 test modules import from it. `tests/test_handler.py:23-35` defines
  `_auth_file` / `_post`; 6 modules import from it. The same six-line `_server` body is
  copy-pasted in 10 files (`test_handler.py:39`, `test_claude_ingress.py:34`,
  `test_protocol_contracts.py:19`, `test_router_response.py:10`, `test_v2_compaction.py:105`,
  `test_latency_metrics.py:67`, `test_setup.py:320`, `test_runtime.py:133`,
  `test_mixed_router.py:203`, `test_lifecycle.py:25`), and `_post` is re-declared five times.
  38 test modules import fixtures from another test module.
- `tests/test_tool_adapter.py:18-26` and `tests/test_v2_compaction.py:33-41` are drifted copies of
  `_isolated_home` (one returns the temp dir, the other `None` — `test_tool_adapter.py:279` depends
  on the return value). The temp-home idiom (`mkdtemp` + `addCleanup(rmtree)` + `ROUTER_HOME`
  patch) appears ~40 times.
- `tests/test_install.py` is exactly 500 lines — the tests HARD cap — and `:24-137` is pure fixture
  code (`install_mod`, `_ok_run`, `_patch_attrs`, `_craft_bundle`, `_tarball`, `_run_install`);
  20 modules import from it (`test_install_config.py`, `test_install_lifecycle.py`,
  `test_client_activation.py`, `test_systemd.py`, `test_feed_serial.py`, `test_windows_acl.py`,
  `test_interpreter_resolution.py`, …), some through a third layer. Because the checker requires
  an exact baseline match, the fixture API lives in a file that cannot change size.
- `tests/fakes.py` (upstream/launchd) and `tests/_platform.py` (skip guards) cover other concerns;
  no module owns the HTTP/auth/home harness.

## Scope

**In scope**: new `tests/harness.py`, new `tests/install_fixtures.py`, the test modules that import
or duplicate those helpers, `config/source-limits-baseline.json`.
**Out of scope**: any assertion change, any runtime/source change, merging `fakes.py` or
`_platform.py`, splitting files only for line count, test discovery configuration.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Focused | `python3.14 -B -m unittest tests.test_handler tests.test_mixed_router tests.test_setup tests.test_install tests.test_install_lifecycle tests.test_install_config` | pass after each migration step |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | exit 0; baseline updated for shrunken files |

## Steps

1. **Add `tests/harness.py`** containing: `auth_file`, `test_state`, `start_server`,
   `start_auth_server`, `post`, `get`, `stub_credentials`, `isolated_home(test) -> tmp` (the
   superset contract: returns the temp dir), `tmp_home(test) -> Path`. Copy semantics verbatim from
   the existing definitions (`tests/test_mixed_router.py:143-169`, `tests/test_handler.py:23-35`,
   `tests/test_tool_adapter.py:18-26`). Do not change behaviour; one module, one contract.
2. **Migrate importers in small batches** (one commit per batch), keeping aliases in
   `test_mixed_router.py`/`test_handler.py` until the last importer moves, then delete the local
   copies. Update `test_tool_adapter.py`/`test_v2_compaction.py` to the single `isolated_home`.
   Include `test_handler.py`'s new 092 tests in the first batch so they use the harness.
3. **Extract `tests/install_fixtures.py`** from `tests/test_install.py:24-137` (plus the
   `static_fetch` re-export at `:19`) and update its ~20 importers. `test_install.py` keeps only
   its test classes. Remove the `tests/test_install.py` baseline entry once its count drops below
   the soft limit; update the baseline via the checker.
4. **Optional, only if step 3 leaves `test_install_lifecycle.py` awkward**: split its
   `SafeUpdateTests` class into its own module. Do not split any other file for size alone.

**Verify**: after each batch, the focused list and the full suite pass; `rg -l "from tests\.test_(mixed_router|handler) import" tests/` empties batch by batch; final
`wc -l tests/test_install.py` below the 500 hard cap (expect ~385) with no fixture definitions
left.

## Done criteria

- [ ] `tests/harness.py` is the only definition of the HTTP/auth/home helpers; no copies remain.
- [ ] `tests/test_install.py` contains tests only; its baseline entry reflects the
      post-extraction count (expect ~385, below the 500 hard cap).
- [ ] Full suite, compile and limit gates pass; no assertion changed.
- [ ] Only `tests/` and the baseline changed.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- A test's semantics depend on a helper's local quirk (e.g. `_post` variants that differ subtly):
  stop for that helper, keep both contracts explicitly named in the harness, and note the
  difference rather than silently unifying.
- A migration batch cannot stay green: revert that batch only, keep earlier batches, and report.

## Maintenance notes

- New server/auth/home fixtures go in `tests/harness.py`; do not add new peer imports.
- `fakes.py` stays the upstream/launchd fake owner; `_platform.py` stays skip guards.
- Reviewers: diff migrated helpers against the originals; any behavioural difference is a defect.
