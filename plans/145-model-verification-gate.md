# Plan 145: Model verification gate - hidden until probed

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving on. If a STOP condition
> occurs, stop and report - do not improvise. When done, update this plan's status
> row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 3515c6a..HEAD -- ai_router/registry.py ai_router/clients/__init__.py ai_router/catalogue.py ai_router/models.py ai_router/live_refresh.py ai_router/candidate.py tools/probe_codex_runtime.py docs/adding-a-model.md docs/compatibility.md tests/`
> Reconcile the cited lines against the live code before editing; on a mismatch, STOP.

## Status and first proof

- Priority P1; effort M; risk MED; confidence HIGH; category direction/quality.
- Depends on 133 (one `AppServer` harness). 135 stage 2 consumes this plan's
  promotion state. No owner gate: everything here is offline except the billed
  probe legs, which stay owner-gated per run.
- Source: `plans/2026-09-12-external-router-review.md` (external router review).
- First proof: a row added for a new model is routable but absent from both client
  catalogues until a probe passes; `models discover` reports the same row without
  writing anything; the compatibility record names the legs that actually ran.

## Why this matters

Today `models add` writes `tier: preview` and the row is immediately visible in
both pickers: the Codex catalogue through `ai_router/clients/__init__.py`, and the
Claude listing through `ai_router/claude.py::models_listing()`, which never consults
`visible_for`. An unverified model reaches users before anything has exercised it. The external
review's rule - a discovered model stays unlisted until live checks pass - is the
right shape, and our own `--probe` exists but runs only one tool round trip.

## Scope

**In scope**: `ai_router/registry.py`, `ai_router/clients/__init__.py`,
`ai_router/claude.py` (the Claude picker listing is a separate projection and
must honour the flag too), `ai_router/catalogue.py`, `ai_router/models.py`,
`ai_router/live_refresh.py`,
`ai_router/candidate.py`, `tools/probe_codex_runtime.py`,
`docs/adding-a-model.md`, `docs/compatibility.md`, `tests/test_registry.py`,
`tests/test_models_cmd.py`, `tests/test_catalogue.py`,
`tests/test_claude_ingress.py`, `tests/test_candidate.py`.
**Out of scope**: routing policy (`providers.select` must ignore the new flag),
`docs/operations.md`, the Claude projection shape, and any automatically billed
run in CI or tests.

## Steps

1. **`listed` flag, grandfathering preserved (commit 1).** Add `listed: bool = True`
   to the registry row model and validate it as a bool. A **missing** key on any row
   already in `models.json` reads as True and is not an error: the loader reads rows
   with strict bracket indexing today (`registry.py`, the `row['tier']` checks and the
   exact-set check), so validating `row['listed']` would raise `KeyError` and adding
   the field to the exact set would refuse the row outright. The loader must accept
   the old shape (`set(row) - {'listed'} == set(FIELDS)`), and every check - including
   step 3's invariant - must read the **raw** row, presence-gated, never the defaulted
   value; otherwise a grandfathered `tier: preview` row without the key is refused and
   the router stops booting. Add a test that loads a preview row without the field.
   `models add` writes `listed: false` for a derived row.
2. **Exclusion in both projections (commit 1).** Codex: `clients.visible_for`
   returns False when `not model.listed`, so the picker key and catalogue derive from
   the visibility owner (Plan 064). Claude: `claude.models_listing()` builds the
   listing straight from `registry.MODELS` through `claude_alias` and never consults
   `visible_for`, so it must drop `not entry.listed` rows itself. Routing never
   consults the flag: `providers.select` and `claude.select` keep working from the
   registry and policy, so the row stays routable for its own probe. Tests assert
   routing still resolves an unlisted slug, `models_for(...)` omits it, and
   `GET /v1/models` does not list it. Write that listing test by patching an existing
   row to `listed=False` (the alias path resolves through the import-time `BY_SLUG`), so
   it fails before the fix instead of passing vacuously.
3. **One invariant (commit 2).** The registry validator refuses `listed: true` with
   `tier != 'verified'`, so a hand-edited `models.json` cannot mark a preview row
   listed; this plan's own promotion path writes both fields together. Grandfathering
   is unaffected because every existing row is already `tier: verified` or `preview`
   with the default flag.
4. **Promotion only on a passed probe (commit 2).** `models add --probe` sets
   `listed: true` and `tier: verified` only after the probe returns success; a
   failed or refused probe leaves the row unlisted and prints why. An explicit
   `--tier verified` without a probe run keeps the row unlisted and says so.
5. **`models discover` (commit 2).** New read-only subcommand over the live
   catalogue: `addable` (served upstream, not in `models.json`), `registered`,
   `unavailable` (in the registry, absent upstream) and `retired`. Never writes,
   never probes, needs no key for OpenRouter; `--provider ID` selects a provider
   and `--json` emits the same document. Reuse `live_refresh`'s derivation.
6. **Probe the capabilities the row claims (commit 3).** `candidate.py` passes the
   legs the row implies: the tool round trip always, `--image` when the row's
   modalities include image, and the compaction leg when the row declares a context
   window. A billed run requires the explicit `--probe` plus a confirmation flag;
   without it the command prints what would run and exits without a paid call.
7. **Evidence names the legs (commit 3).** `_record_compat` records model, tier,
   date and the exact legs that ran (`tool,stream,image,compact`), replacing the
   fixed "base round trip" text, so a reader can tell which claim was tested.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Focused | `python3.14 -B -m unittest tests.test_registry tests.test_models_cmd tests.test_catalogue tests.test_claude_ingress tests.test_candidate` | pass |
| Registry | `python3.14 -m ai_router.models check --offline` | exit 0 |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | exit 0; baseline if counts move |

## Done criteria

- [x] An unlisted row is absent from both client projections (Codex catalogue and
      `GET /v1/models`) and still routable.
- [x] A row without the `listed` key loads as listed; `listed: true` with a
      non-verified tier is refused.
- [x] Promotion happens only on a passed probe; a failed probe changes nothing.
- [x] `models discover` performs no write and no billed call.
- [x] The compatibility record names the legs that ran, with the date.
- [x] Full suite, compile and limit gates pass; `docs/adding-a-model.md` updated.
- [x] `plans/README.md` status row updated.

## Landed notes, 2026-09-12

- Loader accepts the old shape (`set(row) - {'listed'} == set(FIELDS)`);
  the `listed: true` + non-verified invariant reads the raw row with
  `row.get('listed', False)`, so a grandfathered preview row without the
  key loads as listed and never refuses (all 19 shipped rows load listed).
- `visible_for` returns False for unlisted rows (Codex catalogue derives
  from it); `claude.models_listing()` drops unlisted rows itself.
  `providers.select` and `claude.select` untouched; the listing test
  patches `moonshotai/kimi-k3` through `BY_SLUG` + `MODELS` and fails
  without the fix.
- `models add` writes `listed: false`; `--probe` promotes to listed +
  verified only on pass, derives the legs from the row it just wrote
  (`legs_for(slug, row)` - the import-time registry predates the new slug),
  records those legs in compatibility, and
  prints why on failure or refusal; `--tier verified` without a probe
  stays unlisted. `verify()` keeps its bool contract; legs derive after.
- `models discover` reuses `require_live_shape`/`fetch_live`, honours
  `--provider`/`--json`, never writes or probes. `candidate` gains
  `legs_for` (tool+stream always, image on modalities, compact on context
  window), `run_probe` passes `--image`/`--compact`, and the `candidate`
  CLI bills only with `--probe --confirm`.
- Gates: focused 121 OK; full suite 1173 OK; `models check --offline` 0
  problems; compile, source limits (baseline updated for the four grown
  files), policy scans, ruff F401/F811 all pass. No billed run in tests.

## STOP conditions

- Threading `listed` requires touching routing: stop; routing must not consult it.
- A probe leg cannot run without a paid call in CI: stop; the paid legs stay out of CI.
- A row cannot be routed while unlisted: stop and report rather than widening policy.

## Maintenance notes

- Existing preview rows are grandfathered and stay visible; the rule applies to
  rows added after this plan lands.
- Plan 135 stage 2 must treat `listed: false` rows as absent, so a preview-only
  addition never prompts for a client restart.
