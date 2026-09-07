# Plan 038: One declarative model registry drives membership, capabilities, quirks and catalogue entries

> **Amended 2026-09-07**: the registry is a data file, `codex_router/models.json`, not Python rows. `registry.py` is the loader and validator (the `Model` dataclass stays as the schema) and exposes `MODELS`, `by_slug`, `openrouter_slugs`. Step 1's `Model(...)` rows become JSON objects with the same field names; every other step stands. Plan 046 builds the `models add` command and hourly remote reload on top of this file, so keep the loader pure (text in, validated registry out).

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 749a6b8d..HEAD -- <ROUTER_ROOT>`
> On any in-scope change, compare the "Current state" excerpts against the
> live code first; on a mismatch, STOP.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW to MED (data refactor; the catalogue regeneration diff in Step 5 is the proof)
- **Depends on**: Plan 036 (safety net). Plan 037 consumes this plan's `by_slug`.
- **Category**: tech-debt / dx
- **Planned at**: commit `749a6b8d`, 2026-09-07

## Path convention

`ROUTER_ROOT` is `domains/ai-platform/codex-model-router` pre-Plan 034 or the repository root post-034. Post-034 names are used; pre-034 drop the `codex_router/` and `tests/` prefixes.

## Why this matters

Adding one OpenRouter model today means editing the slug set and the reasoning table in `capabilities.py`, hand-copying a 21 KB entry into the 553 KB catalogue file (no generator exists; `apply_catalogue.py` only patches entries that already exist), editing provider quirks that are keyed on slug strings inside `tool_adapter.py`, changing the README wording "six", and changing a test that asserts the count is six. Six edits, one restart, and no single place that says what a model is. This plan makes the registry the only source: one entry per model with its provider, display data, reasoning levels, modalities, quirks and catalogue numbers. Everything else derives from it, and the catalogue entries for OpenRouter models are generated from a template, so adding a model is one entry plus one generation run.

## Current state

- `capabilities.py:10-32` (verbatim):

```python
OPENROUTER_MODELS = frozenset({
    'meta/muse-spark-1.3', 'meta/muse-spark-1.3-contributor',
    'z-ai/glm-5.3-flash', 'z-ai/glm-5.3', 'moonshotai/kimi-k3',
    '~x-ai/grok-latest',
})
IMAGE_INPUT_MODELS = OPENROUTER_MODELS - {'z-ai/glm-5.3'}
EXCLUDED_EFFORTS = {
    'meta/muse-spark-1.3-contributor': {'max'},
}
EFFORT_DESCRIPTIONS = {'xhigh': 'Extra high reasoning', 'max': 'Maximum reasoning'}
CANONICAL_ORDER = ['minimal', 'low', 'medium', 'high', 'xhigh', 'max']
REASONING_LEVELS = {
    'meta/muse-spark-1.3': ['minimal', 'low', 'medium', 'high', 'xhigh', 'max'],
    'meta/muse-spark-1.3-contributor': ['minimal', 'low', 'medium', 'high', 'xhigh'],
    'z-ai/glm-5.3-flash': ['low', 'high', 'max'],
    'z-ai/glm-5.3': ['low', 'high', 'max'],
    'moonshotai/kimi-k3': ['low', 'high', 'max'],
    '~x-ai/grok-latest': ['low', 'medium', 'high', 'xhigh'],
}
```

  followed by `MULTI_AGENT_VERSION = 'v1'`, `NODE_REPL_DISABLED = False`, `COMP_HASH = None`, functions `input_modalities`, `reasoning_levels`, `live_levels`, `describe`, `advertised_or_pinned`, `checked_level_entries`, `catalogue_patch`, and `OPENROUTER_HOST = 'openrouter.ai'`.
- Slug-string quirks in `tool_adapter.py`:
  - `:82` `elif payload.get('model', '').startswith('meta/muse-') and has_recursive_refs(tool.get('parameters', {})):` (recursive schemas carried as JSON text for Meta).
  - `:104-105` `if payload.get('model') == '~x-ai/grok-latest' and len(flattened) > 350: raise ValueError('Grok supports at most 350 exposed tools. ...')`.
- `tests/test_capabilities.py:7` `self.assertEqual(len(OPENROUTER_MODELS), 6)`.
- `README.md:7` says "The six".
- OpenAI model membership lives in the runtime state file as `openai_models` (nine slugs on the author's machine: `gpt-6-astra`, `gpt-reserve`, `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`, `gpt-5.5`, `gpt-5.4-mini`, `gpt-5.3-codex-spark`, `codex-auto-review`).
- The deployed catalogue `mixed-models.json` (not in git) has 15 entries under a top-level `models` list. Each OpenRouter entry has these fields, with the per-model values in bold: **`slug`**, **`display_name`** (`"GLM 5.3 Flash · OpenRouter"`), **`description`** (`"OpenRouter billing. Choose before starting a fresh task. OpenRouter: Z.ai: GLM 5.3 Flash"`), **`default_reasoning_level`**, **`supported_reasoning_levels`** (list of `{effort, description}`), `shell_type: "unified_exec"`, `visibility: "list"`, `supported_in_api: true`, **`priority`** (102 for GLM Flash; OpenRouter entries use 100 and up), `additional_speed_tiers: []`, `service_tiers: []`, `availability_nux: null`, `upgrade: null`, `model_messages: null`, `include_skills_usage_instructions: true`, `include_plugin_usage_instructions: true`, `include_apps_usage_instructions: true`, `default_reasoning_summary: "none"`, `support_verbosity: false`, `default_verbosity: "low"`, `apply_patch_tool_type: null`, `web_search_tool_type: "text_and_image"`, `truncation_policy: {"mode": "tokens", "limit": 10000}`, `supports_image_detail_original: true`, **`context_window`** and **`max_context_window`** (1310720 for GLM Flash), `comp_hash: null`, `effective_context_window_percent: 90`, `experimental_supported_tools: []`, **`input_modalities`**, `supports_search_tool: true`, `use_responses_lite: false`, `node_repl_auto_review_required: false`, `node_repl_disabled: false`, `base_instructions` (a long shared prompt beginning "You are Codex, a coding agent running the selected OpenRouter model."), `tool_mode: null`, `multi_agent_version: "v1"`, `multi_agent_reasoning_effort: null`.
- `apply_catalogue.py:9-25` `apply(catalog, live)` patches only slugs already present; `:27-37` `write_guarded` does the safe atomic write with `.bak`.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Tests | `python3.14 -m unittest discover -s tests -t . -v` | `OK` |
| Source limits | `python3.14 tools/check_source_limits.py` | `failures=0` |
| Regenerate check (Step 5) | `python3.14 -m codex_router.catalogue --check ~/.codex/mixed-model-router/mixed-models.json` | `identical: 6 entries` |

## Scope

**In scope**: new `codex_router/registry.py`, new `codex_router/catalogue.py`, `codex_router/capabilities.py`, `codex_router/tool_adapter.py` (two lines), `codex_router/apply_catalogue.py`, `codex_router/update_reasoning_catalog.py`, `tests/test_capabilities.py`, `tests/test_apply_catalogue.py`, new `tests/test_registry.py`, `README.md` (the word "six").

**Out of scope**: `router.py` and `providers.py` (Plan 037 wires them), `compaction.py`, the deployed catalogue file on any machine (Step 5 reads it, never writes it), the OpenAI catalogue entries (Plan 039).

## Git workflow

- Branch `codex/router-registry-<yyyymmdd>`; commits `refactor:`/`feat:`/`test:`. Do not push unless instructed.

## Steps

### Step 1: Write the registry

Create `codex_router/registry.py`:

```python
"""The one place that says what a model is. Everything else derives from MODELS."""
from dataclasses import dataclass, field

@dataclass(frozen=True)
class Model:
    slug: str
    provider: str                 # 'openrouter' | 'openai'
    display_name: str             # picker label, e.g. 'GLM 5.3 Flash · OpenRouter'
    vendor: str                   # 'Z.ai'
    reasoning: tuple              # last-known-good levels, canonical order
    default_reasoning: str
    modalities: tuple = ('text', 'image')
    excluded_efforts: frozenset = frozenset()   # live-advertised but proven unsupported
    schema_mode: str = 'native'   # 'native' | 'json_text' (recursive schemas as JSON string)
    max_tools: int | None = None  # provider ceiling on exposed tools
    context_window: int = 0
    priority: int = 100

MODELS = (
    Model('meta/muse-spark-1.3', 'openrouter', 'Muse Spark 1.3 · OpenRouter', 'Meta',
          ('minimal', 'low', 'medium', 'high', 'xhigh', 'max'), 'low', schema_mode='json_text',
          context_window=<from deployed catalogue>, priority=<from deployed catalogue>),
    Model('meta/muse-spark-1.3-contributor', 'openrouter', 'Muse Spark 1.3 Contributor · OpenRouter', 'Meta',
          ('minimal', 'low', 'medium', 'high', 'xhigh'), 'low', excluded_efforts=frozenset({'max'}),
          schema_mode='json_text', context_window=..., priority=...),
    Model('z-ai/glm-5.3-flash', 'openrouter', 'GLM 5.3 Flash · OpenRouter', 'Z.ai', ('low', 'high', 'max'), 'low',
          context_window=1310720, priority=102),
    Model('z-ai/glm-5.3', 'openrouter', 'GLM 5.3 · OpenRouter', 'Z.ai', ('low', 'high', 'max'), 'low',
          modalities=('text',), context_window=..., priority=...),
    Model('moonshotai/kimi-k3', 'openrouter', 'Kimi K3 · OpenRouter', 'Moonshot AI', ('low', 'high', 'max'), 'low',
          context_window=..., priority=...),
    Model('~x-ai/grok-latest', 'openrouter', 'Grok (latest) · OpenRouter', 'xAI', ('low', 'medium', 'high', 'xhigh'), 'low',
          max_tools=350, context_window=..., priority=...),
)

BY_SLUG = {m.slug: m for m in MODELS}

def by_slug(slug):
    return BY_SLUG.get(slug)

def openrouter_slugs():
    return frozenset(m.slug for m in MODELS if m.provider == 'openrouter')
```

Fill every `<from deployed catalogue>` value by reading the deployed file on the author's machine: `python3.14 -c "import json; [print(m['slug'], m['display_name'], m['priority'], m['context_window'], m['input_modalities']) for m in json.load(open('/Users/cyrilallart/.codex/mixed-model-router/mixed-models.json'))['models'] if '/' in m['slug']]"`. Do not guess them.

OpenAI models are not listed in the registry in this plan; the subscription provider recognises them from `state['openai_models']` until Plan 039 makes the OpenAI catalogue live. Add a comment saying so.

**Verify**: `python3.14 -c "from codex_router.registry import MODELS, openrouter_slugs; print(len(MODELS), sorted(openrouter_slugs()))"` prints `6` and the six slugs.

### Step 2: Derive `capabilities.py` from the registry

Replace lines 10 to 32 of `capabilities.py` with derivations, keeping every public function name and signature so callers and tests keep working:

```python
from .registry import MODELS, by_slug, openrouter_slugs
OPENROUTER_MODELS = openrouter_slugs()
IMAGE_INPUT_MODELS = frozenset(m.slug for m in MODELS if 'image' in m.modalities)
EXCLUDED_EFFORTS = {m.slug: set(m.excluded_efforts) for m in MODELS if m.excluded_efforts}
REASONING_LEVELS = {m.slug: list(m.reasoning) for m in MODELS}
```

Leave `EFFORT_DESCRIPTIONS`, `CANONICAL_ORDER`, `MULTI_AGENT_VERSION`, `NODE_REPL_DISABLED`, `COMP_HASH`, `OPENROUTER_HOST` and all functions unchanged.

**Verify**: `python3.14 -m unittest tests.test_capabilities -v` passes except the count test (fixed in Step 6).

### Step 3: Quirks become data in `tool_adapter.py`

Line 82: replace `payload.get('model', '').startswith('meta/muse-')` with `_quirk(payload, 'schema_mode') == 'json_text'`. Lines 104 to 105: replace with

```python
ceiling = _quirk(payload, 'max_tools')
if ceiling and len(flattened) > ceiling:
    raise ValueError(f'{payload.get("model")} supports at most {ceiling} exposed tools. Restart Codex and start a fresh task to load the deferred tool catalog.')
```

and add at module level:

```python
from .registry import by_slug
def _quirk(payload, name):
    entry = by_slug(payload.get('model', ''))
    return getattr(entry, name, None) if entry else None
```

Update `tests/test_tool_adapter.py:15-19` only if its regex `'350'` no longer matches (it will still match because the number is in the message).

**Verify**: `python3.14 -m unittest tests.test_tool_adapter -v` passes unchanged.

### Step 4: Generate OpenRouter catalogue entries from a template

Create `codex_router/catalogue.py` with:

- `OPENROUTER_TEMPLATE`: a dict of every non-bold field from Current state with its constant value.
- `openrouter_base_instructions()`: returns the shared prompt text, stored once in `codex_router/openrouter_base_instructions.txt` (copy it verbatim from any OpenRouter entry's `base_instructions` in the deployed catalogue; the six entries must share the same text, see STOP conditions).
- `openrouter_entry(model)`: returns `{**OPENROUTER_TEMPLATE, 'slug': model.slug, 'display_name': model.display_name, 'description': f'OpenRouter billing. Choose before starting a fresh task. OpenRouter: {model.vendor}: {display without the " · OpenRouter" suffix}', 'default_reasoning_level': model.default_reasoning, 'supported_reasoning_levels': [{'effort': lv, 'description': describe(lv)} for lv in model.reasoning], 'priority': model.priority, 'context_window': model.context_window, 'max_context_window': model.context_window, 'input_modalities': list(model.modalities), 'base_instructions': openrouter_base_instructions(), **catalogue_patch(model.slug)}` using `describe` and `catalogue_patch` from `capabilities.py`.
- `merge(catalog)`: for each registry OpenRouter model, replace the entry with the same slug or append a generated one; returns the catalogue.
- A `__main__` with `--check <path>`: loads the file, generates entries for the six registry models, compares each to the existing entry with the same slug field by field, prints `identical: N entries` or the differing field names per slug and exits 1.

Rewrite `apply_catalogue.py` so `apply(catalog, live)` calls `merge(catalog)` first and then applies the live OpenRouter metadata exactly as today. `update_reasoning_catalog.py` is unchanged in behaviour.

**Verify**: `python3.14 -m compileall -q codex_router` exits 0.

### Step 5: Prove the generator reproduces today's entries

Run `python3.14 -m codex_router.catalogue --check ~/.codex/mixed-model-router/mixed-models.json` on the author's machine.

**Verify**: prints `identical: 6 entries`. If any slug reports differing fields, fix the template or registry values until identical. Fields that legitimately differ per model must be registry fields; do not special-case a slug in code.

### Step 6: Registry-driven tests and docs

- `tests/test_capabilities.py:6-7`: replace the `len == 6` assertion with `self.assertEqual(OPENROUTER_MODELS, {m.slug for m in MODELS if m.provider == 'openrouter'})`.
- New `tests/test_registry.py`: `test_slugs_unique`, `test_default_reasoning_is_supported` (for every model, `default_reasoning in reasoning`), `test_reasoning_in_canonical_order`, `test_excluded_efforts_not_in_reasoning`, `test_provider_is_known` (`provider in {'openrouter', 'openai'}`), `test_openrouter_entry_has_every_catalogue_field` (generated entry keys equal the key set listed in Current state).
- `README.md:7`: replace "The six" with "The configured OpenRouter models (see `codex_router/registry.py`)". Add a short "Adding a model" section: add a `Model(...)` entry, run `python3.14 -m codex_router.apply_catalogue <catalogue> <live-models.json>` (or the Plan 039 dynamic path), restart the router, run the probe once on low effort.

**Verify**: full suite `OK`; `grep -n "six" README.md` returns nothing relevant.

## Test plan

Tests listed in Step 6, modelled on `tests/test_capabilities.py` (`InvariantTests`). Verification: full suite `OK`, `test_registry.py` six tests passing.

## Done criteria

- [ ] `python3.14 -m codex_router.catalogue --check <deployed catalogue>` prints `identical: 6 entries`.
- [ ] `grep -n "meta/muse-\|grok-latest\|350" codex_router/tool_adapter.py` returns nothing.
- [ ] `grep -n "'z-ai/\|'meta/\|'moonshotai/\|'~x-ai/" codex_router/capabilities.py` returns nothing (slugs live only in `registry.py`).
- [ ] Full suite `OK`; `tests/test_registry.py` present.
- [ ] Source limits `failures=0`.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- The six deployed OpenRouter entries do not share identical `base_instructions` text. Report the differences; do not invent a per-model prompt field without the operator's decision.
- Step 5 cannot reach `identical` because a field differs in a way that is not explained by any registry attribute (for example a different `truncation_policy`). Report the field and slug.
- The deployed catalogue file is not readable on the executing machine (this plan needs the author's machine or a copy of the file supplied by the operator).

## Maintenance notes

- Adding a model: one `Model(...)` line, regenerate, restart, probe. Reviewers should reject slug literals anywhere outside `registry.py`.
- Plan 039 will generate OpenRouter entries at request time from this same `openrouter_entry`, so keep it pure (no file access besides the instructions text, which should be read once at import).
- Plan 037 uses `by_slug(model).provider` for membership; until Plan 039, OpenAI slugs come from state, which is why `MODELS` has no OpenAI rows yet.
