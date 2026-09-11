# Plan 125: Consolidate runtime shared primitives (path sets, image blocks, catalogue predicate, capability maps, SSE framing)

> Planning only. Implement only under a later implementation instruction.
> Drift check: `git diff --stat b642de9..HEAD -- ai_router/protocols/__init__.py ai_router/providers.py ai_router/claude.py ai_router/capabilities.py ai_router/context_budget.py ai_router/compaction.py ai_router/catalogue.py ai_router/tool_adapter.py ai_router/sse.py ai_router/model_refresh.py`
> Read changed code and preserve current behavior before edits.

## Status and first proof

- Priority P2; effort M; risk LOW-MED; confidence HIGH; category tech-debt; depends on
  090/091/093/096 (they edit the same runtime files) and 101 (dead code).
- Planned at `b642de9`, 2026-09-11.
- Implemented 2026-09-12 after the drift check; items 1 and 3-6 landed, item 2 was already
  satisfied by `image_items.py` (reconciled below).
- First proof: each shared rule exists once, with a test that couples its consumers.

## Why this matters

Five rules are currently duplicated in the runtime; each pair has already drifted or is one edit
away from doing so:

1. **Protocol path sets.** `ai_router/providers.py` `NATIVE_SERVICE_PATHS` and
   `ai_router/protocols/__init__.py` (the same four paths in `TABLE`) were independent copies;
   `ai_router/claude.py` `CLAUDE_POST_PATHS` and the `protocols/__init__.py` Messages row repeated
   the two Messages paths. `owned_paths()` (used by `router.py`) and provider ownership could
   disagree, producing a 404 or a wrong 400 instead of the intended local answer.
   *Reconciled 2026-09-12: landed here — the table now imports both owners' sets.*
2. **Image-block detection.** *Reconciled 2026-09-12: already satisfied* by
   `ai_router/image_items.py` (`is_image` / `count_images` / `has_images` / `strip_images` /
   `note_images`), the plan-141-era single owner; `context_budget.py` was deleted and compaction's
   copies are gone. `router._payload_has_image` survives as a thin wrapper over
   `capabilities.has_images` because `tests/test_handler.py` imports it. No work left here.
3. **Catalogue visibility**: `merge` and `check` re-wrote the same `models_for` + external-provider
   + allowlist expression and built `allowset` twice; `check` could certify a catalogue `merge`
   would not produce. *Reconciled 2026-09-12: landed here as `_visible_rows`.*
4. **Capability maps**: `capabilities.py` derives four maps at import; `model_refresh.apply`
   rebuilt the same four by hand (plan 098 explicitly excludes `model_refresh.py`). Once 099 wires
   the hourly refresh, the hand-mirror becomes live. *Reconciled 2026-09-12: landed here as
   `capabilities.rebuild`.*
5. **Capability constants**: `catalogue.py` `ROW_TEMPLATE` hardcoded `multi_agent_version`,
   `node_repl_disabled`, `comp_hash` while `capabilities.py` defines them; subscription stubs used
   the unoverridden literals. *Reconciled 2026-09-12: landed here — the template imports them.*
6. **SSE framing**: `sse.py` owns framing and `replace_data`, but `tool_adapter.py` built
   `b'data: ' + json.dumps(event) + b'\n\n'` itself; the two rules could drift.
   *Reconciled 2026-09-12: landed here as `sse.frame`.*

## Scope

**In scope**: the files listed in the drift check, plus focused tests.
**Out of scope**: any behavior change to routing (path sets stay identical), the router failure-path
change in plan 093, the refresh wiring (099), the dead-code deletions (101), `transport.py` contents,
new SSE features.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Focused | `python3.14 -B -m unittest tests.test_catalogue tests.test_providers tests.test_tool_adapter tests.test_claude_ingress tests.test_context_budget tests.test_compaction tests.test_domain_boundaries` | pass before and after |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | exit 0; baseline updated for changed counts |

## Steps

1. **Path sets (commit 1).** Have `protocols/__init__.py` build its native-path row from
   `providers.NATIVE_SERVICE_PATHS` and its Messages row from `claude.CLAUDE_POST_PATHS` (verify no
   import cycle first; if importing providers into protocols cycles, move the two sets into a tiny
   leaf both import and STOP-report the location choice). Add a test asserting `owned_paths()`
   equals the union of the provider/claude path sets.
   *Landed 2026-09-12: no cycle — `protocols/messages.py` already imports `claude` and
   `protocols/responses.py` already imports `providers`, so `protocols/__init__.py` imports both
   directly. The coupling test asserts each owner's path selects that owner's policy and that
   `owned_paths()` is exactly the two sets plus `/responses` and `/responses/compact`
   (`tests/test_protocol_contracts.py`).*
2. **Image primitives (commit 2).** Add `is_image_block(block)` and `image_blocks(item)` to
   `capabilities.py` (leaf, stdlib only) and route `has_images`, `_without_images`,
   `strip_images`, `note_images`, and router's payload check through them. Plan 093 already moves
   router to parsed payloads — take that shape. Preserve exact semantics (which block types count)
   and the fail-closed behaviour.
   *Reconciled 2026-09-12: already done by `image_items.py` (single owner) — no change here. See
   item 2 above.*
3. **Catalogue predicate (commit 3).** Extract `_visible_rows(client, allowed)` returning
   `(visible, hidden)`; call it once in `merge` and once in `check`; build `allowset` once per call.
   *Landed 2026-09-12 as `_visible_rows(client, allowed, include_twins=False)` in `catalogue.py`,
   called by both.*
4. **Capability maps (commit 4).** Add `capabilities.rebuild(models)` containing the four
   derivations; call it at import and from `model_refresh.apply` (replacing the hand-mirror).
   Coordinate with 099: the function must be safe to call at any time. Either have
   `catalogue.py`'s template fields reference the constants once import direction allows, or add an
   equality test in `tests/test_catalogue.py` if a direct import is disallowed — one of the two is required by the Done criteria.
   *Landed 2026-09-12: `rebuild(models)` runs at import and from `model_refresh.apply` after the
   registry swap (`registry.MODELS` must be the new snapshot first, because `external_slugs()`
   reads it). `catalogue.py` now imports the three constants, so no equality test is needed;
   `tests/test_model_refresh.py` keeps pinning apply → derived maps.*
5. **SSE framing (commit 5).** Either route rebuilt frames through an `sse` helper (keep the
   one-`data:`-line envelope semantics that plan 091 establishes) or document the fresh-frame rule
   in `sse.py`'s contract; choose one and cover it in the adapter test. Do not change wire bytes
   beyond what 091 already sets.
   *Landed 2026-09-12: added `sse.frame(data)`; `tool_adapter.stream_events` yields it for both the
   changed and unchanged branches. Wire bytes are unchanged.*

**Verify**: focused tests after each step; full suite and compile at the end; `rg -n 'NATIVE_SERVICE_PATHS' ai_router/protocols/` shows a reference, not a copy.

## Done criteria

- [x] One definition each for: native/Messages path sets (`protocols/__init__.py` imports the
      owners), image-block detection (`image_items.py`, pre-existing), catalogue visibility
      (`_visible_rows`), capability maps (`capabilities.rebuild`), capability constants
      (`catalogue.py` imports them), SSE frame construction (`sse.frame`).
- [x] Coupling tests exist where two modules must agree: `tests/test_protocol_contracts.py` pins
      the path union and per-path policy; `tests/test_model_refresh.py` pins apply → derived maps;
      the constants are single-source imports, the alternative the plan allowed.
- [x] Full suite, compile and limit gates pass; only in-scope files changed (`ai_router/`,
      `tests/`, the baseline and the two plan files).
- [x] `plans/README.md` status row updated.

## STOP conditions

- An import cycle appears (protocols↔providers, capabilities↔compaction, catalogue↔capabilities):
  stop, choose the leaf placement, and report before proceeding.
- Any focused test shows a behavioral difference (path classification, image counting, catalogue
  output, retry/visibility) — stop; these are contracts, not refactors to hand-wave.

## Maintenance notes

- New image block types are added in one place (`image_items.py`); `capabilities` re-exports them.
- `model_refresh.apply` no longer owns derivations; rebuild is the single entry point.
- Reviewers: confirm no import-direction violation against `docs/architecture.md`.
