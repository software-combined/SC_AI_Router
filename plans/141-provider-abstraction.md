# Plan 141: Provider abstraction - one definition per upstream

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If any
> "STOP conditions" item occurs, stop and report - do not improvise. When done,
> update this plan's status row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 95d0368..HEAD -- ai_router packaging tools tests docs plans AGENTS.md CHANGELOG.md config/source-limits-baseline.json`
> If any in-scope file changed since this plan was written, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch, STOP.

## Status

- **Priority**: P1 (owner request: "plan a full abstraction layer"); Effort: L; Risk: MED;
  Confidence: HIGH; category: direction / tech-debt.
- **Depends on**: nothing external. Plan 127's two splits (failure policy to
  `ai_router/upstream.py`, setup page markup to its own module) landed as part of this work
  because the provider table needed the same headroom; plan 125's shared primitives remain TODO
  and rebase on top.
- **Serialise with**: 126, 128, 134 (they edit `router.py`, `providers.py`, `setup.py`, tools).
  One writer per file. Rebase any in-flight branch onto this commit before touching those files.
- **Planned at**: commit `78da059`, 2026-09-11; rebased onto `95d0368` and re-verified
  after the twin-picker, native-popup and standalone-outputs waves landed.
- First proof: a second provider defined only as one `ProviderDef` entry plus registry rows routes a
  Codex Responses turn to its host with its key, lists in the picker as `Vendor: Model · Acme`, and
  reports `Acme billing` - with no built-in provider host literal left outside
  `ai_router/provider_defs.py`.

## Why this matters

Every upstream fact about OpenRouter is hard-wired: the host constant, the key env var and file
name, the catalogue URL, the picker suffix, the key-validation URL, and the failure dialect. The
adapter seam is real (`owns`/`prepare`/`adapt` classes plus `Prepared` and the protocol table), but a
provider swap still needs edits in a dozen files. The owner's question - "would it be easy, do we
have enough abstraction to just change the API key?" - is answered no today. This plan makes the
answer yes for the key/endpoint surface, and one reviewed table entry for a new provider.

## Current state (verified at 78da059)

- `ai_router/capabilities.py:33` `OPENROUTER_HOST = 'openrouter.ai'`, imported by `providers.py:6`
  and `claude.py:17`; both adapters, plus `OpenRouterProvider.summarize` (`providers.py:331`),
  build their upstream target from it.
- `ai_router/credentials.py:6-7` `ENV_VAR = 'OPENROUTER_API_KEY'`, `KEY_FILE = 'openrouter.key'`;
  `openrouter_key()` (`:25`) is the only lookup; `packaging/install.py:186-203` and
  `packaging/diagnostics.py:143-171` mirror the same names by hand.
- `ai_router/registry.py:57` validates `provider` against the literal tuple
  `('openrouter', 'openai')`; `openrouter_slugs()` (`:123`) feeds `capabilities.OPENROUTER_MODELS`,
  `apply_catalogue.py`, `model_refresh.py` and `__main__.py`.
- `ai_router/models.py:18` and `ai_router/live_refresh.py:16` both pin
  `https://openrouter.ai/api/v1/models`; `models.py:60-61` stamps `provider: 'openrouter'` and a
  `· OpenRouter` label; `model_metadata.py:65` re-appends the same suffix on refresh.
- `ai_router/setup.py:26` pins `KEY_URL = 'https://openrouter.ai/api/v1/auth/key'`; `check_key`,
  `store_key` and `open_key_window` are OpenRouter-shaped; `setup.serve` renders "Connect OpenRouter"
  copy.
- Provider selection compares strings: `providers.py:362` `PROVIDERS` tuple, `providers.py:192-199`
  `entry.provider != 'openrouter'`, `providers.py:367` `provider.name != 'openrouter'`,
  `claude.py:33,95-97`, and `router.py:200,312,327-331` plus `_stored_key_dead` (`:277-291`) and
  `transport.py` `RESPONSES_STREAM_PROVIDERS` (`:114`).
- `router.py` is 398 lines against a 400 hard cap (`config/source-limits-baseline.json`), so the
  dead-key probe must move out of `router.py`, not grow inside it.
- `packaging/` runs on Python 3.9 and cannot import `ai_router` as a package; it spec-loads 3.9-safe
  leaves such as `ai_router/winacl.py` (see `packaging/diagnostics.py:40-44`).
- No config surface exists for any of this: `ROUTER_*` env vars are home/debug/live/update scoping
  only, and state keys are `port`, `token`, `openai_models`, `openai_mode`, `anthropic_mode`,
  `allowed_models`, `opencode_auth`, `openai_helper_fallback`, setup/nonce fields.

## Interfaces

New leaf module `ai_router/provider_defs.py`, stdlib-only, no I/O, no `ai_router` imports, and
parseable as Python 3.9 so the installer surface can spec-load it:

```python
class KeySpec:            # where one provider's key resolves from
    env, file, state_key, example

class ProviderDef:
    id, label, kind,      # kind: 'external' | 'subscription'
    host,
    responses_path,       # upstream path prefix prepended to the client path;
    messages_path,        #   None means this provider does not serve that protocol
    key,                  # KeySpec for external providers, None for subscriptions
    catalogue_url,        # live model list, None when rows are hand-authored
    catalogue_shape,      # 'openrouter' | 'manual'
    key_info_url,         # key validation endpoint, None when it has none
    dialect               # 'openrouter' | 'openai' | 'anthropic' failure envelope

def get(provider_id) -> ProviderDef | None
def is_external(provider_id) -> bool
def external_ids() -> tuple
def external_defs() -> tuple
def supports(provider_id, protocol) -> bool      # 'responses' | 'messages'
def label_for(provider_id) -> str
RESPONSES_IDS, MESSAGES_IDS                      # ids serving each protocol
```

Built-ins: `openrouter` (external: host `openrouter.ai`, responses prefix `/api/v1`, messages prefix
`/api`, catalogue `https://openrouter.ai/api/v1/models`, shape `openrouter`, key info
`https://openrouter.ai/api/v1/auth/key`, dialect `openrouter`, key env `OPENROUTER_API_KEY`, file
`openrouter.key`, state fallback `opencode_auth`), `openai` (subscription: `chatgpt.com`, responses
prefix `/backend-api/codex`, dialect `openai`), `anthropic` (subscription: `api.anthropic.com`,
messages prefix ``, dialect `anthropic`).

Renames (mechanical, all call sites updated): `capabilities.OPENROUTER_MODELS` -> `EXTERNAL_MODELS`;
`registry.openrouter_slugs()` -> `external_slugs()`; `catalogue.OPENROUTER_TEMPLATE` ->
`ROW_TEMPLATE`; `catalogue.openrouter_entry()` -> `external_entry()`; `providers.OpenRouterProvider`
-> `ExternalResponsesProvider(defn)`; `claude.ClaudeOpenRouterProvider` ->
`ExternalMessagesProvider(defn)`; `Credentials.openrouter_key()` -> `Credentials.key_for(provider_id)`.
`transport.Prepared.provider` keeps one string: the upstream id (`openrouter`, `openai`,
`anthropic`, `local-services`); request metrics gain `protocol` (`responses` | `messages`).

## Scope

**In scope**: `ai_router/provider_defs.py` (new), `registry.py`, `capabilities.py`, `providers.py`,
`claude.py`, `router.py`, `transport.py`, `credentials.py`, `setup.py`, `runtime.py`, `candidate.py`,
`catalogue.py`, `clients/__init__.py`, `clients/codex.py`, `model_metadata.py`, `apply_catalogue.py`,
`model_refresh.py`, `models.py`, `live_refresh.py`, `__main__.py`, `subscription_fallback.py`,
`packaging/install.py`, `packaging/diagnostics.py`, `tools/probe_*.py` call sites, tests, `docs/`,
`AGENTS.md` section 8 wording, `CHANGELOG.md`, `packaging/VERSION`,
`config/source-limits-baseline.json`.

**Out of scope**: `tools/provision_key.py` (OpenRouter management tooling), the desktop-picker
plugin, any protocol translation, any live or paid probe, and behaviour changes to routing,
compaction, allowlist policy, or the setup window's security rules.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Focused | `python3.14 -B -m unittest tests.test_providers tests.test_claude_ingress tests.test_handler tests.test_router_response tests.test_catalogue tests.test_registry` | pass before and after |
| Keys | `python3.14 -B -m unittest tests.test_credentials tests.test_setup tests.test_safe_diagnostics tests.test_runtime tests.test_status` | pass before and after |
| Data | `python3.14 -B -m unittest tests.test_models_cmd tests.test_model_refresh tests.test_domain_boundaries` | pass before and after |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | exit 0; baseline synced for changed counts |

## Steps

1. **Definitions and vocabulary.** Add `provider_defs.py`; point `registry.load` at `BY_ID`, rename
   `openrouter_slugs()` -> `external_slugs()`; move capability gates, `apply_catalogue`,
   `model_refresh`, `__main__` and `clients.visible_for` at the new names. Add the new module to
   `tests/test_domain_boundaries.py` (it may import no `ai_router` module) and add the source scan
   that no built-in provider host literal appears outside `provider_defs.py`, with a synthetic
   violation so the check cannot pass vacuously.
2. **Adapters and routing.** Parameterize `ExternalResponsesProvider` and `ExternalMessagesProvider`
   with a `ProviderDef` (host, path prefix, key, dialect); keep `SubscriptionProvider` /
   `ClaudeSubscriptionProvider` as the `openai`/`anthropic` defs; adapters own `validate_response`;
   the compaction summarizer uses the routed def; `providers.select` and `claude.select` fail with a
   clear 400 when the row's provider does not serve the client's protocol; the router compares `kind`
   and dialect instead of names and records `protocol` in metrics; `transport.emit_terminal_failure`
   keys on `metrics['protocol']`.
3. **Keys per provider.** `Credentials.key_for(provider_id)` from the `KeySpec` (env, then owner-only
   file, then the optional state-file fallback), and `Credentials.key_rejected(provider_id)` holding
   the dead-key probe moved out of `router.py` (which is at the 400-line cap);
   `setup.check_key(provider_id, key)` validates against `key_info_url` when present and stores
   unvalidated keys otherwise; `store_key`/`open_key_window` take the provider id and the pending
   window records it; `runtime.load_state` requires at least one external key to resolve only when
   the registry has external rows and names every provider that did not; `candidate.py` resolves the
   candidate row's provider; `packaging/install.py` and `packaging/diagnostics.py` spec-load the leaf
   and prompt/report per provider (diagnostics keeps `key_present`/`key_usable` for the default
   provider and adds a `providers` map).
4. **Picker labels.** `ROW_TEMPLATE`, `external_entry`, `catalog_name`,
   `model_metadata.refresh_display_name` and `clients.visible_for` render `· <Label>` and
   `<Label> billing.` from the row's provider definition; `subscription_fallback` resolves the twin
   through the same table.
5. **Onboarding.** `models add`, `live_refresh` and `models check` resolve each row's provider and use
   its `catalogue_url`; `models add --provider` (default `openrouter`) refuses a `manual`-shape
   provider with a clear message; refresh rewrites only rows whose provider serves that catalogue.
6. **Proof and release.** New `tests/test_provider_defs.py` and `tests/test_provider_swap.py` (a
   registered `acme` fixture provider routes, labels, gates, and fails closed per provider with no
   network); docs updates in `docs/architecture.md`, `docs/operations.md`, `docs/claude-code.md`,
   `docs/adding-a-model.md`, `README.md`, `AGENTS.md`; `CHANGELOG.md` entry and a `packaging/VERSION`
   bump.

## Done criteria

- [x] No built-in provider host, key env var, key file name, catalogue URL or key-info URL literal
      exists outside `ai_router/provider_defs.py` (boundary test enforces it).
- [x] A second provider needs one `ProviderDef` entry plus registry rows: no conditional on a
      provider id anywhere in the request path.
- [x] `Credentials.key_for('openrouter')` resolves exactly as `openrouter_key()` did; a missing key
      for one provider fails that provider's requests closed and leaves another provider serving.
- [x] Full suite, compile and source-limit checks pass; `router.py` stays at or below 400 lines.
- [x] `plans/README.md` status row updated.

## STOP conditions

- `router.py` would exceed 400 lines, or `packaging/install.py` would exceed 700, with an in-scope
  change: stop and report before editing rather than raising a cap.
- Any test asserts the removed `openrouter_key()`/`openrouter_entry()`/`OpenRouterProvider` names in a
  way that is not a straight rename: stop and report the conflict.
- The credential precedence or the setup window's nonce/origin rules would have to change to make the
  abstraction fit: stop and report; those are security contracts, not refactors.

## Known limitation (recorded 2026-09-11)

With more than one external provider registered, a pending setup window
re-points its provider state but does not refresh an already-visible native
dialog or browser page, so the visible prompt can still name the previous
provider. No wrong-file write is possible through the loopback page (it
renders the provider the state names), and only one external provider ships
today; the next plan that adds a second definition owns re-opening the
window and the native dialog copy in `key_dialog.py`.
