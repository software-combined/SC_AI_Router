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


def rewrite_tool_history(payload, names, wire_names, history_mode):
    items = payload.get('input', []) if isinstance(payload.get('input'), list) else []
    exposed_keys = {tool_merge.key_of(tool, namespace)
                    for tool, namespace in tool_entries(payload.get('tools', []))}
    exposed_keys.update(key for key, wire in wire_names.items() if (None, wire) in names)
    rewrite_custom_pairs(items, exposed_keys, wire_names)
    # Newest listing per tool key wins; an earlier repeat gets the note below.
    latest_search, listings = tool_merge.newest_listings(items, wire_names)
    for item in items:
        if item.get('type') == 'tool_search_call':
            item.pop('execution', None)
            item.update(type='function_call', name=SEARCH_NAME, arguments=json.dumps(item['arguments']))
        elif item.get('type') == 'tool_search_output':
            item.pop('execution', None)
            item.pop('status', None)
            item.pop('tools', None)
            entries = listings[id(item)]
            found = {'available_tools': entries or [SEARCH_REPEAT_NOTE]}
            if item is latest_search and entries:
                found['how_to_use'] = SEARCH_NEXT
            item.update(type='function_call_output', output=json.dumps(found))
        elif item.get('type') == 'function_call':
            wire = wire_names.get(tool_key(item))
            if wire:
                item.pop('namespace', None)
                item['name'] = wire
            entry = names.get(tool_key(item))
            kind = entry.get('kind') if isinstance(entry, dict) else entry
            if kind in ('json_text', 'json_text_root'):
                item['arguments'] = json.dumps({'arguments_json': item['arguments']})
        elif item.get('type') == 'function_call_output' and isinstance(item.get('output'), str):
            item['output'] = tool_aliases.annotate(item['output'], names)
    if isinstance(payload.get('input'), list):
        payload['input'] = portable_history(payload['input'], SEARCH_NAME, history_mode)
