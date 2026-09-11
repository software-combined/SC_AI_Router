"""The one place that says what a model is. Data lives in models.json.

Everything else derives from MODELS. Keep the loader pure (text in,
validated registry out) so Plan 099 can reload it at runtime.

`provider` is a key into the provider definition table
(`ai_router/provider_defs.py`), the one owner of upstream facts; the
registry only says which upstream serves a row.
"""
import json
from dataclasses import dataclass
from pathlib import Path

from . import provider_defs

FIELDS = ('slug', 'provider', 'display_name', 'vendor', 'reasoning',
          'default_reasoning', 'modalities', 'excluded_efforts',
          'schema_mode', 'max_tools', 'drop_images', 'context_window',
          'priority', 'max_output_tokens', 'reasoning_summary',
          'apply_patch', 'experimental_tools', 'web_search', 'tier')


@dataclass(frozen=True)
class Model:
    slug: str
    provider: str                 # a provider_defs id, e.g. 'openrouter' | 'openai'
    display_name: str             # picker label, e.g. 'Z.ai: GLM 5.3 Flash · OpenRouter'
    vendor: str                   # 'Z.ai'
    reasoning: tuple              # last-known-good levels, canonical order
    default_reasoning: str
    modalities: tuple = ('text', 'image')
    excluded_efforts: frozenset = frozenset()   # live-advertised but proven unsupported
    schema_mode: str = 'native'   # 'native' | 'json_text' (recursive schemas as JSON string)
                                  # | 'json_text_root' (non-object roots as JSON value)
    max_tools: int | None = None  # provider ceiling on exposed tools
    drop_images: bool = False  # upstream stalls on image input; run text-only
    context_window: int = 0
    priority: int = 100
    max_output_tokens: int = 32768   # live-refreshed output ceiling
    reasoning_summary: str = 'none'  # 'none' | 'auto' (probe-gated)
    apply_patch: str = 'none'        # 'none' | 'freeform' (probe-gated)
    experimental_tools: tuple = ()   # probe-gated tool names
    web_search: bool = True          # False downgrades search to text-only
    tier: str = 'verified'           # 'verified' | 'preview'


def load(text):
    """Validate models.json text into a tuple of Model rows."""
    try:
        rows = json.loads(text)
    except ValueError as exc:
        raise SystemExit(f'models.json is not valid JSON ({exc.__class__.__name__})')
    if not isinstance(rows, list) or not rows:
        raise SystemExit('models.json must be a non-empty list')
    models = []
    seen = set()
    for i, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != set(FIELDS):
            raise SystemExit(f'models.json row {i} must have exactly: {", ".join(FIELDS)}')
        if row['slug'] in seen:
            raise SystemExit(f'models.json duplicate slug: {row["slug"]}')
        seen.add(row['slug'])
        if not provider_defs.is_external(row['provider']) \
                and row['provider'] not in provider_defs.subscription_ids():
            raise SystemExit(f'models.json {row["slug"]}: bad provider')
        if row['schema_mode'] not in ('native', 'json_text', 'json_text_root'):
            raise SystemExit(f'models.json {row["slug"]}: bad schema_mode')
        if row['default_reasoning'] not in row['reasoning']:
            raise SystemExit(f'models.json {row["slug"]}: default not in reasoning')
        if row['reasoning_summary'] not in ('none', 'auto'):
            raise SystemExit(f'models.json {row["slug"]}: bad reasoning_summary')
        if row['apply_patch'] not in ('none', 'freeform'):
            raise SystemExit(f'models.json {row["slug"]}: bad apply_patch')
        if (not isinstance(row['max_output_tokens'], int)
                or isinstance(row['max_output_tokens'], bool)
                or row['max_output_tokens'] <= 0):
            raise SystemExit(f'models.json {row["slug"]}: bad max_output_tokens')
        if not isinstance(row['web_search'], bool):
            raise SystemExit(f'models.json {row["slug"]}: bad web_search')
        if not isinstance(row['drop_images'], bool):
            raise SystemExit(f'models.json {row["slug"]}: bad drop_images')
        if (not isinstance(row['experimental_tools'], list)
                or any(not isinstance(name, str) for name in row['experimental_tools'])):
            raise SystemExit(f'models.json {row["slug"]}: bad experimental_tools')
        if row['tier'] not in ('verified', 'preview'):
            raise SystemExit(f'models.json {row["slug"]}: bad tier')
        models.append(Model(
            slug=row['slug'], provider=row['provider'], display_name=row['display_name'],
            vendor=row['vendor'], reasoning=tuple(row['reasoning']),
            default_reasoning=row['default_reasoning'], modalities=tuple(row['modalities']),
            excluded_efforts=frozenset(row['excluded_efforts']), schema_mode=row['schema_mode'],
            max_tools=row['max_tools'], drop_images=row['drop_images'],
            context_window=row['context_window'],
            priority=row['priority'], max_output_tokens=row['max_output_tokens'],
            reasoning_summary=row['reasoning_summary'], apply_patch=row['apply_patch'],
            experimental_tools=tuple(row['experimental_tools']),
            web_search=row['web_search'], tier=row['tier']))
    return tuple(models)


MODELS = load((Path(__file__).with_name('models.json')).read_text())
BY_SLUG = {m.slug: m for m in MODELS}


def by_slug(slug):
    return BY_SLUG.get(slug)


def near_miss(model):
    """Canonical slug for a bare tilde-alias id, else None. Pure.

    Discovery lists tilde rows without their `~` (Claude ingress), so a
    caller can echo back an id the Responses path never owned. Offer the
    exact canonical slug only when the bare id is absent and `~`+bare is
    present; never fuzzy-match, never route."""
    if not isinstance(model, str) or not model or by_slug(model) is not None:
        return None
    candidate = '~' + model
    return candidate if by_slug(candidate) is not None else None


def picker_key(vendor, tier, display_name, slug):
    """Vendor-grouped picker order: vendor A-Z, verified before preview.

    Codex lists the picker by ascending priority, so registry priorities
    must ascend in this order; merge emits file rows in it as well."""
    return (vendor.casefold(), tier != 'verified', display_name.casefold(), slug)


def external_slugs():
    """Every slug billed on an external provider's own key (Plan 141)."""
    return frozenset(m.slug for m in MODELS if provider_defs.is_external(m.provider))
