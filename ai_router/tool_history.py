"""Rewrite external tool history to match this turn's declared tools (Plan 183).

`tool_adapter.prepare_tools` shapes the declarations and returns the two maps
read here; `outbound` runs this stage right after it. The order is fixed:
custom pairs, discovery listings, the item loop, then the model-switch
boundary. The history mode is the request's captured row value, never a lookup.
"""
import json

from . import tool_aliases, tool_merge
from .history_portability import portable_history, rewrite_custom_pairs
from .tool_merge import tool_entries

SEARCH_NAME = 'codex_client_tool_search'
SEARCH_NEXT = 'Call the exact returned name; do not search again.'
# Deliberately terse: this replaces a repeated listing, so every byte here is
# charged 2,690 times on the thread this exists for.
SEARCH_REPEAT_NOTE = 'repeated search result omitted'


def tool_key(item):
    return (item.get('namespace'), item.get('name'))


def _replace(item, drop, **values):
    """A copy of `item` without `drop`, then `values`, keeping key order."""
    copy = {key: value for key, value in item.items() if key not in drop}
    copy.update(values)
    return copy


def rewrite_tool_history(payload, names, wire_names, history_mode):
    """The payload with its history renamed for this turn; items are copied, never edited."""
    if not isinstance(payload.get('input'), list):
        return payload
    exposed_keys = {tool_merge.key_of(tool, namespace)
                    for tool, namespace in tool_entries(payload.get('tools', []))}
    exposed_keys.update(key for key, wire in wire_names.items() if (None, wire) in names)
    items = rewrite_custom_pairs(payload['input'], exposed_keys, wire_names)
    # Newest listing per tool key wins; an earlier repeat gets the note below.
    latest_search, listings = tool_merge.newest_listings(items, wire_names)
    rewritten = []
    for item in items:
        if item.get('type') == 'tool_search_call':
            item = _replace(item, ('execution',), type='function_call', name=SEARCH_NAME,
                            arguments=json.dumps(item['arguments']))
        elif item.get('type') == 'tool_search_output':
            entries = listings[id(item)]
            found = {'available_tools': entries or [SEARCH_REPEAT_NOTE]}
            if item is latest_search and entries:
                found['how_to_use'] = SEARCH_NEXT
            item = _replace(item, ('execution', 'status', 'tools'),
                            type='function_call_output', output=json.dumps(found))
        elif item.get('type') == 'function_call':
            wire = wire_names.get(tool_key(item))
            if wire:
                item = _replace(item, ('namespace',), name=wire)
            entry = names.get(tool_key(item))
            kind = entry.get('kind') if isinstance(entry, dict) else entry
            if kind in ('json_text', 'json_text_root'):
                item = {**item, 'arguments': json.dumps({'arguments_json': item['arguments']})}
        elif item.get('type') == 'function_call_output' and isinstance(item.get('output'), str):
            output = tool_aliases.annotate(item['output'], names)
            if output is not item['output']:
                item = {**item, 'output': output}
        rewritten.append(item)
    return {**payload, 'input': portable_history(rewritten, SEARCH_NAME, history_mode)}
