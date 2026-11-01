"""One pairing and run model for replayed tool history (Plan 183).

A tool call and its output share a `call_id`. `pairs` and `open_calls` read
that relation in item order, and `scrub_tool_fragments` drops the fragments a
strict upstream refuses. Only the shared vocabulary is imported, so every
outbound stage can build on this without an import cycle.
"""
from .history_items import CALL_TYPES, OUTPUT_TYPES

_CALLS = CALL_TYPES | {'tool_search_call'}
_OUTPUTS = OUTPUT_TYPES | {'tool_search_output'}


def _walk(items):
    """(answered, waiting), keyed by call id.

    In item order a call opens its string `call_id` unless that id is already
    open, and the next output with that id answers it. An output with no open
    call answers nothing, and an id keeps its first answered call.
    """
    answered, waiting = {}, {}
    for index, item in enumerate(items if isinstance(items, list) else ()):
        kind = item.get('type') if isinstance(item, dict) else None
        call_id = item.get('call_id') if kind in _CALLS or kind in _OUTPUTS else None
        if not isinstance(call_id, str):
            continue
        if kind in _CALLS:
            waiting.setdefault(call_id, index)
        elif call_id in waiting:
            answered.setdefault(call_id, (waiting.pop(call_id), index))
    return answered, waiting


def pairs(items):
    """{call id: (call index, output index)} for each id a later output answered."""
    return _walk(items)[0]


def open_calls(items):
    """{call id: call index} for each id still open after the last item."""
    return _walk(items)[1]


# Calls the endpoint accepts, and outputs keyed by call. A fragment missing
# these fields (interrupted call, orphan output) 400s the whole turn, so the
# scrub drops fragments before anything is forwarded. A partial call never
# executed, so the next turn regenerates it if still needed. A standalone
# output (no call_id) is the app-injected instruction shape, not an orphan,
# and is never dropped here; providers materialize it before the scrub.
def _call_complete(item):
    kind = item.get('type')
    if kind == 'image_generation_call':
        # A finished image result carries `id`, not `call_id`: completed
        # (or failed) results replay as history, while an in-progress call
        # without either id is still a fragment.
        return (isinstance(item.get('call_id'), str)
                or (isinstance(item.get('id'), str)
                    and item.get('status') in ('completed', 'failed')))
    if not isinstance(item.get('call_id'), str):
        return False
    field = {'function_call': 'arguments', 'custom_tool_call': 'input'}.get(kind)
    if field is not None:
        return isinstance(item.get(field), str)
    if kind == 'apply_patch_call':
        return (item.get('status') in ('in_progress', 'completed')
                and isinstance(item.get('operation'), dict))
    return True


def scrub_tool_fragments(items):
    """Drop incomplete tool history; complete pairs pass through untouched."""
    if not isinstance(items, list):
        return items
    calls = {item.get('call_id') for item in items
             if isinstance(item, dict) and item.get('type') in CALL_TYPES
             and _call_complete(item)}
    out = []
    for item in items:
        if not isinstance(item, dict):
            out.append(item)
            continue
        kind = item.get('type')
        if kind in CALL_TYPES and not _call_complete(item):
            continue
        if (kind in OUTPUT_TYPES and isinstance(item.get('call_id'), str)
                and item['call_id'] not in calls):
            continue
        out.append(item)
    return out
