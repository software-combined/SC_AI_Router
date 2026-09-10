# Plan 100: One source for retired subscription slugs

> Planning only. Implement only under a later implementation instruction.
> Drift check: `git diff --stat a985197..HEAD -- ai_router/retired_slugs.py ai_router/catalogue.py packaging/service.py tests/test_catalogue.py tests/test_install_state.py tests/test_packaging.py`
> Read changed code and preserve current behavior before edits.

## Status and first proof

- Priority P3; effort S; risk LOW; confidence HIGH; category tech-debt; depends on plans/094-router-atomic-write-consolidation.md (same `ensure_state` function; land after it and preserve the atomic writer).
- Planned at `a985197`, 2026-09-10.
- First proof: a coupling test shows the catalogue's retired-subscription set and the installer's
  prune set are the same object; configuring a new retirement requires one edit.

## Why this matters

Retired-subscription knowledge is duplicated and unlinked:

- `ai_router/catalogue.py:73` — `RETIRED_SUBSCRIPTION_SLUGS = frozenset({'gpt-reserve'})`, consumed
  at `:211-215` to drop the row from the merged catalogue.
- `packaging/service.py:617-620` — `ensure_state` prunes the literal `'gpt-reserve'` from
  `openai_models`.

A future retirement needs both edits, and a missed one lets a retired slug linger in state or
reappear in the picker. Packaging can import 3.9-safe `ai_router` leaves (precedent:
`service.py:39-41` imports `ai_router.feed_verify`), but **cannot** import `catalogue` or `registry`:
`registry.py:29` uses `int | None` annotations without `from __future__`, so it is not 3.9-parseable.

## Current state (verified at a985197)

- `ai_router/catalogue.py:70-73`:
  ```python
  RETIRED_SUBSCRIPTION_SLUGS = frozenset({'gpt-reserve'})
  ```
  and at `:211-215` it pops those slugs from merged entries and skips them when seeding from roster.
- `packaging/service.py:610-621` `ensure_state`; the prune is the `elif 'gpt-reserve' in state['openai_models']`
  branch.
- `packaging/service.py:39-41` shows the load path:
  ```python
  import sys
  sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
  from ai_router import feed_verify  # noqa: E402  (3.9-safe, no router import)
  ```
- Same-file sibling duplication worth one line in the PR description but **out of scope**:
  `service.DEFAULT_OPENAI_MODELS` (`:58-60`) duplicates the subscription roster.

## Scope

**In scope**: new `ai_router/retired_slugs.py`, `ai_router/catalogue.py`,
`packaging/service.py` (import + prune loop only), `tests/test_catalogue.py`,
`tests/test_install_state.py`, `tests/test_packaging.py` (surface list), `plans/README.md` (status row only).
**Out of scope**: `DEFAULT_OPENAI_MODELS` deduplication, `RETIRED_SLUGS` (the OpenRouter-side set at
`catalogue.py:65-69`), retirement policy changes, state migrations beyond the existing prune.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Focused | `python3.14 -B -m unittest tests.test_catalogue tests.test_install_state tests.test_packaging` | pass before and after |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | exit 0 |

## Steps

### Step 1: new leaf (commit 1)

Create `ai_router/retired_slugs.py`:
```python
"""Subscription slugs withdrawn from the picker; shared by catalogue and installer."""
SUBSCRIPTION = frozenset({'gpt-reserve'})
```
Python 3.9-safe (plain literal, no annotations). It ships automatically with the `ai_router/*.py`
bundle glob, but confirm `packaging/release.py` and the bundle test enumerate or glob it; add it to
the explicit `python3.9` installer-surface parse list test if that list is explicit.

### Step 2: consume it in both layers (commit 1)

- `ai_router/catalogue.py`: replace the literal with
  `from .retired_slugs import SUBSCRIPTION as RETIRED_SUBSCRIPTION_SLUGS` (keep the local name so
  existing importers/tests are unaffected).
- `packaging/service.py`: after the existing `from ai_router import feed_verify` line,
  `from ai_router.retired_slugs import SUBSCRIPTION as RETIRED_SUBSCRIPTION_SLUGS` (same `# noqa`
  pattern) and change the prune to iterate the set:
  ```python
  elif any(slug in state['openai_models'] for slug in RETIRED_SUBSCRIPTION_SLUGS):
      state['openai_models'] = [s for s in state['openai_models']
                                if s not in RETIRED_SUBSCRIPTION_SLUGS]
  ```
  Keep the write only when something changed. Plan 094 lands first and routes both `ensure_state`
  writes through `packaging/atomic_write.replace_text`; preserve that helper here and never
  reintroduce a bare `path.write_text`.

### Step 3: coupling test (commit 1)

Add a test (e.g. in `tests/test_install_state.py`) asserting `service`'s imported set and
`catalogue.RETIRED_SUBSCRIPTION_SLUGS` are equal, so a future one-sided edit fails. Keep the
existing per-side tests (`tests/test_catalogue.py:102`, `tests/test_install_state.py:55-57`).

**Verify**: focused modules pass; temporarily removing the service import makes the coupling test fail.

## Done criteria

- [ ] No literal `'gpt-reserve'` outside `ai_router/retired_slugs.py` (`rg -n "gpt-reserve" ai_router packaging tools tests` → only the leaf plus test fixtures that intentionally pin behavior).
- [ ] Catalogue and installer read the shared set; coupling test exists.
- [ ] Surface parse test includes the new module if it enumerates files.
- [ ] Full suite, compile and limit gates pass; only in-scope files changed.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- `packaging/service.py` cannot import the new leaf under the 3.9 surface gate: stop and report.
- A test pins the literal in a way that makes sharing impossible: stop before changing the test's
  intent.

## Maintenance notes

- Retiring a subscription slug is now: edit the frozenset, update the shared display/reasoning
  tables if any, run the suites.
- `DEFAULT_OPENAI_MODELS` remains a second duplication; fold it into a shared leaf only when the
  roster next changes.
- Reviewers: confirm the prune still writes state only when the list actually changes.
