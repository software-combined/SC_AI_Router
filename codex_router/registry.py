"""The one place that says what a model is. Data lives in models.json.

Everything else derives from MODELS. Keep the loader pure (text in,
validated registry out) so Plan 046 can reload it at runtime.
"""
import json
from dataclasses import dataclass
from pathlib import Path

FIELDS = ('slug', 'provider', 'display_name', 'vendor', 'reasoning',
          'default_reasoning', 'modalities', 'excluded_efforts',
          'schema_mode', 'max_tools', 'drop_images', 'context_window',
          'priority', 'max_output_tokens', 'reasoning_summary',
          'apply_patch', 'experimental_tools', 'web_search', 'tier')


@dataclass(frozen=True)
class Model:
    slug: str
    provider: str                 # 'openrouter' | 'openai'
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
        if row['provider'] not in ('openrouter', 'openai'):
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


def openrouter_slugs():
    return frozenset(m.slug for m in MODELS if m.provider == 'openrouter')
