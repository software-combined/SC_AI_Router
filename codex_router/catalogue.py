"""Generate OpenRouter catalogue entries from the registry.

Every non-model-specific field lives in OPENROUTER_TEMPLATE. Per-model
values come from codex_router/registry.py rows. Pure: no network, no
state; the instructions text is read once at import.
"""
import json
import sys
from pathlib import Path
from .capabilities import catalogue_patch, describe
from .registry import MODELS

OPENROUTER_TEMPLATE = {
    'shell_type': 'unified_exec',
    'visibility': 'list',
    'supported_in_api': True,
    'additional_speed_tiers': [],
    'service_tiers': [],
    'availability_nux': None,
    'upgrade': None,
    'model_messages': None,
    'include_skills_usage_instructions': True,
    'include_plugin_usage_instructions': True,
    'include_apps_usage_instructions': True,
    'default_reasoning_summary': 'none',
    'support_verbosity': False,
    'default_verbosity': 'low',
    'apply_patch_tool_type': None,
    'web_search_tool_type': 'text_and_image',
    'truncation_policy': {'mode': 'tokens', 'limit': 10000},
    'supports_image_detail_original': True,
    'comp_hash': None,
    'effective_context_window_percent': 90,
    'experimental_supported_tools': [],
    'supports_search_tool': True,
    'use_responses_lite': False,
    'node_repl_auto_review_required': False,
    'node_repl_disabled': False,
    'tool_mode': None,
    'multi_agent_version': 'v1',
    'multi_agent_reasoning_effort': None,
}

BASE_INSTRUCTIONS = (Path(__file__).with_name('openrouter_base_instructions.txt')).read_text()


def catalog_name(model):
    short = model.display_name.removesuffix(' · OpenRouter')
    return short if short.startswith(model.vendor) else model.vendor + ': ' + short


def openrouter_entry(model):
    return {**OPENROUTER_TEMPLATE,
            'slug': model.slug,
            'display_name': model.display_name,
            'description': ('OpenRouter billing. Choose before starting a fresh task. '
                            'OpenRouter: ' + catalog_name(model)),
            'default_reasoning_level': model.default_reasoning,
            'supported_reasoning_levels': [
                {'effort': level, 'description': describe(level)} for level in model.reasoning],
            'priority': model.priority,
            'context_window': model.context_window,
            'max_context_window': model.context_window,
            'input_modalities': list(model.modalities),
            'base_instructions': BASE_INSTRUCTIONS,
            **catalogue_patch(model.slug)}


def merge(catalog):
    entries = {m['slug']: m for m in catalog.get('models', [])}
    for model in MODELS:
        if model.provider == 'openrouter':
            entries[model.slug] = openrouter_entry(model)
    seen = {m['slug'] for m in catalog.get('models', [])}
    order = [m['slug'] for m in catalog.get('models', []) if m['slug'] in entries]
    order += [m.slug for m in MODELS if m.provider == 'openrouter' and m.slug not in seen]
    catalog['models'] = [entries[slug] for slug in order]
    return catalog


def _same(old, new, key):
    if key == 'supported_reasoning_levels':
        return ([e['effort'] for e in old.get(key, [])]
                == [e['effort'] for e in new.get(key, [])])
    return old.get(key) == new.get(key)


def check(path):
    catalog = json.loads(Path(path).read_text())
    existing = {m['slug']: m for m in catalog.get('models', [])}
    identical, total = 0, 0
    for model in MODELS:
        if model.provider != 'openrouter':
            continue
        total += 1
        old = existing.get(model.slug)
        if old is None:
            print(f'{model.slug}: missing from catalogue')
            continue
        new = openrouter_entry(model)
        diff = [k for k in set(old) | set(new) if not _same(old, new, k)]
        if diff:
            print(f'{model.slug}: differs in {", ".join(sorted(diff))}')
        else:
            identical += 1
    print(f'identical: {identical} entries')
    return identical == total


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != '--check':
        raise SystemExit('usage: python3.14 -m codex_router.catalogue --check <catalogue>')
    sys.exit(0 if check(sys.argv[2]) else 1)
