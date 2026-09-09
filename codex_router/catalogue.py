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
    # Codex >=0.153.4 catalogue schema: every row must carry these or chat
    # creation fails with 'missing field' (2026-09-08, Codex 26.901.51231).
    # Defaults mirror the client's own embedded model catalogue.
    'available_in_plans': ['business', 'edu', 'edu_plus', 'edu_pro', 'education',
                           'enterprise', 'enterprise_cbp_automation',
                           'enterprise_cbp_trial', 'enterprise_cbp_usage_based',
                           'finserv', 'free', 'free_workspace', 'go', 'hc', 'k12',
                           'plus', 'pro', 'prolite', 'quorum', 'sci',
                           'self_serve_business_prolite',
                           'self_serve_business_usage_based', 'team'],
    'prefer_websockets': True,
    'minimal_client_version': '0.153.0',
    'supports_parallel_tool_calls': True,
    'supports_reasoning_summaries': True,
    'default_service_tier': None,
    'model_specialty': None,
    'auto_compact_token_limit': None,
    'auto_review_model_override': None,
}

PREVIEW_PRIORITY_OFFSET = 100000  # preview entries sort after every verified model
RETIRED_SLUGS = {'anthropic/claude-opus-5', 'anthropic/claude-fable-5.1',
                 'deepseek/deepseek-v4-flash',
                 'deepseek/deepseek-v4-flash-0731'}  # superseded by the flash-latest alias

# Picker labels for the subscription side, matching the live Codex picker.
# Codex >=0.153.4 requires every catalogue row to carry display_name and the
# full schema, so roster rows can no longer seed as bare {'slug': ...} stubs.
SUBSCRIPTION_DISPLAY_NAMES = {
    'gpt-6-astra': 'GPT-6-Astra',
    'gpt-reserve': 'GPT-Reserve',
    'gpt-5.6-sol': 'GPT-5.6-Sol',
    'gpt-5.6-terra': 'GPT-5.6-Terra',
    'gpt-5.6-luna': 'GPT-5.6-Luna',
    'gpt-5.5': 'GPT-5.5',
    'gpt-5.4-mini': 'GPT-5.4-Mini',
    'gpt-5.3-codex-spark': 'GPT-5.3-Codex-Spark',
    'codex-auto-review': 'Codex Auto Review',
}


def subscription_stub(slug):
    """Full-schema placeholder row for a subscription-side picker slug.

    Routing ignores these fields (the subscription provider owns the slug),
    but the Codex catalogue parser requires the complete schema.
    """
    name = SUBSCRIPTION_DISPLAY_NAMES.get(slug, slug)
    return {**OPENROUTER_TEMPLATE,
            'slug': slug,
            'display_name': name,
            'description': 'ChatGPT subscription billing.',
            'default_reasoning_level': 'medium',
            'supported_reasoning_levels': [{'effort': 'medium', 'description': 'Balanced.'}],
            'supports_reasoning_summary_parameter': False,
            'context_window': 272000,
            'max_context_window': 272000,
            'input_modalities': ['text', 'image'],
            'priority': 1,
            'model_messages': {'instructions_template': BASE_INSTRUCTIONS}}


BASE_INSTRUCTIONS = (Path(__file__).with_name('openrouter_base_instructions.txt')).read_text()


def catalog_name(model):
    # display_name is stored qualified (<Vendor>: <Model> <Version?>), so this
    # is a pure suffix strip; bare legacy rows fail the registry test instead.
    return model.display_name.removesuffix(' · OpenRouter')


def openrouter_entry(model):
    return {**OPENROUTER_TEMPLATE,
            'slug': model.slug,
            'display_name': (model.display_name + ' · Preview'
                             if model.tier == 'preview' else model.display_name),
            'description': (('Preview, not yet verified with Codex. '
                             if model.tier == 'preview' else '')
                            + 'OpenRouter billing. Switch to this model mid-thread; history carries over. '
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
    approved picker. Existing rows gain missing schema defaults while
    retaining their model-specific values, repairing older bare stubs.
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
    entries = {m['slug']: {**subscription_stub(m['slug']), **m} for m in models}
    for model in visible:
        entries[model.slug] = openrouter_entry(model)
    order = [m['slug'] for m in models]
    seen = set(order)
    for slug in roster:
        if slug not in entries:
            entries[slug] = subscription_stub(slug)
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
    for slug, row in existing.items():
        missing = subscription_stub(slug).keys() - row.keys()
        if missing:
            print(f'{slug}: missing schema fields: {", ".join(sorted(missing))}')
            return False
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
