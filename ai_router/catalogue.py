"""Generate external-provider catalogue entries from the registry.

Every non-model-specific field lives in ROW_TEMPLATE. Per-model
values come from ai_router/registry.py rows. Pure: no network, no
state; the served instructions come from the model_instructions leaf.

The picker label suffix and billing line come from the row's provider
definition (`provider_defs.label_for`), so a second provider reads as its
own label with no code change here.
"""
import json
import sys
from pathlib import Path
from . import context_recovery, provider_defs, state as state_mod
from .atomic_write import replace_json
from .capabilities import (COMP_HASH, MULTI_AGENT_VERSION, NODE_REPL_DISABLED,
                           catalogue_patch, describe)
from .clients.codex import capability_fields as codex_projection
from .clients import client_ids, models_for
from .model_instructions import (SUBAGENT_MODEL_PLACEHOLDER,
                                 SUBSCRIBER_INSTRUCTIONS, instructions_for,
                                 is_routed_text)
from .registry import MODELS, picker_key
from .retired_slugs import SUBSCRIPTION as RETIRED_SUBSCRIPTION_SLUGS
from .subscription_roster import SUBSCRIPTION_SLUGS

ROW_TEMPLATE = {
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
    'comp_hash': COMP_HASH,
    'effective_context_window_percent': 90,
    'experimental_supported_tools': [],
    'supports_search_tool': True,
    'use_responses_lite': False,
    'node_repl_auto_review_required': False,
    'node_repl_disabled': NODE_REPL_DISABLED,
    'tool_mode': None,
    'multi_agent_version': MULTI_AGENT_VERSION,
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

# Claude, Gemini and Grok pin exact ids, so their latest aliases retire.
# DeepSeek keeps Pro 0813 + V4.1 Flash; its alias and Vision rows retire too.
RETIRED_SLUGS = {'~anthropic/claude-sonnet-latest', '~anthropic/claude-fable-latest',
                 '~anthropic/claude-haiku-latest', '~anthropic/claude-opus-latest',
                 '~google/gemini-flash-latest', '~google/gemini-pro-latest',
                 '~x-ai/grok-latest',
                 'deepseek/deepseek-v4-pro', 'deepseek/deepseek-v4-flash',
                 'deepseek/deepseek-v4-flash-0731',
                 '~deepseek/deepseek-v4-flash-latest',
                 'deepseek/deepseek-v4-flash-vision-exp'}

# Retired subscription slugs live in retired_slugs.py (Plan 100 single source,
# shared with the installer prune); merge() drops them from stale machines.

# Native reasoning levels per subscription slug (2026-09-07 owner-Mac
# models_cache). Fresh installs seed these so the effort picker works.
_A = ('low', 'medium', 'high', 'xhigh', 'max', 'ultra')
_M = ('low', 'medium', 'high', 'xhigh', 'max')
_X = ('low', 'medium', 'high', 'xhigh')
SUBSCRIPTION_REASONING = {
    'gpt-6-astra': ('medium', _A), 'gpt-5.6-sol': ('low', _A),
    'gpt-5.6-terra': ('medium', _A), 'gpt-5.6-luna': ('medium', _M),
    'gpt-5.5': ('medium', _X), 'gpt-5.4-mini': ('medium', _X),
    'gpt-5.3-codex-spark': ('high', _X), 'codex-auto-review': ('medium', _M),
}


# Picker labels for the subscription side, matching the live Codex picker.
# Codex >=0.153.4 requires every catalogue row to carry display_name and the
# full schema, so roster rows can no longer seed as bare {'slug': ...} stubs.
SUBSCRIPTION_DISPLAY_NAMES = {
    'gpt-6-astra': 'GPT-6-Astra',
    'gpt-5.6-sol': 'GPT-5.6-Sol',
    'gpt-5.6-terra': 'GPT-5.6-Terra',
    'gpt-5.6-luna': 'GPT-5.6-Luna',
    'gpt-5.5': 'GPT-5.5',
    'gpt-5.4-mini': 'GPT-5.4-Mini',
    'gpt-5.3-codex-spark': 'GPT-5.3-Codex-Spark',
    'codex-auto-review': 'Codex Auto Review',
}


# Plan 123: the roster leaf owns the subscription slug set; these tables own
# the per-slug presentation values. Fail closed at import when they disagree
# so a half-added row can never ship; the coupling test pins the same set.
if (set(SUBSCRIPTION_REASONING) != set(SUBSCRIPTION_SLUGS)
        or set(SUBSCRIPTION_DISPLAY_NAMES) != set(SUBSCRIPTION_SLUGS)):
    raise ValueError('subscription roster and catalogue tables disagree')


def subscription_stub(slug, instructions=None):
    """Full-schema placeholder row for a subscription-side picker slug.

    Routing ignores these fields (the subscription provider owns the slug),
    but the Codex catalogue parser requires the complete schema.
    """
    name = SUBSCRIPTION_DISPLAY_NAMES.get(slug, slug)
    default, efforts = SUBSCRIPTION_REASONING.get(slug, ('medium', ('medium',)))
    if instructions is None:
        instructions = instructions_for(_visible_rows('codex', None)[0],
                                        base=SUBSCRIBER_INSTRUCTIONS)
    return {**ROW_TEMPLATE,
            'slug': slug,
            'display_name': name,
            'description': 'ChatGPT subscription billing.',
            'default_reasoning_level': default,
            'supported_reasoning_levels': [
                {'effort': level, 'description': describe(level)} for level in efforts],
            'supports_reasoning_summary_parameter': False,
            'context_window': 272000,
            'max_context_window': 272000,
            'input_modalities': ['text', 'image'],
            'priority': 1,
            'model_messages': {'instructions_template': instructions}}


def catalog_name(model):
    # display_name is stored qualified (<Vendor>: <Model> <Version?>).
    return model.display_name.removesuffix(' · ' + label_of(model))


def label_of(row):
    """Provider label for a registry row or a raw models.json row."""
    provider_id = row.get('provider') if isinstance(row, dict) else getattr(row, 'provider', None)
    return provider_defs.label_for(provider_id or provider_defs.DEFAULT_EXTERNAL)


def external_entry(model, instructions=None):
    projected = codex_projection(model)
    label = label_of(model)
    if instructions is None:
        instructions = instructions_for(_visible_rows('codex', None)[0])
    return {**ROW_TEMPLATE,
            'slug': model.slug,
            'display_name': (model.display_name + ' · Preview'
                             if model.tier == 'preview' else model.display_name),
            'description': (('Preview, not yet verified with Codex. '
                             if model.tier == 'preview' else '')
                            + f'{label} billing. Switch to this model mid-thread; history carries over. '
                            + label + ': ' + catalog_name(model)),
            'default_reasoning_level': model.default_reasoning,
            'supported_reasoning_levels': projected['supported_reasoning_levels'],
            'priority': model.priority,
            'context_window': model.context_window,
            'max_context_window': model.context_window,
            'model_messages': {'instructions_template': instructions},
            **catalogue_patch(model.slug),
            'input_modalities': projected['input_modalities'],
            'default_reasoning_summary': model.reasoning_summary,
            'supports_reasoning_summary_parameter': model.reasoning_summary == 'auto',
            'apply_patch_tool_type': 'freeform' if model.apply_patch == 'freeform' else None,
            'experimental_supported_tools': list(model.experimental_tools),
            'web_search_tool_type': 'text_and_image' if model.web_search else 'text'}


def _visible_rows(client, allowed, include_twins=False, available=None):
    """(visible, hidden) external registry rows for one client and allowlist.

    `allowed` is the optional portco allowlist (Plan 068); `available` is
    the optional key-filtered id set from `/models/user`. Either None
    preserves today's behavior; a set hides rows the key cannot use. The
    registry is never pruned: hidden rows stay out of this catalogue
    until the key may use them again.
    """
    allowset = None if allowed is None else frozenset(allowed)
    avail = None if available is None else frozenset(available)
    visible = [m for m in models_for(MODELS, client, include_twins=include_twins)
               if provider_defs.is_external(m.provider)
               and (allowset is None or m.slug in allowset)
               and (avail is None or m.slug in avail)]
    shown = {m.slug for m in visible}
    hidden = [m for m in MODELS
              if provider_defs.is_external(m.provider) and m.slug not in shown]
    return visible, hidden


def merge(catalog, roster=(), client='codex', allowed=None, include_twins=False,
          available=None):
    """Merge registry OpenRouter entries into one client catalogue.

    Emits models_for(client) rows only; see _visible_rows for the
    allowlist and key filters. Roster stubs repair fresh files; retired
    subscription slugs never return. Routing never consults this filter.
    """
    visible, hidden_rows = _visible_rows(client, allowed, include_twins,
                                           available=available)
    instructions = instructions_for(visible, client)
    sub_instructions = instructions_for(visible, client,
                                        base=SUBSCRIBER_INSTRUCTIONS)
    shown = {m.slug for m in visible}
    hidden = {m.slug for m in hidden_rows}
    active = {m.slug for m in MODELS}
    models = [m for m in catalog.get('models', [])
              if (m['slug'] not in RETIRED_SLUGS or m['slug'] in active)
              and m['slug'] not in hidden]
    entries = {m['slug']: {**subscription_stub(m['slug'], instructions), **m}
               for m in models}
    for slug, row in entries.items():
        if slug in SUBSCRIPTION_SLUGS:
            # A row an older merge wrote with the routed text is upgraded to
            # the subscription wording; a hand-tuned row is left alone.
            template = (row.get('model_messages') or {}).get('instructions_template')
            if is_routed_text(template):
                row['model_messages'] = {'instructions_template': sub_instructions}
            else:
                row['model_messages'] = context_recovery.refresh_model_messages(
                    row.get('model_messages'), instructions)
        # Frozen 0.6.10.23 single-medium signature, exact match only.
        if (slug in SUBSCRIPTION_REASONING
                and row.get('default_reasoning_level') == 'medium'
                and row.get('supported_reasoning_levels') == [
                    {'effort': 'medium', 'description': 'Balanced.'}]):
            fresh = subscription_stub(slug)
            row['default_reasoning_level'] = fresh['default_reasoning_level']
            row['supported_reasoning_levels'] = fresh['supported_reasoning_levels']
    for model in visible:
        entries[model.slug] = external_entry(model, instructions)
    # Retired subscription rows never come back: a roster or catalogue that
    # still names one loses it here, so the dead picker row cannot linger.
    for slug in RETIRED_SUBSCRIPTION_SLUGS:
        entries.pop(slug, None)
    for slug in roster:
        # A roster stub repairs a fresh file only, never a hidden row.
        if (slug not in entries and slug not in RETIRED_SUBSCRIPTION_SLUGS
                and slug not in hidden):
            entries[slug] = subscription_stub(slug, sub_instructions)
    if include_twins:
        subs = []
    else:
        subs = [s for s in dict.fromkeys(roster) if s in entries]
        subs += [m['slug'] for m in models
                 if m['slug'] in entries and m['slug'] not in shown and m['slug'] not in subs]
    def rank(slug):
        model = next(m for m in visible if m.slug == slug)
        return picker_key(model.vendor, model.tier, model.display_name, model.slug)
    catalog['models'] = [entries[s] for s in subs + sorted(shown, key=rank)]
    return catalog


def _state_doc(catalog_path):
    """State dict beside the catalogue; {} when missing or unreadable."""
    return state_mod.read(state_mod.path(Path(catalog_path).parent)) or {}


def read_roster(catalog_path):
    """Subscription roster from the state file beside the catalogue; () when absent."""
    roster = _state_doc(catalog_path).get('openai_models')
    return tuple(roster) if isinstance(roster, list) else ()


def read_openai_mode(catalog_path):
    """openai_mode from the state file beside the catalogue; 'subscription' when absent."""
    mode = _state_doc(catalog_path).get('openai_mode')
    return mode if mode in ('none', 'subscription') else 'subscription'


def merge_file(path, client='codex', allowed=None, openai_mode=None,
               available=None):
    """Merge the catalogue file for the install's openai_mode and write it atomically."""
    path = Path(path)
    mode = openai_mode if openai_mode is not None else read_openai_mode(path)
    base = json.loads(path.read_text()) if path.exists() else {'models': []}
    merged = merge(base, read_roster(path), client, allowed,
                   include_twins=(mode == 'none'), available=available)
    replace_json(path, merged)
    return merged


def _same(old, new, key):
    if key == 'supported_reasoning_levels':
        return ([e['effort'] for e in old.get(key, [])]
                == [e['effort'] for e in new.get(key, [])])
    return old.get(key) == new.get(key)


def check(path, client='codex', allowed=None, include_twins=False,
          available=None):
    catalog = json.loads(Path(path).read_text())
    existing = {m['slug']: m for m in catalog.get('models', [])}
    for slug, row in existing.items():
        missing = subscription_stub(slug).keys() - row.keys()
        if missing:
            print(f'{slug}: missing schema fields: {", ".join(sorted(missing))}')
            return False
        template = (row.get('model_messages') or {}).get('instructions_template') or ''
        if SUBAGENT_MODEL_PLACEHOLDER in template:
            print(f'{slug}: unrendered model roster placeholder')
            return False
    visible, hidden = _visible_rows(client, allowed, include_twins,
                                        available=available)
    identical, total = 0, 0
    for model in hidden:
        if model.slug in existing:
            print(f'{model.slug}: hidden from the {client} picker but present')
            return False
    instructions = instructions_for(visible, client)
    sub_instructions = instructions_for(visible, client,
                                        base=SUBSCRIBER_INSTRUCTIONS)
    for slug in SUBSCRIPTION_SLUGS:
        row = existing.get(slug) or {}
        if is_routed_text((row.get('model_messages') or {}).get('instructions_template')):
            print(f'{slug}: subscription row carries the routed instructions')
            return False
    for model in visible:
        total += 1
        old = existing.get(model.slug)
        if old is None:
            print(f'{model.slug}: missing from catalogue')
            continue
        new = external_entry(model, instructions)
        diff = [k for k in set(old) | set(new) if not _same(old, new, k)]
        if diff:
            print(f'{model.slug}: differs in {", ".join(sorted(diff))}')
        else:
            identical += 1
    print(f'identical: {identical} entries')
    return identical == total


def _take_set(args, flag):
    # Optional comma flag for tool/CI pins; (ids-or-None, rest).
    if args[:1] != [flag]:
        return None, args
    if len(args) < 2 or not args[1].strip():
        raise SystemExit(USAGE)
    return (frozenset(s.strip() for s in args[1].split(',') if s.strip()),
            args[2:])


USAGE = ('usage: python3.14 -m ai_router.catalogue '
         '[--client codex|claude] [--allowed slug,...] [--available slug,...] '
         '--check|--merge <catalogue>')


if __name__ == '__main__':
    args = sys.argv[1:]
    client = 'codex'
    if args[:1] == ['--client']:
        if len(args) < 2 or args[1] not in client_ids():
            raise SystemExit(USAGE)
        client = args[1]
        args = args[2:]
    # Tool/CI-only pins; never widen the stored file policy at runtime.
    allowed, args = _take_set(args, '--allowed')
    available, args = _take_set(args, '--available')
    if args[:1] == ['--merge'] and len(args) == 2:
        merged = merge_file(Path(args[1]), client, allowed, available=available)
        print(f'rows={len(merged.get("models", []))} bytes={Path(args[1]).stat().st_size}')
    elif args[:1] == ['--check'] and len(args) == 2:
        sys.exit(0 if check(args[1], client, allowed,
                            include_twins=read_openai_mode(args[1]) == 'none',
                            available=available) else 1)
    else:
        raise SystemExit(USAGE)
