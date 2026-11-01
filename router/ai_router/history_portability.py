"""Portable history for model-switched threads (Plan 168 split).

Owns the `<model_switch>` boundary rule: items before the client's last
marker were produced under another model and get the portable treatment
(discovery pair collapses to a note, reasoning never rides along); items
after it are the current model's and replay natively. A `portable` row
rewrites the whole history. Never splits a tool run across the boundary.
"""
import json

from .history_items import (CALL_TYPES, OUTPUT_TYPES, TOOL_RUN_TYPES, summary_text,
                            user_message_item)

PORTABLE_SEARCH_NOTE = ('[tool search result replayed as declared tools; '
                        'the search call itself is omitted on this model]')
PORTABLE_REASONING_NOTE = '[reasoning summary from the previous model] '


def rewrite_custom_pairs(items, exposed_keys, wire_names):
    """Keep custom call/output pairs symmetric on the external wire.

    A pair whose tool this turn exposes converts to matched function-call
    items; an undeclared pair stays matched custom items. One converted side
    alone is the mixed shape strict providers refuse. Returns a new list;
    converted items are copies, so the client's history is never edited.
    """
    calls = {item.get('call_id'): (item.get('namespace'), item.get('name'))
             for item in items
             if isinstance(item, dict) and item.get('type') == 'custom_tool_call'
             and isinstance(item.get('call_id'), str)}
    rewritten = []
    for item in items:
        kind = item.get('type') if isinstance(item, dict) else None
        if kind == 'custom_tool_call':
            key = (item.get('namespace'), item.get('name'))
        elif kind == 'custom_tool_call_output':
            key = calls.get(item.get('call_id'),
                            (item.get('namespace'), item.get('name')))
        if kind not in ('custom_tool_call', 'custom_tool_call_output') or key not in exposed_keys:
            rewritten.append(item)
            continue
        if kind == 'custom_tool_call':
            item = {**item, 'type': 'function_call'}
            item['arguments'] = json.dumps({'input': item.pop('input')})
        else:
            item = {**item, 'type': 'function_call_output'}
        wire = wire_names.get(key)
        if wire:
            item.pop('namespace', None)
            item['name'] = wire
        rewritten.append(item)
    return rewritten


def marker_texts(item, tag):
    """Texts of a client `developer` or `system` message that open with `tag`.

    String content or any text block counts once leading whitespace is
    dropped, so a marker the client moves still reads as one; the tag later
    in a text is quoted data. `context_recovery` shares this rule.
    """
    if not isinstance(item, dict) or item.get('role') not in ('developer', 'system'):
        return []
    content = item.get('content')
    blocks = content if isinstance(content, list) else [{'text': content}]
    texts = [block['text'].lstrip() for block in blocks
             if isinstance(block, dict) and isinstance(block.get('text'), str)]
    return [text for text in texts if text.startswith(tag)]


def _switch_boundary(items):
    """Index of the client's last `<model_switch>` marker, else None.

    The marker is the message Codex records when the thread changes model
    (Codex 0.155: a developer message with one text block); it stays in
    history and sits in chronological order, so everything before the last
    one was produced under another model. It names no model.
    """
    boundary = None
    for index, item in enumerate(items):
        if marker_texts(item, '<model_switch>'):
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
            note = summary_text(item)
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
