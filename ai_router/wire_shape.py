"""Content-free shape of a prepared Responses body.

`fingerprint` reduces the body the router sent upstream to the names and
counts a provider-refusal log line carries: item kinds, top-level field
names, reasoning item shapes and broken tool call/output pairing.
`pair_problems` is the one pairing rule set, shared with the test fake that
checks every external body. Both only observe: nothing here changes a
request, and no item text, argument, description, id or tool name leaves
this module.
"""
import json
import re
from collections import Counter

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


def _kind(item):
    kind = item.get('type') if isinstance(item, dict) else None
    return kind if isinstance(kind, str) else 'unknown'


def _reasoning_shape(item):
    """The most telling part a reasoning item carries; never its value."""
    if item.get('encrypted_content'):
        return 'blob'
    if item.get('content'):
        return 'content'
    return 'summary' if item.get('summary') else 'bare'


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


def fingerprint(body):
    """Names and counts from a prepared Responses body; never content.

    {} unless `body` is JSON text (bytes or str) holding an object with an
    `input` list, so a Messages or compressed body yields nothing. Otherwise
    the `items`, `item_kinds` and `tools` counts, the bounded
    `top_level_keys`, and `reasoning_shapes` and `pair_problems` when either
    is non-empty. These keys join the refusal log line beside the request
    metrics, so none may share a metrics field name. Never raises.
    """
    if not isinstance(body, (bytes, str)):
        return {}
    try:
        payload = json.loads(body)
    except (ValueError, RecursionError):
        return {}
    items = payload.get('input') if isinstance(payload, dict) else None
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
    return shape
