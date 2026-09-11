# Plan 098: Make model-refresh swaps visible to every consumer

> Planning only. Implement only under a later implementation instruction.
> Drift check: `git diff --stat a985197..HEAD -- ai_router/model_refresh.py ai_router/claude.py ai_router/providers.py tests/test_model_refresh.py tests/test_providers.py`
> Read changed code and preserve current behavior before edits.

## Status and first proof

- Priority P2; effort S; risk LOW; confidence HIGH; category correctness; depends on none (but must
  land before or with the Plan 099 Step 3 wiring that calls `model_refresh.start()`).
- Planned at `a985197`, 2026-09-10.
- First proof: after `model_refresh.apply(new_models)`, `claude.models_listing()` and
  `providers.summarize`'s effort selection both reflect the new registry.

## Why this matters

`model_refresh.apply()` (`ai_router/model_refresh.py:97-112`) swaps `registry.MODELS`/`BY_SLUG` and
rebuilds the `capabilities.*` maps. Two consumers bind tables **by value at import time** and stay
stale after a swap:

- `ai_router/claude.py:19` imports `MODELS`; `models_listing()` (`:66-78`, served at
  `ai_router/router.py:156`) keeps the old tuple, so `/v1/models` can advertise removed slugs and
  hide new ones while routing uses the new map.
- `ai_router/providers.py:6` imports `REASONING_LEVELS`; `summarize` reads it at `:326` for
  compaction effort, so compaction would pick levels from the previous catalogue.

`model_refresh.start()` has no caller yet (`model_refresh.py:3-5`), so the defect is latent until
Plan 099 Step 3 wires the refresh — hence the sequencing note. `registry.by_slug` and the
`capabilities` functions already read module globals dynamically and are **not** stale.

## Current state (verified at a985197)

- `ai_router/model_refresh.py:97-112` — `apply()` rebinds `registry.MODELS`, `registry.BY_SLUG`,
  `capabilities.OPENROUTER_MODELS`, `capabilities.IMAGE_INPUT_MODELS`,
  `capabilities.EXCLUDED_EFFORTS`, `capabilities.REASONING_LEVELS`.
- `ai_router/claude.py:19` — `from .registry import MODELS, by_slug`; `:70` uses `MODELS`.
- `ai_router/providers.py:6` — `from .capabilities import (CANONICAL_ORDER, OPENROUTER_HOST, REASONING_LEVELS, ...)`;
  `:326` uses `REASONING_LEVELS.get(model)`.
- `tests/test_model_refresh.py:45-71` shows the swap/restore fixture and asserts
  `capabilities.REASONING_LEVELS` after `apply`; extend it.

## Scope

**In scope**: `ai_router/claude.py`, `ai_router/providers.py`, `tests/test_model_refresh.py`,
`tests/test_providers.py` (one summarize test if needed), `plans/README.md` (status row only).
**Out of scope**: `model_refresh.py` itself (no `apply()`-driven rebuilds of peers — dynamic reads
are the fix), `catalogue.py`/`apply_catalogue.py` (CLI one-shots), the wiring of `start()` (Plan 099 Step 3),
`registry.load` behavior.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Focused | `python3.14 -m unittest tests.test_model_refresh tests.test_providers tests.test_claude_ingress` | pass before and after |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | exit 0; update baseline if pinned counts change |

## Steps

### Step 1: dynamic registry read in claude (commit 1)

Change the import to keep `by_slug` (already dynamic) and read the listing from the module:
use `from . import registry` and `models_listing` iterates `registry.MODELS`. Keep the function's
sorting and alias behavior byte-identical.

### Step 2: dynamic capability read in providers (commit 1)

Add `from . import capabilities` and change `summarize`'s lookup at `:326` to
`capabilities.REASONING_LEVELS.get(model)`. Remove the now-unused `REASONING_LEVELS` name from the
`from .capabilities import ...` list. Do not touch `CANONICAL_ORDER` (static).

### Step 3: tests (commit 1)

Extend `tests/test_model_refresh.py::test_valid_payload_swaps_atomically_and_rebuilds_derived` (or a
sibling) to assert, after `apply(models)`:

- `claude.models_listing()['data']` contains the new slug's listing id and not a removed one;
- the compaction effort selection uses the new levels: call `providers.OpenRouterProvider().summarize`
  with the `_summarize`-style fake connection from `tests/test_providers.py:240-249` and assert the
  posted `reasoning.effort` comes from the swapped levels (the fixture rows use `['low']`, so `low`).

The existing `setUp`/`addCleanup` restore is in place; add any newly needed restores (none expected).

**Verify**: focused tests pass; temporarily reverting the dynamic reads makes the new assertions fail.

## Done criteria

- [ ] `rg -n "from .registry import MODELS" ai_router/claude.py` → no matches (`capabilities.py:10` and `catalogue.py:13` keep their static imports by design and are out of scope).
- [ ] `rg -n "REASONING_LEVELS" ai_router/providers.py` → only the `capabilities.`-qualified use.
- [ ] After `apply()`, listing and summarize reflect the new registry in tests.
- [ ] Full suite, compile and limit gates pass; only in-scope files changed.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- A circular import appears (`capabilities` ↔ `providers`): stop and report; the fallback is to have
  `providers` read `registry`-derived levels through a function.
- Any other module still imports `MODELS`/`REASONING_LEVELS` by value in a request path: stop and
  enumerate it in the report before extending scope.

## Maintenance notes

- Rule going forward: request-path consumers read registry/capabilities through the module, never by
  value; `apply()` remains the single swap point.
- **Required before Plan 099 Step 3 wires `start()`**: `apply()` publishes its six module globals
  sequentially with no lock, so a request landing mid-swap can see new `registry.MODELS` with old
  `capabilities.*` (reviewers proved the window and the `check_effort` `KeyError` it enables). This
  plan deliberately left `model_refresh.py` out of scope; the wiring step must build all derived
  maps into locals and publish capabilities before `registry.MODELS`/`BY_SLUG`, or guard the
  publish with one lock.
- Plan 099 Step 3 (wiring `start()`) must land after or with this plan; note it in the 099 row when
  integrating. While wiring, correct the stale "Plan 046 step 4" phrase in
  `ai_router/model_refresh.py:3-5`, which still names the old number and the wrong step.
- Reviewers: check no behavior changed when the refresh is never run (default bundled registry).
