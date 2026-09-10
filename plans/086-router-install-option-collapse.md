# Plan 086: Reduce install.py at its hard cap by collapsing duplicated option handling

> Planning only. Implement only under a later implementation instruction.
> Drift check: `git diff --stat a985197..HEAD -- packaging/install.py tests/test_install_lifecycle.py tests/test_install.py tests/test_install_config.py config/source-limits-baseline.json`
> Read changed code and preserve current behavior before edits.

## Status and first proof

- Priority P2; effort M; risk MED; confidence HIGH; category tech-debt; depends on none (run after 085).
- Planned at `a985197`, 2026-09-10.
- First proof: `python3.14 tools/check_source_limits.py` passes with `packaging/install.py` below its
  previous 697-line count, with every installer test green.

## Why this matters

`packaging/install.py` is 697 lines — three under the 700 hard cap — and
`config/source-limits-baseline.json` pins it at 697. Any one-line fix requires a compensating deletion, and the 217-line `do_install`
(`:313-529`) interleaves option resolution, bundle install, rollback, and client attachment.

Pure extraction within the file does **not** create headroom by itself; the win comes from
collapsing four near-identical `state.get(...) != ... : _write_state(...)` blocks (`:369-407`) into
one resolution pass that writes state once, plus extracting the rollback block. Keep helpers in the
same module: the installer's tests patch globals on `install_mod` and mirror seams through
`_sync_seams` (`:301-310`); moving helpers to another module silently bypasses those patches.

## Current state (verified at a985197; line refs refreshed at 12c834b)

- `packaging/install.py:313-529` `do_install`; `:301-310` `_sync_seams` mirrors
  `run/health/wait_version/ensure_serving` from `_svc`; `:89-99` binds service seams at module level.
- `:369-407` — four separate writes to the same state document as each option resolves:
  ```python
  if state.get('client', 'codex') != client:
      state['client'] = client
      _write_state(home, state)
  ...
  if state.get('claude_mode') != claude_mode:
      state['claude_mode'] = claude_mode
      _write_state(home, state)
  ...
  ```
- `:419-466` — bundle install, service start, health wait, and the multi-branch rollback/refusal block.
- `:467-529` — attachment tail; keep in place for this plan.
- Characterizing tests: `tests/test_install_lifecycle.py`, `tests/test_install.py`,
  `tests/test_interpreter_resolution.py`, `tests/test_platform_dispatch_order.py`,
  `tests/test_install_config.py`, `tests/test_update_channel.py`, plus `test_windows_acl`.

## Scope

**In scope**: `packaging/install.py` (internal extraction and the option-resolution collapse only),
`config/source-limits-baseline.json`, `plans/README.md` (status row only).
**Out of scope**: behavior changes of any kind, `packaging/service.py`, other packaging modules,
test rewrites beyond what a pure move requires, the `_sync_seams` mechanism, CLI flags.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Installer suites | `python3.14 -B -m unittest tests.test_install_lifecycle tests.test_install tests.test_install_config tests.test_interpreter_resolution tests.test_platform_dispatch_order tests.test_update_channel tests.test_windows_acl` | pass before and after |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | exit 0; baseline updated to the new exact count |

## Steps

### Step 1: collapse option resolution (commit 1)

Extract `_resolve_clients_and_modes(args, home, state)` (name it in the file's style) covering
`:369-407`. It must:

- perform every validation/refusal in the same order with the same messages;
- mutate `state` exactly as today, then call `_write_state(home, state)` **once** if anything changed;
- return `(client, clients, claude_mode, mode)` for the caller's later use.

The four current calls write intermediate states; the only observable difference is fewer disk
writes of the same document. If any test observes intermediate file states, stop and report.

### Step 2: extract the failure/rollback block (commit 2)

Move `:443-466` into `_rollback_failed_install(home, state, backend, latest, previous, catalog_path, before_catalog)`.
Keep every message and branch byte-identical (catalog restore, pointer swap, TERM restart,
`rollback_serving_ok` distinction, `raise SystemExit(1)`). Pass values explicitly; do not capture
loop locals implicitly.

### Step 3: baseline and evidence (same commits)

Run `tools/check_source_limits.py`; update the `packaging/install.py` baseline entry to the new
count (it will remain above the 400 soft limit, so the entry must match exactly). Never exceed the 700 hard cap.

**Verify**: all installer suites pass unchanged; `python3.14 tools/check_source_limits.py` exits 0.

## Done criteria

- [ ] `install.py` count is lower than 697 and the baseline entry matches exactly.
- [ ] All installer suites and the full suite pass with zero test edits required by the moves.
- [ ] No seam patched by tests moved out of the module (`_sync_seams` still binds the same names).
- [ ] Compile and limit gates pass; only in-scope files changed.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- Any installer test fails and the fix requires changing a test: stop and report; this plan must be
  behavior-preserving.
- The extraction raises the line count (net growth): stop; re-check the collapse before continuing.
- A helper needs a module-level global that tests patch: stop and keep it in `install.py`.

## Maintenance notes

- Headroom remains modest (~20-30 lines); a future feature needing real room should trigger the
  larger split with explicit seam arguments, not another in-file extraction.
- Reviewers: diff the option-resolution semantics line by line; that is where behavior can drift.
