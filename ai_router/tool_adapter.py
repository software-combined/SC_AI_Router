"""Adapt Codex client tool discovery and schemas to JSON function tools.

The native Codex executor still owns tool validation and execution. This adapter
only wraps/unwraps its text input; it never executes tools or changes permissions.
"""
import hashlib
import json
import re
from copy import deepcopy
from .capabilities import has_recursive_refs
from .discovered import recall
from .registry import by_slug
from . import agent_handoffs, sse
SEARCH_NAME = 'codex_client_tool_search'
# Bytes retained per body for the post-EOF identity parse. Overflow drops
# the observation, never the forwarded bytes.
_OBSERVE_LIMIT = 64 * 1024

def _quirk(payload, name):
    entry = by_slug(payload.get('model', ''))
    return getattr(entry, name, None) if entry else None

def integer_json(text):
    # Meta emits e.g. 8.0 for integer arguments. Rust's integer deserializers
    # reject that spelling. Preserve strings, fractions and large-number precision.
    if '.0' not in text:
        return text
    try:
        json.loads(text)
    except json.JSONDecodeError:
        return text  # Leave malformed arguments for the native validator to reject.
    return re.sub(r'("(?:\\.|[^"\\])*")|(-?\d+)\.0+(?=\s*[,}\]]|\s*$)',
                  lambda match: match[1] if match[1] is not None else match[2], text)

def tool_entries(tools, namespace=None):
    for tool in tools:
        if tool.get('type') == 'namespace':
            yield from tool_entries(tool.get('tools', []), tool['name'])
        else:
            yield tool, namespace

def tool_key(item):
    return (item.get('namespace'), item.get('name'))

def _wrap_string_envelope(tool, noun):
    """Share the arguments_json string envelope between json_text kinds."""
    schema = tool['parameters']
    tool['description'] = tool.get('description', '') + (
        f'\nPass arguments_json as a JSON {noun} encoded in a string, '
        'following this schema: ' + json.dumps(schema))
    tool['parameters'] = {'type': 'object', 'properties': {'arguments_json': {'type': 'string'}},
                          'required': ['arguments_json'], 'additionalProperties': False}
    tool['strict'] = True

def _grok_needs_envelope(parameters):
    """True when xAI would reject the parameter root without a string envelope."""
    if not isinstance(parameters, dict):
        return False
    if parameters.get('type') != 'object':
        return True
    for key in ('anyOf', 'oneOf'):
        branches = parameters.get(key)
        if isinstance(branches, list):
            for branch in branches:
                if isinstance(branch, dict) and branch.get('type') != 'object':
                    return True
    return False

def prepare_tools(payload):
    names = {}
    # OpenAI reads discovered definitions from tool_search_output history. Other
    # providers require those released tools in the ordinary request tool list.
    released = []
    for item in payload.get('input', []) if isinstance(payload.get('input'), list) else []:
        if item.get('type') == 'tool_search_output':
            released.extend(deepcopy(item.get('tools', [])))
    released.extend(recall(payload.get('input', [])))
    released_keys = {(namespace, tool.get('name')) for tool, namespace in tool_entries(released)}
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
        elif (_quirk(payload, 'schema_mode') == 'json_text'
                and has_recursive_refs(tool.get('parameters', {}))):
            _wrap_string_envelope(tool, 'object')
            names[(namespace, tool['name'])] = 'json_text'
        elif (_quirk(payload, 'schema_mode') == 'json_text_root'
                and _grok_needs_envelope(tool.get('parameters'))):
            # xAI rejects non-object parameter roots, including object roots
            # with an anyOf/oneOf union holding a non-object branch (e.g. the
            # automation tool). Same string envelope as json_text, but the
            # value may be any JSON type the original schema accepts.
            # Object-only unions stay native.
            _wrap_string_envelope(tool, 'value')
            names[(namespace, tool['name'])] = 'json_text_root'
    wire_names = {}
    flattened = []
    for tool, namespace in tool_entries(payload.get('tools', [])):
        if namespace:
            original = (namespace, tool['name'])
            digest = hashlib.sha256((namespace + '\0' + tool['name']).encode()).hexdigest()[:12]
            wire = 'ns_' + digest + '_' + tool['name'][:48]
            kind = names.pop(original, 'identity')
            if original in released_keys:
                released_keys.discard(original)
                released_keys.add((None, wire))
            names[(None, wire)] = {'kind': kind, 'namespace': namespace, 'name': tool['name']}
            wire_names[original] = wire
            tool['description'] = namespace + '.' + tool['name'] + ': ' + tool.get('description', '')
            tool['name'] = wire
        tool.pop('defer_loading', None)
        flattened.append(tool)
    if _quirk(payload, 'web_search') is False:
        # No web-search capability upstream: OpenRouter aborts the turn with
        # 'Server tool request failed' when the client's web_search server
        # tool rides along (2026-09-10, deepseek-v4.1-flash).
        flattened = [tool for tool in flattened if tool.get('type') != 'web_search']
    payload['tools'] = flattened
    ceiling = _quirk(payload, 'max_tools')
    if ceiling and len(flattened) > ceiling:
        # ponytail: drop, don't page; the search tool reloads on demand.
        kinds = [names.get((None, tool.get('name'))) for tool in flattened]
        kinds = [kind.get('kind') if isinstance(kind, dict) else kind for kind in kinds]
        kept = [tool for tool, kind in zip(flattened, kinds)
                if kind == 'search' or (None, tool.get('name')) in released_keys]
        if 'search' not in kinds or len(kept) > ceiling:
            raise ValueError(
                f'{payload.get("model")} supports at most {ceiling} exposed tools '
                f'(this turn exposes {len(flattened)}). Switch to a model without '
                'the ceiling, or trim tools, then retry in the same thread.')
        for tool in flattened:
            if tool not in kept:
                names.pop((None, tool.get('name')), None)
        payload['tools'] = kept
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
        elif item.get('type') == 'custom_tool_call' and (
                tool_key(item) in names or tool_key(item) in wire_names):
            key = tool_key(item)
            item['type'] = 'function_call'
            item['arguments'] = json.dumps({'input': item.pop('input')})
            if key in wire_names:
                item.pop('namespace', None)
                item['name'] = wire_names[key]
        elif item.get('type') == 'custom_tool_call_output':
            item['type'] = 'function_call_output'
            wire = wire_names.get(tool_key(item))
            if wire:
                item.pop('namespace', None)
                item['name'] = wire
        elif item.get('type') == 'function_call':
            wire = wire_names.get(tool_key(item))
            if wire:
                item.pop('namespace', None)
                item['name'] = wire
            entry = names.get(tool_key(item))
            kind = entry.get('kind') if isinstance(entry, dict) else entry
            if kind in ('json_text', 'json_text_root'):
                item['arguments'] = json.dumps({'arguments_json': item['arguments']})
    return names

class ToolEvents:
    def __init__(self, names, notes=None):
        self.names = names
        self.notes = notes
        self.item_ids = set()
        self.changed = False

    def item(self, item, started=False):
        if not started and item.get('type') == 'function_call' and isinstance(item.get('arguments'), str):
            trimmed = integer_json(item['arguments'])
            if trimmed != item['arguments']:
                self.changed = True
                item['arguments'] = trimmed
        if item.get('type') != 'function_call' or tool_key(item) not in self.names:
            return item
        if item.get('id'):
            self.item_ids.add(item['id'])
        had_arguments = 'arguments' in item
        arguments = item.pop('arguments', '')
        kind = self.names[tool_key(item)]
        if isinstance(kind, dict):
            if item.get('namespace') != kind['namespace'] or item.get('name') != kind['name']:
                self.changed = True
            item.update(namespace=kind['namespace'], name=kind['name'])
            if kind['namespace'] == agent_handoffs.PLAINTEXT_NAMESPACE:
                restored = agent_handoffs.restore_item(item, {kind['name']})
                if restored is not item:
                    self.changed = True
                item = restored
            kind = kind['kind']
        if kind == 'identity':
            if not had_arguments:
                self.changed = True
            item['arguments'] = arguments
            return item
        self.changed = True
        if kind == 'search':
            item.pop('name')
            args = {} if started else json.loads(arguments)
            query = args.get('query', '')
            if isinstance(query, str) and re.fullmatch(r'[\w]+(?:\.[\w]+)+', query):
                args['query'] = query.replace('.', ' ')
            item.update(type='tool_search_call', execution='client', arguments=args)
            return item
        if kind in ('json_text', 'json_text_root'):
            value = '' if started else integer_json(json.loads(arguments)['arguments_json'])
            if not started:
                parsed = json.loads(value)  # any JSON value the original schema accepts
                if kind == 'json_text' and not isinstance(parsed, dict):
                    raise ValueError('Tool arguments must be a JSON object')
            item['arguments'] = value
            return item
        value = '' if started else json.loads(arguments)['input']
        if not isinstance(value, str):
            raise ValueError('Freeform tool input must be a string')
        item.update(type='custom_tool_call', input=value)
        return item

    def event(self, event):
        self.changed = False
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

def snoop_response_identity(response, notes):
    """Yield a tool-free 200 response unchanged while recording its model.

    Forwarding stays immediate: bytes are yielded as they arrive and
    identity is observed, never awaited. Non-SSE bodies stream through
    read1 pieces while a bounded copy is retained for a post-EOF parse;
    overflow (over 64 KiB seen) disables observation, never forwarding.
    SSE bodies stream piece by piece with complete frames parsed for
    identity; an over-long tail or unterminated trailing bytes are
    discarded unobserved. Malformed observation data is nonfatal.
    """
    if 'text/event-stream' not in response.getheader('Content-Type', ''):
        kept = bytearray()
        seen = 0  # cumulative bytes; parse only when seen fits the bound
        while piece := response.read1(65536):
            yield piece
            seen += len(piece)
            if len(kept) < _OBSERVE_LIMIT:
                kept += piece
        if seen <= _OBSERVE_LIMIT:
            try:
                model = json.loads(kept).get('model')
            except Exception:
                model = None  # observation is best-effort; never fail bytes
            if isinstance(model, str):
                notes['served_model'] = model
        return
    spare = b''
    watching = True  # False once the tail exceeds the bound: keep yielding
    # read1 is the codebase-wide stream primitive (transport.passthrough
    # relies on it too); no line-iteration fallback, which would rebuffer.
    while piece := response.read1(65536):
        yield piece
        if not watching:
            continue
        spare, frames = _split_frames(spare + piece)
        if len(spare) > _OBSERVE_LIMIT:
            spare, watching = b'', False
            continue
        for frame in frames:
            _observe_sse_frame(frame, notes)
    # An unterminated tail is discarded like the canonical framer does;
    # only complete frames may observe identity.


def _split_frames(buf):
    """Split blank-line-terminated SSE frames off buf.

    Returns (spare, frames): frames are complete and parseable now;
    spare is the incomplete tail held for the next piece.
    """
    frames = []
    start = 0
    while True:
        nl = buf.find(b'\n', start)
        if nl < 0:
            break
        end = nl + 1
        if buf[start:end].strip():
            start = end
            continue
        frames.append(buf[:end])
        buf = buf[end:]
        start = 0
    return buf, frames


def _observe_sse_frame(frame, notes):
    """Record identity from one complete SSE frame; never raises."""
    try:
        data = b''.join(part[5:].lstrip() for part in
                        frame.split(b'\n') if part.startswith(b'data:')).strip()
        if data and data != b'[DONE]':
            completed = _completed_model(data)
            if completed is not None:
                notes['served_model'] = completed
    except Exception:
        pass  # observation is best-effort; never fail forwarded bytes


def _completed_model(data):
    """Serving model from a response.completed SSE payload, else None."""
    try:
        event = json.loads(data)
        if event['type'] != 'response.completed':
            return None
        model = event['response']['model']
        return model if isinstance(model, str) else None
    except Exception:
        return None


def stream_events(response, names, notes=None):
    adapter = ToolEvents(names, notes)
    for frame, data in sse.blocks(response):
        if data and data != b'[DONE]':
            event = adapter.event(json.loads(data))
            if event is None:
                continue
            if adapter.changed:
                yield sse.frame(json.dumps(event).encode())
            else:
                yield sse.frame(data)
        else:
            yield frame
