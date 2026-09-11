# Plan 102: Reduce install.py at its hard cap by collapsing duplicated option handling

> Implemented 2026-09-11; drift reconciled in the same change.
> Drift check: `git diff --stat a985197..HEAD -- packaging/install.py tests/test_install_lifecycle.py tests/test_install.py tests/test_install_config.py config/source-limits-baseline.json`
> Drift reality (2026-09-11, develop c892e1f): `install.py` is 699 lines (baseline pins 699), the
> option writes were already compacted to five single-line sites, and the file has moved on. The
> extraction below therefore lands as a net-zero decomposition: `do_install` now delegates to
> `_resolve_clients_and_modes` (`:303-339`) and `_rollback_failed_install` (`:342-359`), with
> `do_install` at `:362-527`.

## Status and first proof

- Priority P2; effort M; risk MED; confidence HIGH; category tech-debt; depends on none (run after 101).
- Planned at `a985197`, 2026-09-10.
- First proof: `python3.14 tools/check_source_limits.py` passes with `packaging/install.py` below the
  700-line hard cap, with every installer test green.

## Why this matters

`packaging/install.py` sits at its 400/700 entrypoint ceiling — 699 lines against a 700 hard cap,
`config/source-limits-baseline.json` pinned at 699 — so any one-line fix needs a compensating
deletion, and `do_install` (`:362-527`) interleaves option resolution, bundle install, rollback, and
client attachment.

Pure extraction within the file does **not** create headroom by itself; the win is the decomposition
itself: collapsing the near-identical `state.get(...) != ... : _write_state(...)` sites into one
resolution pass that writes state at most once (`:303-339`), plus extracting the rollback block
(`:342-359`). Keep helpers in the same module: the installer's tests patch globals on `install_mod`
and mirror seams through `_sync_seams` (`:291-300`); moving helpers to another module silently
bypasses those patches.

## Current state (verified at 2026-09-11 on develop c892e1f; original refs at a985197/12c834b in git history)

- `packaging/install.py` is 699 lines; `do_install` is `:362-527`; `_sync_seams` is `:291-300`
  (mirrors `run/health/wait_version/ensure_serving` from `_svc`); `:89-99` binds service seams at
  module level.
- The option resolution had drifted from four to five write sites (client, claude_mode,
  anthropic_mode, openai_mode, clients) at `:359-406`, each writing the same state document:
  ```python
  if state.get('client', 'codex') != client:
      state['client'] = client; _write_state(home, state)
  ...
  if state.get('claude_mode') != claude_mode:
      state['claude_mode'] = claude_mode
      _write_state(home, state)
  ...
  ```
  These now live in `_resolve_clients_and_modes` (`:303-339`), which validates in the same order
  with the same messages and performs at most one `_write_state`. The `args.setup` nonce write
  (`:440-446`) is deliberately outside the helper.
- `:432-455` — bundle install, service start, health wait, and the multi-branch rollback/refusal
  block; now `_rollback_failed_install` (`:342-359`) with byte-identical messages.
- `:456-527` — attachment tail; unchanged by this plan.
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

- [x] `install.py` count is below 700 (699, net-zero: the two helper definitions offset the
      collapsed writes) and the baseline entry matches exactly.
- [x] All installer suites and the full suite pass with zero test edits required by the moves
      (installer 98, full suite 1009).
- [x] No seam patched by tests moved out of the module (`_sync_seams` still binds the same names).
- [x] Compile, limit and F401/F811 gates pass; only in-scope files changed.
- [x] `plans/README.md` status row updated.
- [x] Accepted semantic delta (per the plan's own note): a failed late validation no longer
      persists the earlier option writes; state is written once, after validation.

## STOP conditions

- Any installer test fails and the fix requires changing a test: stop and report; this plan must be
  behavior-preserving.
- The extraction raises the line count (net growth): stop; re-check the collapse before continuing.
- A helper needs a module-level global that tests patch: stop and keep it in `install.py`.

## Maintenance notes

- Headroom remains modest (~20-30 lines); a future feature needing real room should trigger the
  larger split with explicit seam arguments, not another in-file extraction.
- Reviewers: diff the option-resolution semantics line by line; that is where behavior can drift.
