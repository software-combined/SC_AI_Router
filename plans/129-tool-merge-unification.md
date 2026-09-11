# Plan 129: Unify the tool-definition merge rule shared by tool_adapter and discovered

> Planning only. Implement only under a later implementation instruction.
> Drift check: `git diff --stat b642de9..HEAD -- ai_router/tool_adapter.py ai_router/discovered.py ai_router/tool_merge.py tests/test_tool_adapter.py tests/test_discovered.py`
> Read changed code and preserve current behavior before edits.

## Status and first proof

- Priority P3; effort M; risk MED; confidence HIGH; category tech-debt; depends on 091, 096, 097
  (they edit these files).
- Planned at `b642de9`, 2026-09-11.
- Implemented 2026-09-12; the shared rule moved to `ai_router/tool_merge.py` and both call
  sites consume it. One deliberate policy difference was kept (see below): `prepare_tools`
  never clobbers a declared row (it borrows only the missing schema), while the recalled-cache
  merge lets the first full definition replace a bare stub. The plan's STOP bullet allows
  unifying only the shared part.
- First proof: one merge rule for declared, released and recalled tool definitions, with the
  existing adapter/discovery tests proving identical output.

## Why this matters

`ai_router/tool_adapter.py` merged declared and released tools ("complete a catalogue stub; never
clobber"), and `ai_router/discovered.py` re-implemented the same `(namespace, name)` keying, stub
completion and wrapper merging for recalled schemas — its docstring admitted it was "mirroring
prepare_tools". The two paths meet on every request: live declarations in `tool_adapter`, recalled
schemas from cache in `discovered`. A rule change in one left the other behind, so live-vs-after-
restart tool sets could diverge. *Reconciled 2026-09-12: keying, the stub-completion predicate and
the wrapper/flat merge now live in `tool_merge.py`; `prepare_tools` keeps its declared-wins policy
and calls the shared primitives.*

Constraints: `tool_adapter` imports `discovered.recall`; `discovered` must NOT import `tool_adapter`
(no cycle — this was a deliberate rule in the completed plan 070). A new leaf module avoids both.

## Current state (verified at b642de9; reconciled 2026-09-12)

- `tool_adapter.py` `prepare_tools` merge; the ceiling interaction sits below it.
- `discovered.py` `_dedup` with flat rows, namespace wrappers, first-wins, stub completion;
  `remember`; `recall`. After the move `_dedup` is an alias for `tool_merge.merge_tool_defs`
  (`discovered.py:120`) and the module is 224 -> 164 lines.
- Tests: `tests/test_tool_adapter.py`, `tests/test_discovered.py`, plus the new
  `tests/test_tool_merge.py` and provider preparation tests.

## Scope

**In scope**: new `ai_router/tool_merge.py`, `tool_adapter.py`, `discovered.py`, focused tests,
plus the release inventory entries the packaging gate requires for a new runtime module
(`tests/test_packaging.py` `FILES` and the README runtime list; plan 123's contract).
**Out of scope**: cache format/retention, `prepare_tools`'s ceiling policy, namespace wire-name
hashing, any ordering change visible on the wire.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Focused | `python3.14 -B -m unittest tests.test_tool_adapter tests.test_discovered tests.test_providers` | pass before and after |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | exit 0; baseline updated if counts change |

## Steps

1. **Extract the rule (commit 1).** Create `ai_router/tool_merge.py` (stdlib only, no ai_router
   imports) with `merge_tool_defs(defs)` implementing exactly today's semantics: key by
   `(namespace, name)`; first full definition wins; a later full schema completes an earlier stub
   that lacks `parameters`; namespace wrappers merge by inner tools; output order is first
   occurrence. Cover it with a small unit test including the wrapper and stub cases.
   *Landed 2026-09-12: the leaf is `ai_router/tool_merge.py` (no imports) with `merge_tool_defs`,
   `key_of`, `missing_schema` and `complete_parameters`; `tests/test_tool_merge.py` covers flat
   rows, wrapper merging, the mixed wrapper/flat case, non-dict rows and the completion rule.*
2. **Adopt in `discovered._dedup` (commit 1).** Replace the bodies with calls to the leaf,
   preserving deepcopy isolation and the disk-round-trip behaviour. Keep `_dedup`'s public name
   (callers/tests may use it).
   *Landed 2026-09-12: `_dedup = merge_tool_defs` keeps the public name; `remember`/`recall` still
   deepcopy around it, and the disk round-trip tests are untouched.*
3. **Adopt in `prepare_tools` (commit 2).** Use the same leaf for the declared+released merge,
   keeping the `max_tools` ceiling step and the wire-name hashing in `tool_adapter`. If the merge
   currently interleaves with the ceiling, extract only the pure merge portion and keep the policy
   in place.
   *Landed 2026-09-12: `prepare_tools` now keys declared/released rows with `key_of` and completes
   a schema-less declared row through `complete_parameters`; the ceiling step and wire-name hashing
   are untouched. The declared-wins field policy stays local by design (the STOP bullet's
   "unify only the shared part").*
   The simplifier pass caught a keying edge here: an early `key_of` fallback to a flat row's own
   `namespace` field would have re-keyed released rows that `prepare_tools` had always keyed by
   the wrapper context only. `key_of(tool, namespace)` now takes the effective namespace from the
   caller with no fallback (flat rows in `merge_tool_defs` pass their own field), and
   `tests/test_tool_merge.py::test_prepare_tools_keeps_the_flat_key_for_a_namespaced_released_row`
   pins the pre-image result. A head-to-head differential of `prepare_tools` on the pre-image tree
   and the staged tree is identical across five payload shapes (mixed flat rows, stub completion,
   wrapper release, two wrappers, declared wrappers).

**Verify**: focused tests after each step; a differential test that feeds the same inputs through
both call sites and asserts identical prepared tool lists; full suite green.

## Done criteria

- [x] One merge rule in `tool_merge.py`; no duplicated keying/stub/wrapper logic remains
      (`discovered._dedup` is the alias; `prepare_tools` uses `key_of`/`complete_parameters`).
- [x] Wire output identical before/after: `tests/test_tool_adapter.py` and
      `tests/test_discovered.py` pass unchanged, and `tests/test_tool_merge.py` differentially
      pins the shared rule at both call sites.
- [x] Deepcopy isolation preserved (`remember`/`recall` deepcopy around the leaf; the adapter
      copies released rows before merging).
- [x] Full suite, compile and limit gates pass; only in-scope files changed.
- [x] `plans/README.md` status row updated.

Reconciliation 2026-09-12: the new module is a runtime import of `discovered.py`, so the
release inventory had to list it; `tests/test_packaging.py::test_file_list_covers_the_runtime_import_closure`
and `::test_readme_runtime_list_matches_files` fail without those two edits.

## STOP conditions

- The two sites turn out to have intentionally different rules (not drift): stop and report the
  difference; unify only the shared part.
- A cycle or import-direction problem appears: stop; the leaf must import nothing from ai_router.

## Maintenance notes

- New schema shapes: extend the leaf and its unit test; both call sites inherit.
- Reviewers: verify ordering and stub-completion semantics match the previous behaviour exactly.
