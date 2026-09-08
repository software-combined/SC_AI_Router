"""Adapt Codex client tool discovery and schemas to JSON function tools.

The native Codex executor still owns tool validation and execution. This adapter
only wraps/unwraps its text input; it never executes tools or changes permissions.
"""
import json
import hashlib
import re
import threading
from copy import deepcopy
from .compaction import SUMMARY_PREFIX, extract_user_messages
from .registry import by_slug
SEARCH_NAME = 'codex_client_tool_search'

def _quirk(payload, name):
    entry = by_slug(payload.get('model', ''))
    return getattr(entry, name, None) if entry else None

def integer_json(text):
    # Meta emits e.g. 8.0 for integer arguments. Rust's integer deserializers
    # reject that spelling. Preserve strings, fractions and large-number precision.
    try:
        json.loads(text)
    except json.JSONDecodeError:
        return text  # Leave malformed arguments for the native validator to reject.
    return re.sub(r'("(?:\\.|[^"\\])*")|(-?\d+)\.0+(?=\s*[,}\]]|\s*$)',
                  lambda match: match[1] if match[1] is not None else match[2], text)

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

def tool_entries(tools, namespace=None):
    for tool in tools:
        if tool.get('type') == 'namespace':
            yield from tool_entries(tool.get('tools', []), tool['name'])
        else:
            yield tool, namespace

def tool_key(item):
    return (item.get('namespace'), item.get('name'))

_DISCOVERED, _DISCOVERED_LOCK, _DISCOVERED_MAX = {}, threading.Lock(), 16  # post-compaction restores; FIFO, lost on restart

def remember_discovered(items, output):
    try:
        text = output[-1]['content'][0]['text']
    except (IndexError, KeyError, TypeError):
        return
    if not isinstance(text, str) or not text.startswith(SUMMARY_PREFIX):
        return
    defs = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and item.get('type') == 'tool_search_output' and isinstance(item.get('tools'), list):
            defs.extend(deepcopy(item['tools']))
    if not defs:
        return
    with _DISCOVERED_LOCK:
        _DISCOVERED[hashlib.sha256(text.encode()).hexdigest()] = defs
        if len(_DISCOVERED) > _DISCOVERED_MAX:
            _DISCOVERED.pop(next(iter(_DISCOVERED)))

def recall_discovered(payload):
    found = []
    with _DISCOVERED_LOCK:
        for text in extract_user_messages(payload.get('input', [])):
            if text.startswith(SUMMARY_PREFIX):
                found.extend(deepcopy(_DISCOVERED.get(hashlib.sha256(text.encode()).hexdigest(), [])))
    return found

def prepare_tools(payload):
    names = {}
    # OpenAI reads discovered definitions from tool_search_output history. Other
    # providers require those released tools in the ordinary request tool list.
    released = []
    for item in payload.get('input', []) if isinstance(payload.get('input'), list) else []:
        if item.get('type') == 'tool_search_output':
            released.extend(deepcopy(item.get('tools', [])))
    released.extend(recall_discovered(payload))
    declared = {}
    for tool, namespace in tool_entries(payload.get('tools', [])):
        declared.setdefault((namespace, tool.get('name')), tool)
    for tool, namespace in tool_entries(released):
        key = (namespace, tool.get('name'))
        existing = declared.get(key)
        if existing is not None:
            # Complete a catalogue stub from the discovered schema; never clobber.
            if existing.get('parameters') is None and tool.get('parameters') is not None:
                existing['parameters'] = tool['parameters']
            continue
        if namespace:
            payload.setdefault('tools', []).append({'type': 'namespace', 'name': namespace, 'description': namespace + ' tools', 'tools': [tool]})
        else:
            payload.setdefault('tools', []).append(tool)
        declared[key] = tool
    for tool, namespace in tool_entries(payload.get('tools', [])):
        if tool.get('type') == 'tool_search':
            tool.pop('execution', None)
            tool.update(type='function', name=SEARCH_NAME, strict=False)
            limit = tool.get('parameters', {}).get('properties', {}).get('limit')
            if isinstance(limit, dict):
                limit.update(type='integer', minimum=1)
            tool['description'] = tool.get('description', '') + '\nSearch using short keywords or an unqualified tool name, not a dotted namespace path. If there are no matches, retry with a shorter query.'
            names[(namespace, tool['name'])] = 'search'
        elif tool.get('type') == 'custom':
            names[(namespace, tool['name'])] = 'custom'
            tool.pop('format', None)
            tool.update(type='function', parameters={'type': 'object',
                'properties': {'input': {'type': 'string', 'description': 'The complete raw tool input.'}},
                'required': ['input'], 'additionalProperties': False}, strict=True)
        elif _quirk(payload, 'schema_mode') == 'json_text' and has_recursive_refs(tool.get('parameters', {})):
            names[(namespace, tool['name'])] = 'json_text'
            schema = tool['parameters']
            tool['description'] = tool.get('description', '') + '\nPass arguments_json as a JSON object encoded in a string, following this schema: ' + json.dumps(schema)
            tool['parameters'] = {'type': 'object', 'properties': {'arguments_json': {'type': 'string'}},
                                  'required': ['arguments_json'], 'additionalProperties': False}
            tool['strict'] = True
    wire_names = {}
    flattened = []
    for tool, namespace in tool_entries(payload.get('tools', [])):
        if namespace:
            original = (namespace, tool['name'])
            digest = hashlib.sha256((namespace + '\0' + tool['name']).encode()).hexdigest()[:12]
            wire = 'ns_' + digest + '_' + tool['name'][:48]
            kind = names.pop(original, 'identity')
            names[(None, wire)] = {'kind': kind, 'namespace': namespace, 'name': tool['name']}
            wire_names[original] = wire
            tool['description'] = namespace + '.' + tool['name'] + ': ' + tool.get('description', '')
            tool['name'] = wire
        tool.pop('defer_loading', None)
        flattened.append(tool)
    payload['tools'] = flattened
    ceiling = _quirk(payload, 'max_tools')
    if ceiling and len(flattened) > ceiling:
        raise ValueError(f'{payload.get("model")} supports at most {ceiling} exposed tools. Restart Codex and start a fresh task to load the deferred tool catalog.')
    for item in payload.get('input', []) if isinstance(payload.get('input'), list) else []:
        if item.get('type') == 'tool_search_call':
            item.pop('execution', None)
            item.update(type='function_call', name=SEARCH_NAME, arguments=json.dumps(item['arguments']))
        elif item.get('type') == 'tool_search_output':
            item.pop('execution', None)
            item.pop('status', None)
            visible = [{'name': wire_names.get((ns, tool.get('name')), tool.get('name')),
                        'description': tool.get('description', '')} for tool, ns in tool_entries(item.pop('tools'))]
            item.update(type='function_call_output', output=json.dumps({'available_tools': visible}))
        elif item.get('type') == 'custom_tool_call' and tool_key(item) in names:
            item['type'] = 'function_call'
            item['arguments'] = json.dumps({'input': item.pop('input')})
        elif item.get('type') == 'custom_tool_call_output':
            item['type'] = 'function_call_output'
        elif item.get('type') == 'function_call':
            wire = wire_names.get(tool_key(item))
            if wire:
                item.pop('namespace', None)
                item['name'] = wire
            entry = names.get(tool_key(item))
            kind = entry.get('kind') if isinstance(entry, dict) else entry
            if kind == 'json_text':
                item['arguments'] = json.dumps({'arguments_json': item['arguments']})
    return names

class ToolEvents:
    def __init__(self, names, notes=None):
        self.names = names
        self.notes = notes
        self.item_ids = set()

    def item(self, item, started=False):
        if not started and item.get('type') == 'function_call' and isinstance(item.get('arguments'), str):
            item['arguments'] = integer_json(item['arguments'])
        if item.get('type') != 'function_call' or tool_key(item) not in self.names:
            return item
        if item.get('id'):
            self.item_ids.add(item['id'])
        arguments = item.pop('arguments', '')
        kind = self.names[tool_key(item)]
        if isinstance(kind, dict):
            item.update(namespace=kind['namespace'], name=kind['name'])
            kind = kind['kind']
        if kind == 'identity':
            item['arguments'] = arguments
            return item
        if kind == 'search':
            item.pop('name')
            args = {} if started else json.loads(arguments)
            query = args.get('query', '')
            if isinstance(query, str) and re.fullmatch(r'[\w]+(?:\.[\w]+)+', query):
                args['query'] = query.replace('.', ' ')
            item.update(type='tool_search_call', execution='client', arguments=args)
            return item
        if kind == 'json_text':
            value = '' if started else integer_json(json.loads(arguments)['arguments_json'])
            if not started and not isinstance(json.loads(value), dict):
                raise ValueError('Tool arguments must be a JSON object')
            item['arguments'] = value
            return item
        value = '' if started else json.loads(arguments)['input']
        if not isinstance(value, str):
            raise ValueError('Freeform tool input must be a string')
        item.update(type='custom_tool_call', input=value)
        return item

    def event(self, event):
        kind = event.get('type', '')
        if kind in ('response.function_call_arguments.delta', 'response.function_call_arguments.done'):
            if event.get('item_id') in self.item_ids:
                return None  # Native execution consumes the complete item below.
        if kind in ('response.output_item.added', 'response.output_item.done'):
            event['item'] = self.item(event['item'], started=kind.endswith('.added'))
        if isinstance(event.get('response'), dict):
            response = event['response']
            response['output'] = [self.item(item) for item in response.get('output', [])]
            if kind == 'response.completed' and self.notes is not None and isinstance(response.get('model'), str):
                self.notes['served_model'] = response['model']
        return event

def stream_events(response, names, notes=None):
    adapter = ToolEvents(names, notes)
    block = []
    for line in response:
        if line not in (b'\n', b'\r\n'):
            block.append(line)
            continue
        data = b''.join(line[5:].lstrip() for line in block if line.startswith(b'data:')).strip()
        if data and data != b'[DONE]':
            event = adapter.event(json.loads(data))
            if event is not None:
                yield b'data: ' + json.dumps(event).encode() + b'\n\n'
        else:
            yield b''.join(block) + b'\n'
        block = []
    if block:
        raise ValueError('Incomplete upstream SSE event')
