# Plan 125: Consolidate runtime shared primitives (path sets, image blocks, catalogue predicate, capability maps, SSE framing)

> Planning only. Implement only under a later implementation instruction.
> Drift check: `git diff --stat b642de9..HEAD -- ai_router/protocols/__init__.py ai_router/providers.py ai_router/claude.py ai_router/capabilities.py ai_router/context_budget.py ai_router/compaction.py ai_router/catalogue.py ai_router/tool_adapter.py ai_router/sse.py ai_router/model_refresh.py`
> Read changed code and preserve current behavior before edits.

## Status and first proof

- Priority P2; effort M; risk LOW-MED; confidence HIGH; category tech-debt; depends on
  090/091/093/096 (they edit the same runtime files) and 101 (dead code).
- Planned at `b642de9`, 2026-09-11.
- First proof: each shared rule exists once, with a test that couples its consumers.

## Why this matters

Five rules are currently duplicated in the runtime; each pair has already drifted or is one edit
away from doing so:

1. **Protocol path sets.** `ai_router/providers.py:18` `NATIVE_SERVICE_PATHS` and
   `ai_router/protocols/__init__.py:16-18` (the same four paths in `TABLE`) are independent copies;
   `ai_router/claude.py:26` `CLAUDE_POST_PATHS` and `protocols/__init__.py:20-21` repeat the two
   Messages paths. `owned_paths()` (used by `router.py:184`) and provider ownership can disagree,
   producing a 404 or a wrong 400 instead of the intended local answer.
2. **Image-block detection** appears five times with three shapes: `router.py:61-74`
   (`_payload_has_image`), `capabilities.py:80-90` (`has_images`), `context_budget.py:11-17`
   (`_without_images`), `compaction.py:117-129` (`strip_images`), `compaction.py:176-191`
   (`note_images`). A new image block type or payload shape must be taught to all five.
3. **Catalogue visibility**: `catalogue.py:185-196` (`merge`) and `:254-265` (`check`) re-write the
   same `models_for` + `visible_for` + allowlist expression and build `allowset` twice; `check`
   can certify a catalogue `merge` would not produce.
4. **Capability maps**: `capabilities.py:10-14` derives four maps at import; `model_refresh.py:104-112`
   rebuilds the same four by hand (plan 098 explicitly excludes `model_refresh.py`). Once 099 wires
   the hourly refresh, the hand-mirror becomes live.
5. **Capability constants**: `catalogue.py:34,40,42` hardcode `multi_agent_version`, `node_repl_disabled`,
   `comp_hash` while `capabilities.py:17,114-118` defines them; subscription stubs use the
   unoverridden literals.
6. **SSE framing**: `sse.py` owns framing and `replace_data` (`:18-27`), but
   `tool_adapter.py:347` builds `b'data: ' + json.dumps(event) + b'\n\n'` itself, dropping upstream
   `event:`/`id:` lines; the two rules can drift.

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
2. **Image primitives (commit 2).** Add `is_image_block(block)` and `image_blocks(item)` to
   `capabilities.py` (leaf, stdlib only) and route `has_images`, `_without_images`,
   `strip_images`, `note_images`, and router's payload check through them. Plan 093 already moves
   router to parsed payloads — take that shape. Preserve exact semantics (which block types count)
   and the fail-closed behaviour.
3. **Catalogue predicate (commit 3).** Extract `_visible_rows(client, allowed)` returning
   `(visible, hidden)`; call it once in `merge` and once in `check`; build `allowset` once per call.
4. **Capability maps (commit 4).** Add `capabilities.rebuild(models)` containing the four
   derivations; call it at import and from `model_refresh.apply` (replacing the hand-mirror).
   Coordinate with 099: the function must be safe to call at any time. Either have
   `catalogue.py`'s template fields reference the constants once import direction allows, or add an
   equality test in `tests/test_catalogue.py` if a direct import is disallowed — one of the two is required by the Done criteria.
5. **SSE framing (commit 5).** Either route rebuilt frames through an `sse` helper (keep the
   one-`data:`-line envelope semantics that plan 091 establishes) or document the fresh-frame rule
   in `sse.py`'s contract; choose one and cover it in the adapter test. Do not change wire bytes
   beyond what 091 already sets.

**Verify**: focused tests after each step; full suite and compile at the end; `rg -n 'NATIVE_SERVICE_PATHS' ai_router/protocols/` shows a reference, not a copy.

## Done criteria

- [ ] One definition each for: native/Messages path sets, image-block detection, catalogue
      visibility, capability maps, capability constants, SSE frame construction.
- [ ] Coupling tests exist where two modules must agree (paths, roster tables already in 123,
      constants).
- [ ] Full suite, compile and limit gates pass; only in-scope files changed.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- An import cycle appears (protocols↔providers, capabilities↔compaction, catalogue↔capabilities):
  stop, choose the leaf placement, and report before proceeding.
- Any focused test shows a behavioral difference (path classification, image counting, catalogue
  output, retry/visibility) — stop; these are contracts, not refactors to hand-wave.

## Maintenance notes

- New image block types are added in one place (`capabilities`).
- `model_refresh.apply` no longer owns derivations; rebuild is the single entry point.
- Reviewers: confirm no import-direction violation against `docs/architecture.md`.
