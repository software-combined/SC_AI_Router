"""Single source for external-provider model capabilities.

Native OpenAI entries keep their catalogue values (multi-agent v2,
encrypted history, code_mode_only). Externally billed entries use the
proven trial values: plaintext V1 subagents, no forced-compaction hash,
Node REPL offered, and image input only where live metadata advertises it.
GLM 5.3 and the DeepSeek v4 text models are text-only per live metadata. Contributor rejects max despite
advertising it; Grok has no max/minimal. Defaults stay low.

`EXTERNAL_MODELS` is every slug routed to an external provider's own key,
whatever that provider is; upstream facts live in provider_defs.py.
"""
from .image_items import has_images
from .registry import MODELS, external_slugs
EXTERNAL_MODELS = frozenset()
IMAGE_INPUT_MODELS = frozenset()
EXCLUDED_EFFORTS = {}
REASONING_LEVELS = {}
EFFORT_DESCRIPTIONS = {'none': 'No reasoning', 'xhigh': 'Extra high reasoning', 'max': 'Maximum reasoning'}
CANONICAL_ORDER = ['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max']
MULTI_AGENT_VERSION = 'v1'
NODE_REPL_DISABLED = False
COMP_HASH = None


def rebuild(models):
    """Refresh the maps derived from one registry snapshot (Plan 125).

    The caller swaps registry.MODELS first (model_refresh.apply), so
    external_slugs() reads that same snapshot; the import-time call below
    seeds the maps for the shipped registry.
    """
    global EXTERNAL_MODELS, IMAGE_INPUT_MODELS, EXCLUDED_EFFORTS, REASONING_LEVELS
    EXTERNAL_MODELS = external_slugs()
    IMAGE_INPUT_MODELS = frozenset(m.slug for m in models if 'image' in m.modalities)
    EXCLUDED_EFFORTS = {m.slug: set(m.excluded_efforts) for m in models if m.excluded_efforts}
    REASONING_LEVELS = {m.slug: list(m.reasoning) for m in models}


rebuild(MODELS)

def input_modalities(slug):
    return ['text', 'image'] if slug in IMAGE_INPUT_MODELS else ['text']

def reasoning_levels(slug):
    return list(REASONING_LEVELS[slug])

def live_levels(slug, advertised):
    return [lv for lv in advertised if lv not in EXCLUDED_EFFORTS.get(slug, ())]

def describe(level):
    return EFFORT_DESCRIPTIONS.get(level, level.title() + ' reasoning')

def has_recursive_refs(schema):
    def walk(value, refs=()):
        if isinstance(value, list):
            return any(walk(item, refs) for item in value)
        if not isinstance(value, dict):
            return False
        ref = value.get('$ref')
        if isinstance(ref, str) and ref.startswith('#'):
            if ref in refs:
                return True
            target = schema
            for segment in ref[2:].split('/') if ref != '#' else []:
                target = target[segment.replace('~1', '/').replace('~0', '~')]
            if walk(target, refs + (ref,)):
                return True
        return any(walk(item, refs) for key, item in value.items() if key not in ('$defs', 'definitions', '$ref'))
    return walk(schema)

def advertised_or_pinned(slug, entry):
    return entry or REASONING_LEVELS.get(slug, [])

def checked_level_entries(slug, advertised, default):
    kept = [lv for lv in CANONICAL_ORDER if lv in live_levels(slug, advertised)]
    if not kept or default not in kept:
        raise ValueError('Unsupported reasoning levels for ' + slug)
    return [{'effort': level, 'description': describe(level)} for level in kept]

def check_effort(slug, effort):
    """Fail closed when a routed model is asked for an unsupported effort.

    Mid-thread model switches carry the old thread effort over, so a
    Kimi-at-max thread switching to Contributor must be rejected with a
    clear message instead of an opaque upstream 400. Unknown shapes pass
    through untouched; only a known-bad combination raises.
    """
    if effort is None or slug not in EXTERNAL_MODELS:
        return
    levels = REASONING_LEVELS[slug]
    if effort not in levels:
        raise ValueError(
            slug + ' does not support reasoning effort ' + repr(effort)
            + '; use one of ' + ', '.join(levels)
            + ' (change effort before switching models).')


def current_user_message(items):
    """The message the user is sending now: the last user-role message.

    Codex appends the new user message after history; a trailing
    `compaction_trigger` or developer item may follow it, so search from
    the end. None when no user message is present.
    """
    if not isinstance(items, list):
        return None
    for item in reversed(items):
        if (isinstance(item, dict) and item.get('type') == 'message'
                and item.get('role') == 'user'):
            return item
    return None


def check_images(slug, items):
    """Fail closed when a text-only model is asked to read image blocks.

    Only the message the user is sending now can carry a new image; images
    earlier in history are noted on the wire instead of refusing the turn
    (Plan 174). Unknown shapes pass through untouched; only a known-bad
    combination raises.
    """
    if not isinstance(slug, str) or slug not in EXTERNAL_MODELS:
        return
    if 'image' not in input_modalities(slug) and has_images(current_user_message(items)):
        raise ValueError(
            slug + ' does not accept image input, but this message carries image blocks'
            + ' (resend this message without images).')


def catalogue_patch(slug):
    if slug not in EXTERNAL_MODELS:
        raise KeyError('Unknown external model: ' + slug)
    return {
        'multi_agent_version': MULTI_AGENT_VERSION,
        'multi_agent_reasoning_effort': None,
        'node_repl_disabled': NODE_REPL_DISABLED,
        'node_repl_auto_review_required': False,
        'comp_hash': COMP_HASH,
        'input_modalities': input_modalities(slug),
    }
