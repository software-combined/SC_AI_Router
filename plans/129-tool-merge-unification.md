# Plan 129: Unify the tool-definition merge rule shared by tool_adapter and discovered

> Planning only. Implement only under a later implementation instruction.
> Drift check: `git diff --stat b642de9..HEAD -- ai_router/tool_adapter.py ai_router/discovered.py ai_router/tool_merge.py tests/test_tool_adapter.py tests/test_discovered.py`
> Read changed code and preserve current behavior before edits.

## Status and first proof

- Priority P3; effort M; risk MED; confidence HIGH; category tech-debt; depends on 091, 096, 097
  (they edit these files).
- Planned at `b642de9`, 2026-09-11.
- First proof: one merge rule for declared, released and recalled tool definitions, with the
  existing adapter/discovery tests proving identical output.

## Why this matters

`ai_router/tool_adapter.py:76-92` merges declared and released tools ("complete a catalogue stub;
never clobber"), and `ai_router/discovered.py:117-180` re-implements the same `(namespace, name)`
keying, stub completion and wrapper merging for recalled schemas — its docstring at `:137-138`
admits it is "mirroring prepare_tools". The two paths meet on every request: live declarations in
`tool_adapter`, recalled schemas from cache in `discovered`. A rule change in one (for example the
`max_tools` interaction at `tool_adapter.py:139-154`) leaves the other behind, so live-vs-after-
restart tool sets can diverge.

Constraints: `tool_adapter` imports `discovered.recall`; `discovered` must NOT import `tool_adapter`
(no cycle — this was a deliberate rule in the completed plan 070). A new leaf module avoids both.

## Current state (verified at b642de9)

- `tool_adapter.py:67-92` `prepare_tools` merge; `:139-154` ceiling interaction.
- `discovered.py:117-180` `_dedup` with flat rows, namespace wrappers, first-wins, stub completion;
  `:183-201` `remember`; `:204-219` `recall`.
- Tests: `tests/test_tool_adapter.py` (384 lines), `tests/test_discovered.py`, plus provider
  preparation tests.

## Scope

**In scope**: new `ai_router/tool_merge.py`, `tool_adapter.py`, `discovered.py`, focused tests.
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
   imports) with `merge_tool_defs(*groups)` implementing exactly today's semantics: key by
   `(namespace, name)`; first full definition wins; a later full schema completes an earlier stub
   that lacks `parameters`; namespace wrappers merge by inner tools; output order is first
   occurrence. Cover it with a small unit test including the wrapper and stub cases.
2. **Adopt in `discovered._dedup` (commit 1).** Replace the bodies with calls to the leaf,
   preserving deepcopy isolation and the disk-round-trip behaviour. Keep `_dedup`'s public name
   (callers/tests may use it).
3. **Adopt in `prepare_tools` (commit 2).** Use the same leaf for the declared+released merge,
   keeping the `max_tools` ceiling step and the wire-name hashing in `tool_adapter`. If the merge
   currently interleaves with the ceiling, extract only the pure merge portion and keep the policy
   in place.

**Verify**: focused tests after each step; a differential test that feeds the same inputs through
both call sites and asserts identical prepared tool lists; full suite green.

## Done criteria

- [ ] One merge rule in `tool_merge.py`; no duplicated keying/stub/wrapper logic remains.
- [ ] Wire output identical before/after (differential test).
- [ ] Deepcopy isolation preserved (mutating returned data cannot change cache/declared state).
- [ ] Full suite, compile and limit gates pass; only in-scope files changed.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- The two sites turn out to have intentionally different rules (not drift): stop and report the
  difference; unify only the shared part.
- A cycle or import-direction problem appears: stop; the leaf must import nothing from ai_router.

## Maintenance notes

- New schema shapes: extend the leaf and its unit test; both call sites inherit.
- Reviewers: verify ordering and stub-completion semantics match the previous behaviour exactly.
