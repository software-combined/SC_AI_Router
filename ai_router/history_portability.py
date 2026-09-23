"""Portable history for model-switched threads (Plan 168 split).

Leaf for the `<model_switch>` boundary rule: items before the client's last
marker were produced under another model and get the portable treatment
(discovery pair collapses to a note, reasoning never rides along); items
after it are the current model's and replay natively. A `portable` row
rewrites the whole history. Never splits a tool run across the boundary.
"""
import json


def _block_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return ' '.join(b.get('text', '') for b in content
            if isinstance(b, dict) and isinstance(b.get('text'), str))
    return str(content) if content else ''


def user_message_item(text):
    return {'type': 'message', 'role': 'user',
            'content': [{'type': 'input_text', 'text': text}]}




PORTABLE_SEARCH_NOTE = ('[tool search result replayed as declared tools; '
                        'the search call itself is omitted on this model]')
PORTABLE_REASONING_NOTE = '[reasoning summary from the previous model] '
CALL_TYPES = frozenset({'function_call', 'custom_tool_call', 'apply_patch_call',
                        'web_search_call', 'file_search_call', 'image_generation_call',
                        'code_interpreter_call', 'computer_call'})
OUTPUT_TYPES = frozenset({'function_call_output', 'custom_tool_call_output',
                          'apply_patch_call_output'})
# A tool run is the call/output block of one assistant step. Nothing may be
# inserted inside it: a note between a parallel call and its output makes a
# strict upstream refuse the whole turn ("incomplete parallel tool-call
# group", measured on deepseek/deepseek-v4.1-flash 2026-09-13). The discovery
# pair keeps its names here because the portable pass may run on either side
# of the adapter rewrite that turns it into a plain function call.
TOOL_RUN_TYPES = CALL_TYPES | OUTPUT_TYPES | {'tool_search_call', 'tool_search_output'}


def rewrite_custom_pairs(items, exposed_keys, wire_names):
    """Keep custom call/output pairs symmetric on the external wire.

    A pair whose tool this turn exposes converts to matched function-call
    items; an undeclared pair stays matched custom items. One converted side
    alone is the mixed shape strict providers refuse.
    """
    calls = {item.get('call_id'): (item.get('namespace'), item.get('name'))
             for item in items
             if isinstance(item, dict) and item.get('type') == 'custom_tool_call'
             and isinstance(item.get('call_id'), str)}
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = item.get('type')
        if kind == 'custom_tool_call':
            key = (item.get('namespace'), item.get('name'))
            if key not in exposed_keys:
                continue
            item['type'] = 'function_call'
            item['arguments'] = json.dumps({'input': item.pop('input')})
        elif kind == 'custom_tool_call_output':
            key = calls.get(item.get('call_id'),
                            (item.get('namespace'), item.get('name')))
            if key not in exposed_keys:
                continue
            item['type'] = 'function_call_output'
        else:
            continue
        wire = wire_names.get(key)
        if wire:
            item.pop('namespace', None)
            item['name'] = wire


def _summary_text(item):
    """Readable summary text only; a provider blob value is never read."""
    blocks = item.get('summary')
    if not isinstance(blocks, (str, list)):
        return ''
    return _block_text(blocks).strip()


def _switch_boundary(items):
    """Index of the client's last `<model_switch>` marker, else None.

    The marker is the developer message Codex records when the thread
    changes model; it stays in history and sits in chronological order, so
    everything before the last one was produced under another model.
    """
    boundary = None
    for index, item in enumerate(items):
        if not isinstance(item, dict) or item.get('role') != 'developer':
            continue
        content = item.get('content')
        first = content[0] if isinstance(content, list) and content else None
        text = first.get('text') if isinstance(first, dict) else None
        if isinstance(text, str) and text.strip().startswith('<model_switch>'):
            boundary = index
    return boundary


def _run_start(items, boundary):
    """Move the boundary back past any tool run it would split.

    A call item before the boundary whose output mate (same call_id) sits
    at or after it means the marker landed inside a tool run; the whole
    run replays natively so a call is never dropped while its output
    rides through. Scans to the run's first call, not just the nearest:
    an earlier parallel call (including a discovery call) with its mate
    on the native side belongs to the same run.
    """
    after = {item.get('call_id') for item in items[boundary:]
             if isinstance(item, dict)
             and item.get('type') in OUTPUT_TYPES | {'tool_search_output'}
             and item.get('call_id')}
    if not after:
        return boundary
    start = boundary
    for index in range(boundary - 1, -1, -1):
        item = items[index]
        if (isinstance(item, dict)
                and item.get('type') in CALL_TYPES | {'tool_search_call'}
                and item.get('call_id') in after):
            start = index
    return start


def portable_history(items, search_name, history_mode):
    """History a model switch cannot carry: the discovery pair and reasoning.

    Trigger: `history_mode == 'portable'` (the caller's registry quirk)
    or the client's `<model_switch>` marker. In that mode the search
    call/output matched by call_id collapses into one visible note; a
    half without its mate falls away so no orphan rides along, and
    discovery outputs ride nameless from the rewrite loop, so they join
    by call_id. A provider-scoped reasoning item never rides along: an
    upstream that did not produce it refuses the whole turn (Meta answers
    a carried reasoning item with a bare HTTP 400, measured 2026-09-12),
    so one with a readable summary replays as that visible note and one
    without is dropped.
    Released schemas stay declared in payload['tools']; every other item
    passes through.
    """
    if not isinstance(items, list):
        return items
    if history_mode == 'portable':
        foreign, native = items, []
    else:
        boundary = _switch_boundary(items)
        if boundary is None:
            return items
        boundary = _run_start(items, boundary)
        foreign, native = items[:boundary], items[boundary:]
    calls = {item.get('call_id') for item in foreign
             if isinstance(item, dict) and item.get('type') == 'function_call'
             and item.get('name') == search_name and item.get('call_id')}
    matched = calls & {item.get('call_id') for item in foreign
                       if isinstance(item, dict)
                       and item.get('type') == 'function_call_output'
                       and (item.get('name') == search_name
                            or not item.get('name'))}
    out, noted, pending, in_run = [], False, [], False

    def emit(note):
        """Replace in place, unless a tool run is open: then it waits."""
        if in_run:
            pending.append(note)
        else:
            out.append(note)

    def close_run():
        nonlocal in_run
        in_run = False
        out.extend(pending)
        pending.clear()

    for item in foreign:
        if not isinstance(item, dict):
            close_run()
            out.append(item)
            continue
        kind, name, call_id = item.get('type'), item.get('name'), item.get('call_id')
        if kind == 'reasoning':
            note = _summary_text(item)
            if note:
                emit(user_message_item(PORTABLE_REASONING_NOTE + note[:2000]))
            continue
        discovery = ((kind == 'function_call' and name == search_name)
                     or (kind == 'function_call_output'
                         and (name == search_name or (not name and call_id in calls))))
        if discovery:
            if call_id in matched and not noted:
                emit(user_message_item(PORTABLE_SEARCH_NOTE))
                noted = True
            # Unmatched halves and repeat matches fall away here.
        elif kind in TOOL_RUN_TYPES:
            in_run = True
            out.append(item)
        else:
            close_run()
            out.append(item)
    close_run()
    return out + native
