# Plan 150: Carried-history portability for routed models

> Planning only. Implement only under a later implementation instruction.
> Drift check: `git diff --stat 7ebdb85..HEAD -- ai_router/registry.py ai_router/models.json ai_router/compaction.py ai_router/tool_adapter.py ai_router/upstream.py ai_router/relay.py tests/test_history_portability.py tests/test_upstream_failures.py tests/test_registry.py tests/test_safe_diagnostics.py`
> Reconcile the line references below against the live files before editing.

## Status and first proof

- Owner-authorized 0.6.37 follow-up: subscription history normalization
  now makes DeepSeek -> Astra switches independent of compaction, and
  Responses HTTP 400 validation errors stay final rather than becoming
  retryable 409s. Cache entries preserve the client status. See
  `docs/compatibility.md`, "Subscription history replay and validation
  retries", for synthetic and live acceptance. The external registry
  portability scope below is unchanged.

- Priority P1; effort S; risk MED (refusal path and wire history); category
  router/reliability; depends on none.
- Planned at `3515c6a`, 2026-09-12; rebased onto `7ebdb85` when develop took 145-148.
- Shipped 2026-09-12: the `history_mode` registry field, the portable
  discovery-pair replay (slice 2a), the carried-reasoning drop (slice 2b),
  the coded 409 with the switch-back or new-thread recovery, the
  content-free rejection fingerprint, and the repeat-refusal cache
  (8 entries, 60 s TTL).
- Trigger: a turn is portable when its registry row carries
  `history_mode: portable`, or when the input carries the client's
  `<model_switch>` developer marker. Only `meta/muse-spark-1.3-contributor`
  is `portable`; every other row stays `native` (no evidence for them yet).
- First proof: a portable turn replaces the `codex_client_tool_search`
  call/output pair with one visible note while the released schemas stay
  declared, drops carried reasoning items, and a repeated identical
  refusal answers 409 without dispatch.
- Bisect evidence 2026-09-12 (owner-authorised paid probes): a captured
  refused turn (14 items, 21 tools, 31,953 bytes) reproduces Meta's
  `HTTP 400` with 409 at the client, and the identical turn with its two
  carried reasoning items removed is accepted (`200`); the DeepSeek
  control answers `200` on both. A 21-hour rebuilt tail without reasoning
  was accepted earlier, so the reasoning item is the trigger, not the
  discovery pair alone.
- Remainder: slices 2c/2d stay unproven (no evidence yet), and the Muse
  Contributor row probe repeats on any client upgrade.

## Why this matters

A thread that ran ~21 h on `deepseek/deepseek-v4.1-flash` at `max` was
swapped to `meta/muse-spark-1.3-contributor` at `xhigh` (thread
`01a08bbb-e859-7650-b4c3-c3fcc06d559f`, failing turns `01a09270-0368`
and `01a09274-faa2` in the N8N repository).
The carried turn was refused by OpenRouter's Meta upstream with a bare
HTTP 400 twelve times (two bursts of six client dispatches, ~500 KB
history, 63 declared tools): `upstream_rejected` events 2026-09-11
21:46-21:52 UTC in `~/.codex/mixed-model-router/logs/router.jsonl`
(all on `meta/muse-spark-1.3-contributor`). Swapping back to DeepSeek on
the same history works. The client marks a swap with a `<model_switch>`
developer message in the input. The refusal previously surfaced as a
fixed-wording 409 with no provider code and no recovery action.

## Prior art (evidence, not instructions)

`github.com/duolahypercho/codex-router` v0.5.1, commit `7bd2f52`
(MIT; read 2026-09-12, not copied) solves the same class with
per-provider compatibility modules, and corroborates the portable
shape: `flattenToolSearchHistory` (`src/namespace-relay.mjs`) adds the
discovered definitions to the provider tool list and, when a model
switch leaves no live search relay, drops the unusable native control
pair; `ensureToolResultsForCalls` and `coalesceAssistantMessages`
(`src/api-forwarder.mjs`) repair tool-row adjacency and consecutive
assistant messages so strict providers do not reject the whole turn;
`src/chat-wire-search-history.mjs` replays a structured search item a
wire cannot carry as an ordinary readable marker; repeated refusals are
logged once per provider per process rather than dropped; and
`src/error-translation.mjs` keeps a 300-character innermost upstream
detail. Two of those repairs are candidates this plan has not tested:
strict call/output adjacency, and duplicate assistant-message
coalescing. They join the owner-gated bisect below rather than shipping
on shape alone.

## Steps

### Step 1: registry field `history_mode`

- `ai_router/registry.py`: `history_mode: str = 'native'` dataclass field
  (`'native' | 'portable'`), in `FIELDS`, validated like `schema_mode`.
- `ai_router/models.json`: `"history_mode": "native"` on every row,
  `"portable"` on exactly `meta/muse-spark-1.3-contributor`.
- `ai_router/models.py` `derive_row`: new rows start `native` so
  `models add` output keeps validating.

**Verify**: `test_history_mode_defaults_native_and_validates` and
`test_muse_contributor_is_the_only_portable_row` in
`tests/test_registry.py`.

### Step 2: portable history replay (slices 2a and 2b)

- `portable_history` (`ai_router/compaction.py`, the history
  shaping module) collapses the `codex_client_tool_search` call and its
  matching output (by `call_id`) into one visible user note; either half
  without its mate is dropped. In the same pass it drops carried
  `reasoning` items: one with a readable summary replays as that summary
  note, one without is dropped, because an upstream that did not produce
  the item refuses the turn (measured above).
  `prepare_tools` (`ai_router/tool_adapter.py`) calls it after the rewrite
  loop with the row's `history_mode`. Released schemas stay declared in
  `payload['tools']`; plain declared pairs and every other item are
  untouched. (The helper lives in compaction, not tool_adapter: the
  addition would have pushed tool_adapter past its 400-line hard cap; the
  call site there is two lines.)

**Verify**: the portable tests in `tests/test_history_portability.py`,
especially `test_native_declared_pair_survives_with_discovery_intact`,
`test_portable_turn_drops_carried_reasoning` and
`test_wire_body_carries_no_reasoning_for_a_portable_row` (both fail
against the 0.6.34.51 release, which keeps the item).

### Step 3: coded 409, fingerprint, and repeat-refusal cache

- `ai_router/upstream.py`: `_provider_reason` returns
  `(provider, reason, tool, code)` with the code from fixed fields only;
  `describe_failure` keeps its shape, inserts `, code <code>` when present,
  and names the recovery (switch back, or start a new thread).
- `rejection_fingerprint` returns counts only; `recall_refusal` /
  `remember_refusal` bound repeats (8 entries, 60 s TTL, `clear_refusals`
  for tests).
- `ai_router/relay.py`: consult the cache before dispatch on the
  OpenRouter Responses path only (never the Messages path, never a
  5xx, so a transient upstream failure still dispatches); log the
  fingerprint fields on `upstream_rejected`. The provider code must
  already be code-shaped, so upstream prose can never reach the
  message or the log, and the switch-back recovery is added only for a
  routed turn.

**Verify**: `RefusalCacheTests` and the failure-description tests in
`tests/test_upstream_failures.py`, plus the fingerprint tests in
`tests/test_safe_diagnostics.py`.

## Done criteria

- [x] `history_mode` validates; only the Muse Contributor row is portable.
- [x] Portable turns replay the discovery pair as a note; native output unchanged.
- [x] 409 names the provider code (when present) and the recovery.
- [x] Rejection logs and the cached path carry counts only.
- [x] Owner capture-and-bisect of a failing carried turn (reasoning item).
- [ ] Slices 2c/2d: no evidence yet; reopen only on a new refusal shape.
- [ ] Muse Contributor row probe on a real thread.

## STOP conditions

- A portable replay drops or rewrites anything but the discovery pair and
  carried reasoning items: STOP, narrow the pass, re-prove the native
  regression test.
- A refusal message or log line carries upstream prose, schema text, or
  argument text: STOP, the content-free rule owns this path.
- A second model shows the same carried-history refusal: STOP, do not widen
  `portable` without the bisect evidence for that row.

## Maintenance notes

- Re-check the `portable` row set after every Model onboarding (`models add`)
  and live refresh; new rows default to `native` until evidence says otherwise.
- Re-run the Muse Contributor probe after any Codex desktop upgrade
  (AGENTS.md section 7) before widening portable handling.
