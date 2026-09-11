# Plan 127: Split failure policy out of providers.py and pages out of setup.py

> **Landed by Plan 141 (2026-09-11).** 141 needed the same headroom and split
> both modules the way this plan specifies: `ai_router/upstream.py` owns
> `is_context_error`, `upstream_retry_after`, `_provider_reason`,
> `validate_response` and `describe_failure` (router imports `upstream.*`),
> and `ai_router/setup_page.py` owns the page markup while `setup.py` keeps
> the key lifecycle and state. (Develop renamed the page module from this
> plan's working name `setup_pages.py` to `setup_page.py`.) Do not execute
> this plan again; read the landed modules if the split needs extending.

> Planning only. Implement only under a later implementation instruction.
> Drift check: `git diff --stat b642de9..HEAD -- ai_router/providers.py ai_router/upstream.py ai_router/setup.py ai_router/setup_pages.py ai_router/router.py tests/`
> Read changed code and preserve current behavior before edits.

## Status and first proof

- Priority P2; effort M; risk MED; confidence HIGH; category tech-debt; depends on 101 (dead
  aliases) and 090/096 (router shape); run before 128.
- Planned at `b642de9`, 2026-09-11.
- First proof: `providers.py` holds only adapters and dispatch; `setup.py` holds key lifecycle and
  state, not page markup; both modules drop well under their caps with unchanged behavior.

## Why this matters

- `ai_router/providers.py` (390/400) mixes wire shaping, failure taxonomy and dispatch:
  `is_context_error`, `upstream_retry_after`, `_provider_reason`, `describe_failure`,
  `validate_response` (`:21-142`) sit beside the three adapter classes (`:149-362`) and
  `select`/`compaction_call` (`:365-390`); `router.py:321,327,336,358,384` imports policy from the
  adapter module. `docs/architecture.md:57-60` already flags this as transitional, and the alias
  block at `:15-17` says it exists "until the protocol split completes" — after 101 removes the dead
  `relay_headers` import, the block's rationale is empty.
- `ai_router/setup.py` (379/400) mixes key lifecycle (`:65-108`), HTML page rendering
  (`:111-179`), state mutation (`:257-340`), and HTTP glue (`:343-379`). First-run security logic
  and presentation share a cap-sized module, so any UI touch costs a full security read.

## Current state (verified at b642de9)

- `providers.py:15-17` alias imports from `transport`; `:21-142` policy; `:149-362` adapters;
  `:365-390` dispatch. Router import sites listed above.
- `setup.py:111-179` `_STYLE`/`_page`/`_form`/`_done`; `:257-340` `open_key_window`/
  `_atomic_replace`/`_finish_setup`; `:343-379` `serve`/`_reject`.
- `ai_router/runtime.py:8` imports `setup.setup_pending` (keep working; a state leaf is plan 131).

## Scope

**In scope**: new `ai_router/upstream.py`, new `ai_router/setup_pages.py`, `providers.py`,
`setup.py`, `router.py` imports, focused tests.
**Out of scope**: behaviour changes, transport.py contents, setup's atomic writer (plan 131),
`runtime.py` decoupling (plan 131), route/path changes.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Focused | `python3.14 -B -m unittest tests.test_providers tests.test_handler tests.test_router_response tests.test_setup tests.test_safe_diagnostics tests.test_claude_ingress` | pass before and after |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | exit 0; baseline updated for both files |

## Steps

1. **`ai_router/upstream.py` (commit 1).** Move `is_context_error`, `upstream_retry_after`,
   `_provider_reason`, `describe_failure`, `validate_response` verbatim; update `router.py` imports
   to use `upstream.*`; remove the `transport` alias block and import `transport` qualified where
   needed. Keep `providers.select`/`compaction_call`/adapters in place. If any test patches a
   function via `providers.<name>`, update the patch target deliberately (list them in the commit
   message) — do not leave silent re-exports behind.
2. **`ai_router/setup_pages.py` (commit 2).** Move `_STYLE`, `_page`, `_form`, `_done`
   (`:111-179`) into the new module; `setup.serve` calls them. Keep `check_key`, `store_key`,
   `open_key_window`, `_atomic_replace`, `_finish_setup`, `setup_pending` in `setup.py`. Leave
   `runtime.py`'s import untouched (plan 131 handles the decoupling).
3. **Baseline**: update `config/source-limits-baseline.json` entries for both files to their new
   exact counts (they may drop below the soft limit — remove the entries if the checker allows).

**Verify**: focused tests; `wc -l ai_router/providers.py ai_router/setup.py` noticeably lower;
`rg -n 'from \.providers import (is_context_error|describe_failure|validate_response)' ai_router/`
→ no matches; full suite green.

## Done criteria

- [ ] `upstream.py` owns the failure policy; router imports it directly; alias block gone.
- [ ] `setup.py` no longer contains HTML/CSS; `setup_pages.py` has no state/security logic.
- [ ] No behavior change; focused and full suites green.
- [ ] Baseline updated; only in-scope files changed.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- An import cycle appears (`upstream` ↔ providers/router): stop and choose a placement that keeps
  the documented direction, reporting the choice.
- A test patches a moved function by its old module path and cannot be updated cleanly: stop for
  that function, report the patch sites, and leave a re-export only with an explicit removal note.

## Maintenance notes

- New failure taxonomies go in `upstream.py`; new wire shaping stays in `providers.py`.
- Page markup changes are safe to change without re-reading key storage.
- Reviewers: diff moved functions line by line; any behavioural edit is a defect.
