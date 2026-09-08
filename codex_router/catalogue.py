"""Generate OpenRouter catalogue entries from the registry.

Every non-model-specific field lives in OPENROUTER_TEMPLATE. Per-model
values come from codex_router/registry.py rows. Pure: no network, no
state; the instructions text is read once at import.
"""
import json
import sys
from pathlib import Path
from .capabilities import catalogue_patch, describe
from .registry import MODELS, models_for, visible_for

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

PREVIEW_PRIORITY_OFFSET = 100000  # preview entries sort after every verified model
RETIRED_SLUGS = {'anthropic/claude-opus-5', 'anthropic/claude-fable-5.1'}


BASE_INSTRUCTIONS = (Path(__file__).with_name('openrouter_base_instructions.txt')).read_text()


def catalog_name(model):
    short = model.display_name.removesuffix(' · OpenRouter')
    if short.startswith(model.vendor) or ': ' in short:
        return short  # Already carries its own vendor-style prefix (aliases do).
    return model.vendor + ': ' + short


def openrouter_entry(model):
    return {**OPENROUTER_TEMPLATE,
            'slug': model.slug,
            'display_name': (model.display_name + ' · Preview'
                             if model.tier == 'preview' else model.display_name),
            'description': (('Preview, not yet verified with Codex. '
                             if model.tier == 'preview' else '')
                            + 'OpenRouter billing. Choose before starting a fresh task. '
                            + 'OpenRouter: ' + catalog_name(model)),
            'default_reasoning_level': model.default_reasoning,
            'supported_reasoning_levels': [
                {'effort': level, 'description': describe(level)} for level in model.reasoning],
            'priority': (model.priority + PREVIEW_PRIORITY_OFFSET
                           if model.tier == 'preview' else model.priority),
            'context_window': model.context_window,
            'max_context_window': model.context_window,
            'model_messages': {'instructions_template': BASE_INSTRUCTIONS},
            **catalogue_patch(model.slug),
            'input_modalities': list(model.modalities),
            'default_reasoning_summary': model.reasoning_summary,
            'supports_reasoning_summary_parameter': model.reasoning_summary == 'auto',
            'apply_patch_tool_type': 'freeform' if model.apply_patch == 'freeform' else None,
            'experimental_supported_tools': list(model.experimental_tools),
            'web_search_tool_type': 'text_and_image' if model.web_search else 'text'}


def merge(catalog, roster=(), client='codex'):
    """Merge registry OpenRouter entries, dropping explicitly retired picker rows.

    Only models_for(client) OpenRouter entries are emitted: the Codex
    picker omits OpenRouter-billed GPT rows, so an upgrade merge also
    drops a pre-existing hidden row instead of preserving it. Roster
    slugs (the subscription side from runtime state) absent from the
    catalogue are appended as stubs so a fresh file still lists the
    approved picker; other existing rich entries are never rewritten.
    The future Claude listing reuses models_for('claude') to omit
    OpenRouter-billed Anthropic rows. Plan 039's live /models remains
    the proper replacement for this fallback. Routing never consults
    this filter.
    """
    visible = [m for m in models_for(client) if m.provider == 'openrouter']
    hidden = {m.slug for m in MODELS
              if m.provider == 'openrouter' and not visible_for(m, client)}
    active = {m.slug for m in MODELS}
    models = [m for m in catalog.get('models', [])
              if (m['slug'] not in RETIRED_SLUGS or m['slug'] in active)
              and m['slug'] not in hidden]
    entries = {m['slug']: m for m in models}
    for model in visible:
        entries[model.slug] = openrouter_entry(model)
    order = [m['slug'] for m in models]
    seen = set(order)
    for slug in roster:
        if slug not in entries:
            entries[slug] = {'slug': slug}
            order.append(slug)
    order += [m.slug for m in visible if m.slug not in seen]
    catalog['models'] = [entries[slug] for slug in order]
    return catalog


def read_roster(catalog_path):
    """Subscription roster from the state file beside the catalogue; () when absent."""
    try:
        state = json.loads((Path(catalog_path).parent / 'mixed-router-state.json').read_text())
    except (OSError, ValueError):
        return ()
    if not isinstance(state, dict):
        return ()
    roster = state.get('openai_models')
    return tuple(roster) if isinstance(roster, list) else ()


def _same(old, new, key):
    if key == 'supported_reasoning_levels':
        return ([e['effort'] for e in old.get(key, [])]
                == [e['effort'] for e in new.get(key, [])])
    return old.get(key) == new.get(key)


def check(path, client='codex'):
    catalog = json.loads(Path(path).read_text())
    existing = {m['slug']: m for m in catalog.get('models', [])}
    identical, total = 0, 0
    for model in (m for m in MODELS
                  if m.provider == 'openrouter' and not visible_for(m, client)):
        if model.slug in existing:
            print(f'{model.slug}: hidden from the {client} picker but present')
            return False
    for model in (m for m in models_for(client) if m.provider == 'openrouter'):
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


USAGE = ('usage: python3.14 -m codex_router.catalogue '
         '[--client codex|claude] --check|--merge <catalogue>')


if __name__ == '__main__':
    args = sys.argv[1:]
    client = 'codex'
    if args[:1] == ['--client']:
        if len(args) < 2 or args[1] not in ('codex', 'claude'):
            raise SystemExit(USAGE)
        client = args[1]
        args = args[2:]
    if args[:1] == ['--merge'] and len(args) == 2:
        path = Path(args[1])
        base = json.loads(path.read_text()) if path.exists() else {'models': []}
        path.write_text(json.dumps(merge(base, read_roster(path), client), indent=2) + '\n')
    elif args[:1] == ['--check'] and len(args) == 2:
        sys.exit(0 if check(args[1], client) else 1)
    else:
        raise SystemExit(USAGE)
