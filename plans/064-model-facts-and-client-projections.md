# Plan 064: Give model normalization and client projections one owner each

> Planning only. Execute after implementation is authorised. Preserve existing
> model data and client behavior during extraction; label behavior corrections
> separately. Update `plans/README.md` with the actual evidence gate.
>
> Drift check: `git diff --stat 6840312..HEAD -- codex_router/registry.py codex_router/model_metadata.py codex_router/capabilities.py codex_router/catalogue.py codex_router/apply_catalogue.py codex_router/live_refresh.py codex_router/models.py codex_router/claude.py codex_router/clients tests/test_registry.py tests/test_catalogue.py tests/test_install_catalogue.py tests/test_apply_catalogue.py tests/test_live_refresh.py tests/test_models_cmd.py tests/test_model_roster.py tests/test_claude_ingress.py tests/test_model_projections.py tests/test_domain_boundaries.py tests/test_release.py docs/architecture.md docs/adding-a-model.md docs/compatibility.md config/source-limits-baseline.json CHANGELOG.md packaging/VERSION plans/README.md`
> Compare any moved protocol files from 062 with the current code before changing
> imports. Do not restore the old layout over another integrated refactor.

## Status and outcome

- Priority P2; effort M; risk MED; category architecture/consistency.
- Planned at `6840312`, 2026-09-09. Depends on 061. Coordinate with 062 over
  `claude.py` and its moved Messages implementation; one writer owns that file.
- First proof: one model snapshot yields identical Codex capability fields
  through catalogue merge and the legacy apply command. Naming normalization
  runs without importing the model CLI; Claude listing policy has one explicit
  owner and cannot change routing or billing.

## Current state and reproduced inconsistency

`live_refresh.py:35-36` imports `qualify_name` from the CLI module at call time,
while `models.py:15` imports `CODEX_MODALITIES` from `live_refresh`. The comment
acknowledges the cycle. Both import/refresh paths filter upstream capabilities
using the Codex-specific vocabulary (`live_refresh.py:16-17,45-48` and
`models.py:57-61`). Naming and metadata normalization are domain logic and
should not depend on command orchestration.

`catalogue.py:130-135` takes final modalities from a Model:

```python
**catalogue_patch(model.slug),
'input_modalities': list(model.modalities),
```

`apply_catalogue.py:20-24` independently reduces live modalities:

```python
if 'input_modalities' in arch:
    mods = arch['input_modalities']
    patch['input_modalities'] = ['text', 'image'] if 'image' in mods else ['text']
```

The parent ran both pure functions with the same synthetic live modalities for
the existing Muse row: merge returned `[text, image, audio]`; apply returned
`[text, image]`. This proves competing projection paths, not working audio.
Actual audio/client acceptance remains governed by the existing probe plans.

`registry.visible_for` (`:106-124`) contains Codex/Claude picker policy.
`claude.models_listing` (`:52-59`) lists every OpenRouter row, with tests that
explicitly require that behavior (`test_claude_ingress.py:140-155`). The future
mirror filter mentioned in `catalogue.py:149-150` is not yet the runtime policy.

Good patterns: frozen `registry.Model`, exact-field validation, data-driven
quirks, preview tier, and separate derived/pinned refresh fields. Preserve all.

## Scope and boundaries

Only paths in the drift check, this plan/index. New runtime files:
`codex_router/model_metadata.py`, `codex_router/clients/__init__.py`,
`codex_router/clients/codex.py`, `codex_router/clients/claude.py` as needed for
actual extracted callers. Keep public command modules as thin wrappers.

Out: editing the actual roster in `models.json`, enabling new capabilities,
changing tiers, paid probes, hot reload, registry schema migration, Kiro model
support, runtime credentials and installer/client activation. Keep model data
and the base-instructions resource at their current root paths for now.

## Steps

### 1. Capture projection and normalization contracts

Create `tests/test_model_projections.py` with a synthetic row and live metadata.
Exercise public merge/apply paths and assert equal capability output for the
same model snapshot, including audio and excluded reasoning levels. Assert
subscription rows and unrelated fields are preserved. The modality equality
case must fail before the fix. Separately pin current Claude listing and direct
slug/alias routing, including its intentionally listed Anthropic aliases.

**Verify:** `python3.14 -m unittest tests.test_model_projections` exposes the
existing equality defect; existing registry/catalogue/Claude tests still pass.
No upstream fetch, model file write or candidate probe is needed.

### 2. Extract pure metadata normalization

Move vendor/name qualification and shared metadata field normalization into
`model_metadata.py`. Import it from `models.py` and `live_refresh.py`. It must
not import either command module, catalogue, provider, installer or client.
Keep separate new-row and existing-row rules where intent differs: refresh
must preserve exclusions, default reasoning, schema quirks, tier and probe-gated
fields; new rows start Preview. Do not unify them by resetting pinned values.

Keep the currently supported canonical modality set while giving client
vocabulary projection its own function. Do not store arbitrary new upstream
modalities or promise support merely because the API advertises them.

**Verify:** `python3.14 -m unittest tests.test_models_cmd tests.test_live_refresh tests.test_registry tests.test_domain_boundaries`
passes. Import-cycle check confirms normalization never imports `models` or
`live_refresh`; naming, alias and pinned-field assertions stay unchanged.

### 3. Use one Codex capability projection

Move Codex-specific template/capability presentation into `clients/codex.py`,
leaving `catalogue.py`'s existing CLI and merge/check entrypoints compatible.
The pure projection consumes a validated Model snapshot. It must not look up
part of that same model again through stale import-time maps when supplied a
new snapshot. Reuse it from the legacy `apply_catalogue.apply` path rather than
maintaining an audio-dropping second implementation.

For live input, normalize and validate the candidate snapshot before rendering;
retain pinned exclusions and capability gates. Merge and apply with the same
snapshot must agree, while intentionally different live data may differ.
Preserve guarded writes and existing subscription metadata. Document the
modality consistency correction as a separate behavior change from extraction.

**Verify:** `python3.14 -m unittest tests.test_model_projections tests.test_catalogue tests.test_catalogue_upgrade tests.test_apply_catalogue tests.test_capabilities`
passes. Reintroducing the old two-modality expression makes the regression fail.

### 4. Extract Claude listing policy without changing it implicitly

Move Claude discovery IDs, alias resolution and listing projection into
`clients/claude.py`; the Messages protocol calls those functions. Give the
current include-all behavior an explicit name and retain it in this extraction.
Move picker visibility policy out of the model loader into the client domain.
Update its actual importers: `catalogue.py`, `tests/test_registry.py`,
`tests/test_catalogue.py` and `tests/test_install_catalogue.py`. Do not leave a
registry wrapper that imports the client domain and reverses the new dependency
rule. Keep command-facing compatibility exports in `catalogue.py`/`claude.py`;
their import direction is correct. If an external supported caller of the
registry visibility helpers is discovered, stop and define its migration first.

> **Deferred 2026-09-10 at `d97482d`:** the `clients/claude.py` move did not
> land. Picker visibility already lives in the client domain
> (`clients/__init__.py:visible_for/models_for`, consumed by `catalogue.py`),
> and the include-all Claude discovery list stays in `claude.py:models_listing`
> with explicit tests pinning it (`test_claude_ingress.py:140-181`). Moving
> that function now would churn `claude.py` shared with the 057/066 streams
> for zero behavior change, and the mirror filter itself belongs to 051/053.
> Reopen only with the 051/053 listing change, not as a behavior-preserving
> move.

Document the intentional distinction between current Claude discovery and the
planned mirror filter. That filter belongs to the Claude activation/acceptance
slice (051/053), which must update the actual listing tests and read back the
client picker deliberately. Do not silently apply `models_for('claude')` here
and describe a changed list as a behavior-preserving move. Hidden rows remain
routable by canonical slug; presentation never determines upstream ownership.

**Verify:** `python3.14 -m unittest tests.test_claude_ingress tests.test_registry tests.test_model_roster tests.test_model_projections tests.test_release`
passes with existing listing and route expectations intact.

### 5. Record compatibility by client and finish source gates

In `docs/compatibility.md`, label new evidence by client/version, OS, protocol,
model, capability and evidence type. Preserve historical rows as historical;
do not manufacture missing evidence. Keep `Model.tier`'s current meaning rather
than turning it into a claim that every client/platform is verified.

**Verify:** full tests, compilation, source limits, offline model check and diff
check all exit 0:

```sh
python3.14 -m unittest discover -s tests -t .
python3.14 -m compileall -q codex_router tools tests packaging
python3.14 tools/check_source_limits.py
python3.14 -m codex_router.models check --offline
git diff --check
```

## Done criteria

- [x] Pure metadata normalization has no dependency on command/client modules.
- [x] Merge and apply agree for the same Model snapshot and preserve native rows.
- [x] Refresh never promotes capabilities/tiers or resets pinned quirks.
- [x] Client projections own listing shapes; current Claude list remains unchanged.
- [x] Picker hiding cannot alter canonical upstream routing or credential choice.
- [x] Extracted bundle imports/resources and required checks pass.
- [x] Review, `develop` integration and worktree disposition are recorded.

## STOP conditions and maintenance

Stop for a required registry schema/roster change, paid validation, unclear
ownership with 062, implicit visibility change, or the same failed check twice.
When adding a client, implement its projection from the canonical model rather
than copying the Codex template. Probe acceptance remains per actual client.

Git: one owned `codex/` worktree from `develop`, current review skill and model
table before each conventional commit, scoped stages under the line budget,
target `develop`, then verify and clean up. No live refresh or deploy here.
