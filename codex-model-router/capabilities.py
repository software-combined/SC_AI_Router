"""Single source for OpenRouter model capabilities.

Native OpenAI entries keep their catalogue values (multi-agent v2,
encrypted history, code_mode_only). OpenRouter entries use the proven
trial values: plaintext V1 subagents, no forced-compaction hash, Node
REPL offered, and image input only where live metadata advertises it.
GLM 5.3 is text-only per live metadata. Contributor rejects max despite
advertising it; Grok has no max/minimal. Defaults stay low.
"""
OPENROUTER_MODELS = frozenset({
    'meta/muse-spark-1.3', 'meta/muse-spark-1.3-contributor',
    'z-ai/glm-5.3-flash', 'z-ai/glm-5.3', 'moonshotai/kimi-k3',
    '~x-ai/grok-latest',
})
# ponytail: fixed map, live recheck via update_reasoning_catalog.py
# GLM 5.3 is the only text-only model per live metadata.
IMAGE_INPUT_MODELS = OPENROUTER_MODELS - {'z-ai/glm-5.3'}
# Live-advertised efforts proven UNSUPPORTED and excluded from catalogues.
EXCLUDED_EFFORTS = {
    'meta/muse-spark-1.3-contributor': {'max'},
}
EFFORT_DESCRIPTIONS = {'xhigh': 'Extra high reasoning', 'max': 'Maximum reasoning'}
CANONICAL_ORDER = ['minimal', 'low', 'medium', 'high', 'xhigh', 'max']
# Last-known-good levels; fallback when live metadata lacks a model.
REASONING_LEVELS = {
    'meta/muse-spark-1.3': ['minimal', 'low', 'medium', 'high', 'xhigh', 'max'],
    'meta/muse-spark-1.3-contributor': ['minimal', 'low', 'medium', 'high', 'xhigh'],
    'z-ai/glm-5.3-flash': ['low', 'high', 'max'],
    'z-ai/glm-5.3': ['low', 'high', 'max'],
    'moonshotai/kimi-k3': ['low', 'high', 'max'],
    '~x-ai/grok-latest': ['low', 'medium', 'high', 'xhigh'],
}
MULTI_AGENT_VERSION = 'v1'
NODE_REPL_DISABLED = False
COMP_HASH = None

def input_modalities(slug):
    return ['text', 'image'] if slug in IMAGE_INPUT_MODELS else ['text']

def reasoning_levels(slug):
    return list(REASONING_LEVELS[slug])

def live_levels(slug, advertised):
    return [lv for lv in advertised if lv not in EXCLUDED_EFFORTS.get(slug, ())]

def describe(level):
    return EFFORT_DESCRIPTIONS.get(level, level.title() + ' reasoning')

OPENROUTER_HOST = 'openrouter.ai'

def advertised_or_pinned(slug, entry):
    return entry or REASONING_LEVELS.get(slug, [])

def checked_level_entries(slug, advertised, default):
    kept = [lv for lv in CANONICAL_ORDER if lv in live_levels(slug, advertised)]
    if not kept or default not in kept:
        raise ValueError('Unsupported reasoning levels for ' + slug)
    return [{'effort': level, 'description': describe(level)} for level in kept]

def catalogue_patch(slug):
    if slug not in OPENROUTER_MODELS or slug not in REASONING_LEVELS:
        raise KeyError('Unknown OpenRouter model: ' + slug)
    return {
        'multi_agent_version': MULTI_AGENT_VERSION,
        'multi_agent_reasoning_effort': None,
        'node_repl_disabled': NODE_REPL_DISABLED,
        'node_repl_auto_review_required': False,
        'comp_hash': COMP_HASH,
        'input_modalities': input_modalities(slug),
    }
