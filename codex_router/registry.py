"""The one place that says what a model is. Data lives in models.json.

Everything else derives from MODELS. Keep the loader pure (text in,
validated registry out) so Plan 046 can reload it at runtime.
"""
import json
from dataclasses import dataclass
from pathlib import Path

FIELDS = ('slug', 'provider', 'display_name', 'vendor', 'reasoning',
          'default_reasoning', 'modalities', 'excluded_efforts',
          'schema_mode', 'max_tools', 'context_window', 'priority')


@dataclass(frozen=True)
class Model:
    slug: str
    provider: str                 # 'openrouter' | 'openai'
    display_name: str             # picker label, e.g. 'GLM 5.3 Flash'
    vendor: str                   # 'Z.ai'
    reasoning: tuple              # last-known-good levels, canonical order
    default_reasoning: str
    modalities: tuple = ('text', 'image')
    excluded_efforts: frozenset = frozenset()   # live-advertised but proven unsupported
    schema_mode: str = 'native'   # 'native' | 'json_text' (recursive schemas as JSON string)
    max_tools: int | None = None  # provider ceiling on exposed tools
    context_window: int = 0
    priority: int = 100


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
        if row['schema_mode'] not in ('native', 'json_text'):
            raise SystemExit(f'models.json {row["slug"]}: bad schema_mode')
        if row['default_reasoning'] not in row['reasoning']:
            raise SystemExit(f'models.json {row["slug"]}: default not in reasoning')
        models.append(Model(
            slug=row['slug'], provider=row['provider'], display_name=row['display_name'],
            vendor=row['vendor'], reasoning=tuple(row['reasoning']),
            default_reasoning=row['default_reasoning'], modalities=tuple(row['modalities']),
            excluded_efforts=frozenset(row['excluded_efforts']), schema_mode=row['schema_mode'],
            max_tools=row['max_tools'], context_window=row['context_window'],
            priority=row['priority']))
    return tuple(models)


MODELS = load((Path(__file__).with_name('models.json')).read_text())
BY_SLUG = {m.slug: m for m in MODELS}


def by_slug(slug):
    return BY_SLUG.get(slug)


def openrouter_slugs():
    return frozenset(m.slug for m in MODELS if m.provider == 'openrouter')
