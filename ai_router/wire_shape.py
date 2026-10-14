"""Content-free shape of a prepared Responses body, and the learnt contract.

`CONTRACT` holds each upstream acceptance rule as data, a row's comment
naming what taught it (a dated refusal, a release or a design rule);
`violations` checks a wire payload against the rules its dialect
binds. `pair_problems` is the one pairing rule set, shared with the test fake
that checks every external body. `fingerprint` reduces a sent body to the
names and counts a refusal log line carries. All of it only observes:
enforcing a rule is a separate, evidence-backed change, and no item text,
argument, description, id or tool name leaves this module.
"""
import io
import json
import re
from collections import Counter
from compression import zstd

from . import provider_defs

# Client-run calls that expect an output, by item type.
# ponytail: no local_shell family; add it once a real turn shows how it pairs.
_CALLS = {'function_call': 'function', 'custom_tool_call': 'custom_tool',
          'apply_patch_call': 'apply_patch', 'computer_call': 'computer',
          'tool_search_call': 'tool_search'}
_OUTPUTS = {'function_call_output': 'function',
            'custom_tool_call_output': 'custom_tool',
            'apply_patch_call_output': 'apply_patch',
            'computer_call_output': 'computer',
            'tool_search_output': 'tool_search'}
_FIELD_NAME = re.compile(r'[A-Za-z0-9_.-]{1,40}')
_MAX_FIELD_NAMES = 32
_MAX_UNKNOWN_NAMES = 8
_ZSTD_MAGIC = b'\x28\xb5\x2f\xfd'
# Mirror rejected_repair.ZSTD_DECODE_LIMIT (transport.MAX_REQUEST_BYTES) and
# compaction.PREFIX without their import graphs; unit tests pin both.
DECODE_LIMIT = 256 * 1024 * 1024
_ROUTER_BLOB = 'ocx1:'

VIOLATION, WARNING = 'violations', 'warnings'
_SUBSCRIPTION = (provider_defs.DIALECT_OPENAI,)
_EXTERNAL = provider_defs.EXTERNAL_DIALECTS
_BOTH = _SUBSCRIPTION + _EXTERNAL
# rule id: (level, the dialects it binds). Observed only: promoting a warning
# or enforcing a rule needs its own evidence.
CONTRACT = {
    'pair.family_mismatch': (VIOLATION, _BOTH),  # 13 and 23 Sep refusals
    'pair.orphan_output': (VIOLATION, _BOTH),  # 400s the turn (fragment scrub)
    'pair.orphan_call': (WARNING, _BOTH),  # 13 Sep "has no tool response"
    'pair.duplicate_call_id': (WARNING, _BOTH),  # Jev pins ambiguous ids
    'run.interrupted': (VIOLATION, _EXTERNAL),  # 13 Sep incomplete parallel group
    'pair.namespace_both': (VIOLATION, _EXTERNAL),  # 11 Sep synthetic pair 400
    'output.standalone': (VIOLATION, _EXTERNAL),  # 11 Sep raw standalone 400
    'item.agent_message': (VIOLATION, _EXTERNAL),  # contained before dispatch
    'item.unverified_type': (WARNING, _EXTERNAL),  # outside what 17 Sep measured
    'top_level.forbidden': (VIOLATION, _EXTERNAL),  # ChatGPT-only (0.6.98)
    'top_level.unknown': (WARNING, _BOTH),  # client drift to look at
    'blob.router_owned': (VIOLATION, _SUBSCRIPTION),  # 23 Sep invalid_encrypted_content
    'reasoning.plaintext_content': (VIOLATION, _SUBSCRIPTION),  # 12 Sep array_above_max_length
    'reasoning.id_only': (WARNING, _SUBSCRIPTION),  # 12 Sep unknown-item 404
}
# The pairing rules above, under the names pair_problems reports.
_PAIR_RULES = {'family_mismatch': 'pair.family_mismatch', 'orphan_output': 'pair.orphan_output',
               'orphan_call': 'pair.orphan_call', 'duplicate_call_id': 'pair.duplicate_call_id',
               'interrupted_run': 'run.interrupted', 'namespace_both': 'pair.namespace_both'}
# Common measured types; a captured row may supply further measured shapes.
_VERIFIED_TYPES = frozenset(('message', 'function_call', 'function_call_output', 'reasoning'))
# Codex's 19 Sep first-turn fields (the first twelve), then the fields the
# router sets or knows; only the subscription route may carry the last two.
_KNOWN_TOP_LEVEL = frozenset((
    'model', 'input', 'instructions', 'tools', 'tool_choice', 'parallel_tool_calls', 'reasoning',
    'stream', 'store', 'include', 'prompt_cache_key', 'client_metadata', 'max_output_tokens',
    'text', 'provider', 'metadata', 'user', 'safety_identifier', 'truncation', 'background',
    'top_logprobs', 'stream_options', 'prompt_cache_options', 'service_tier', 'access_programs'))
_FORBIDDEN_TOP_LEVEL = frozenset(('access_programs', 'service_tier'))


def _kind(item):
    """The item's name-shaped type; an item with no type and a role is a message."""
    if not isinstance(item, dict):
        return 'unknown'
    kind = item.get('type', 'message' if 'role' in item else None)
    return kind if isinstance(kind, str) and _FIELD_NAME.fullmatch(kind) else 'unknown'


def _reasoning_shape(item):
    """The most telling part a reasoning item carries; never its value."""
    if item.get('encrypted_content'):
        return 'blob'
    if item.get('content'):
        return 'content'
    return 'summary' if item.get('summary') else 'bare'


def _switch_marker(item):
    """True for a developer or system message with a `<model_switch>` block."""
    content = item.get('content') if _kind(item) == 'message' else None
    return (isinstance(content, list) and item.get('role') in ('developer', 'system')
            and any(isinstance(block, dict) and isinstance(block.get('text'), str)
                    and block['text'].lstrip().startswith('<model_switch>')
                    for block in content))


def pair_problems(items):
    """{rule: count} for tool calls and outputs that do not pair; {} when clean.

    Only call and output items with a string `call_id` take part. Reasoning
    may sit inside a run (a parallel group's calls, then their outputs); any
    other item while a call is still open interrupts it.
    """
    problems, calls, open_ids = Counter(), {}, set()
    for item in items:
        kind = _kind(item)
        family = _CALLS.get(kind) or _OUTPUTS.get(kind)
        if family is None:
            if open_ids and kind != 'reasoning':
                problems['interrupted_run'] += 1
            continue
        call_id = item.get('call_id')
        if not isinstance(call_id, str):
            continue
        if kind in _CALLS:
            if call_id in calls:
                problems['duplicate_call_id'] += 1
            else:
                calls[call_id] = item
            open_ids.add(call_id)
        elif call_id not in calls:
            problems['orphan_output'] += 1
        else:
            call = calls[call_id]
            if _CALLS[call['type']] != family:
                problems['family_mismatch'] += 1
            # A pair carrying `namespace` on both halves is refused upstream.
            if 'namespace' in call and 'namespace' in item:
                problems['namespace_both'] += 1
            open_ids.discard(call_id)
    if open_ids:
        problems['orphan_call'] = len(open_ids)
    return dict(problems)


def _item_rules(item, verified):
    """Contract rule ids one input item breaks, before any dialect applies."""
    kind = _kind(item)
    if kind not in verified:
        yield 'item.unverified_type'
    if not isinstance(item, dict):
        return
    if kind == 'agent_message':
        yield 'item.agent_message'
    if kind in _OUTPUTS and not isinstance(item.get('call_id'), str):
        yield 'output.standalone'
    blob = item.get('encrypted_content')
    if isinstance(blob, str) and blob.startswith(_ROUTER_BLOB):
        yield 'blob.router_owned'
    if kind == 'reasoning' and item.get('content'):
        yield 'reasoning.plaintext_content'
    elif kind == 'reasoning' and not blob:
        yield 'reasoning.id_only'


def violations(dialect, payload, observed_types=()):
    """The CONTRACT rules a wire payload breaks, for the dialect it goes to.

    {'violations': {rule: count}, 'warnings': {rule: count},
    'unknown_top_level': [names]}, all empty for a clean or non-object
    payload or a dialect no rule binds (Messages, None). At most eight
    name-shaped unknown fields are listed; the warning counts them all.
    `observed_types` is the captured row's measured profile, never inferred
    from its name. An absent measurement is unknown, not a refusal.
    Never raises on decoded JSON and a validated profile.
    """
    found = {VIOLATION: {}, WARNING: {}, 'unknown_top_level': []}
    if dialect not in _BOTH or not isinstance(payload, dict):
        return found
    items = payload.get('input')
    items = items if isinstance(items, list) else []
    verified = _VERIFIED_TYPES | frozenset(observed_types)
    hits = Counter({_PAIR_RULES[name]: n for name, n in pair_problems(items).items()})
    hits.update(rule for item in items for rule in _item_rules(item, verified))
    unknown = sorted(key for key in payload if key not in _KNOWN_TOP_LEVEL)
    hits['top_level.unknown'] = len(unknown)
    hits['top_level.forbidden'] = len(payload.keys() & _FORBIDDEN_TOP_LEVEL)
    for rule, count in hits.items():
        level, dialects = CONTRACT[rule]
        if count and dialect in dialects:
            found[level][rule] = count
    found['unknown_top_level'] = [key for key in unknown
                                  if _FIELD_NAME.fullmatch(key)][:_MAX_UNKNOWN_NAMES]
    return found


def decode_wire(body):
    """The JSON object an identity or zstd wire body carries; None on any failure."""
    if not isinstance(body, (bytes, str)):
        return None
    try:
        if isinstance(body, bytes) and body.startswith(_ZSTD_MAGIC):
            with zstd.ZstdFile(io.BytesIO(body)) as stream:
                body = stream.read(DECODE_LIMIT + 1)
            if len(body) > DECODE_LIMIT:
                return None
        payload = json.loads(body)
    except (OSError, EOFError, ValueError, RecursionError, zstd.ZstdError):
        return None
    return payload if isinstance(payload, dict) else None


def fingerprint(body, dialect=None, observed_types=()):
    """Names and counts from a prepared Responses body; never content.

    {} unless `body` decodes to an object with an `input` list, so a Messages
    body yields nothing. Otherwise the `items`, `item_kinds` and `tools`
    counts and the bounded `top_level_keys`, then, each only when non-empty
    or true: `reasoning_shapes`, `pair_problems`, the dialect's other CONTRACT
    hits as `contract_violations` and `contract_warnings` (pairing counts stay
    under `pair_problems` alone, so a line never reports them twice), and
    `switch_marker`. These keys join the refusal log line beside the request
    metrics, so none may share a metrics field name. Never raises.
    """
    payload = decode_wire(body) or {}
    items = payload.get('input')
    if not isinstance(items, list):
        return {}
    tools = payload.get('tools')
    shape = {'items': len(items), 'item_kinds': dict(Counter(map(_kind, items))),
             'tools': len(tools) if isinstance(tools, list) else 0,
             'top_level_keys': sorted(key for key in payload
                                      if _FIELD_NAME.fullmatch(key))[:_MAX_FIELD_NAMES]}
    reasoning = Counter(_reasoning_shape(item) for item in items
                        if _kind(item) == 'reasoning')
    if reasoning:
        shape['reasoning_shapes'] = dict(reasoning)
    problems = pair_problems(items)
    if problems:
        shape['pair_problems'] = problems
    found = violations(dialect, payload, observed_types)
    for key, level in (('contract_violations', VIOLATION), ('contract_warnings', WARNING)):
        rules = {rule: count for rule, count in found[level].items()
                 if rule not in _PAIR_RULES.values()}
        if rules:
            shape[key] = rules
    if any(map(_switch_marker, items)):
        shape['switch_marker'] = True
    return shape
