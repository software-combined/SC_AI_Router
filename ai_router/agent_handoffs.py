"""Plaintext aliases for native collaboration; Codex still executes every tool."""
from copy import deepcopy
import json
import uuid

from . import provider_defs, sse, transport
from .registry import by_slug

NATIVE_NAMESPACE = 'collaboration'
PLAINTEXT_NAMESPACE = 'collaboration_plaintext'
HANDOFF_TOOLS = frozenset(('spawn_agent', 'send_message', 'followup_task'))
LANE_HINT_NAMES = frozenset(('spawn_agent', 'close_agent'))
LANE_HINT = ('When all subagent lanes are full, close finished agents, '
             'or all of them if needed, then retry spawn.')


class AliasTools(frozenset):
    """Advertised names plus the request's response framing, scoped to one call."""
    def __new__(cls, names, stream=False, spawn_models=None):
        value = super().__new__(cls, names)
        value.stream = stream
        value.spawn_models = dict(spawn_models or {})
        return value


def _arguments(item):
    """Parse function-call arguments leniently; {} when absent or malformed."""
    raw = item.get('arguments')
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _spawn_model(spawns, target):
    """Resolve a child path to one spawn model; ambiguous targets return None."""
    if not isinstance(target, str) or not target:
        return None
    if target in spawns:
        return spawns[target]
    suffix = target.rsplit('/', 1)[-1]
    matches = [model for task, model in spawns.items() if suffix == task]
    if len(matches) != 1:
        return None
    return matches[0]


def spawn_models(items):
    """Map spawn task names in request history to their requested models."""
    models = {}
    if not isinstance(items, list):
        return models
    for item in items:
        if not isinstance(item, dict) or item.get('type') != 'function_call':
            continue
        if item.get('namespace') not in (NATIVE_NAMESPACE, PLAINTEXT_NAMESPACE):
            continue
        if item.get('name') != 'spawn_agent':
            continue
        args = _arguments(item)
        task, model = args.get('task_name'), args.get('model')
        if isinstance(task, str) and task and isinstance(model, str) and model:
            models[task] = model
    return models


def _tool_container(payload):
    """Find one native declaration, including the client's Lite prefix."""
    containers = [(payload, None)]
    items = payload.get('input', [])
    containers.extend((item, index) for index, item in enumerate(items if isinstance(items, list) else [])
                      if isinstance(item, dict) and item.get('type') == 'additional_tools'
                      and item.get('role') == 'developer')
    matches = []
    for container, index in containers:
        tools = container.get('tools', [])
        if index is not None and (not isinstance(tools, list)
                                  or any(not isinstance(t, dict) for t in tools)):
            raise ValueError('unsupported tool declaration shape')
        for tool in tools:
            if tool.get('name') == PLAINTEXT_NAMESPACE:
                raise ValueError('plaintext collaboration namespace collision')
            if tool.get('type') == 'namespace' and tool.get('name') == NATIVE_NAMESPACE:
                matches.append((container, index))
    if len(matches) > 1:
        raise ValueError('duplicate native collaboration namespace')
    return matches[0] if matches else (payload, None)


def _hint_tool(tool):
    """`tool`, or a copy with LANE_HINT appended once to spawn/close; walks namespaces."""
    if not isinstance(tool, dict):
        return tool
    if tool.get('type') == 'namespace':
        children = tool.get('tools')
        if not isinstance(children, list):
            return tool
        hinted = _hint_tools(children)
        return tool if hinted is children else {**tool, 'tools': hinted}
    if tool.get('type') != 'function' or tool.get('name') not in LANE_HINT_NAMES:
        return tool
    text = tool.get('description') or ''
    if LANE_HINT in text:
        return tool
    return {**tool, 'description': (text + '\n' if text else '') + LANE_HINT}


def _hint_tools(tools):
    hinted = [_hint_tool(tool) for tool in tools]
    return tools if all(new is old for new, old in zip(hinted, tools)) else hinted


def _hint_item(item):
    """A discovery result or Lite prefix with hinted tools; a changed prefix gets a new ID."""
    tools = item.get('tools') if isinstance(item, dict) else None
    lite = tools is not None and item.get('type') == 'additional_tools' and item.get('role') == 'developer'
    if not isinstance(tools, list) or not (lite or item.get('type') == 'tool_search_output'):
        return item
    hinted = _hint_tools(tools)
    if hinted is tools or not lite:
        return item if hinted is tools else {**item, 'tools': hinted}
    identity = json.dumps([item.get('id'), hinted], sort_keys=True)
    return {**item, 'tools': hinted,
            'id': 'at_' + str(uuid.uuid5(uuid.NAMESPACE_URL, 'scg-lane-hint:' + identity))}


def hint_full_lanes(payload):
    """Codex-only: tell spawn/close to free lanes, without stacking; copies, never edits."""
    tools = payload.get('tools')
    hinted = _hint_tools(tools) if isinstance(tools, list) else tools
    if hinted is not tools:
        payload = {**payload, 'tools': hinted}
    items = payload.get('input')
    if not isinstance(items, list):
        return payload
    hinted = [_hint_item(item) for item in items]
    return payload if all(new is old for new, old in zip(hinted, items)) else {**payload, 'input': hinted}


def add_plaintext_tools(payload):
    """Offer aliases only for native tools present in this request: (payload or a copy, names)."""
    container, input_index = _tool_container(payload)
    tools = container.get('tools', [])
    aliases = []
    for namespace in tools:
        if namespace.get('type') != 'namespace' or namespace.get('name') != NATIVE_NAMESPACE:
            continue
        for tool in namespace.get('tools', []):
            if tool.get('type') != 'function' or tool.get('name') not in HANDOFF_TOOLS:
                continue
            alias = deepcopy(tool)
            message = alias.get('parameters', {}).get('properties', {}).get('message')
            if not isinstance(message, dict) or message.get('type') != 'string':
                raise ValueError('unsupported native collaboration message schema')
            message['encrypted'] = False
            message['description'] = 'The complete readable assignment or message. Do not encrypt it.'
            alias['description'] = (
                'PLAINTEXT HANDOFF: use collaboration_plaintext.' + tool['name']
                + ' for externally billed agents. '
                + tool.get('description', '') +
                '\nPlaintext handoff for mixed-provider agents. Use this variant '
                'for externally billed recipients and keep using it for their '
                'follow-ups. '
                'Use the original collaboration tool for encrypted native handoffs. '
                'Start mixed-provider children with fork_turns="none" when spawning; '
                'encrypted inherited history cannot be translated.')
            aliases.append(alias)
    names = {tool['name'] for tool in aliases}
    children = spawn_models(payload.get('input', []))
    if len(names) != len(aliases):
        raise ValueError('duplicate native collaboration tool')
    if aliases:
        augmented = [*tools, {'type': 'namespace', 'name': PLAINTEXT_NAMESPACE,
            'description': ('Use this namespace for every initial assignment and follow-up '
                'to externally billed agents. Previous calls may appear under '
                'collaboration in '
                'history because Codex executes the native tool; that does not change '
                'the need to choose collaboration_plaintext for the next message.'),
            'tools': aliases}]
        if input_index is None:
            payload = {**payload, 'tools': augmented}
        else:
            # Codex hashes prefix payloads into IDs; changed tools need a new,
            # stable identity too. Never modify the client's saved prefix.
            identity = json.dumps([container.get('id'), augmented], sort_keys=True)
            ident = 'at_' + str(uuid.uuid5(uuid.NAMESPACE_URL, 'scg-plaintext:' + identity))
            items = list(payload['input'])
            items[input_index] = {**container, 'tools': augmented, 'id': ident}
            payload = {**payload, 'input': items}
    return payload, AliasTools(names, payload.get('stream') is True, children)


def restore_item(item, names):
    """Return a native call; only an advertised alias can signal plaintext."""
    if item.get('namespace') != PLAINTEXT_NAMESPACE:
        return item
    if item.get('type') != 'function_call' or item.get('name') not in names:
        raise ValueError('unadvertised plaintext collaboration call')
    if 'encrypted_function_args' in item and item['encrypted_function_args'] != []:
        raise ValueError('encrypted plaintext collaboration call')
    return {**item, 'namespace': NATIVE_NAMESPACE, 'encrypted_function_args': []}


def restore_event(event, names):
    """Map only Responses item envelopes; unrelated native events are untouched."""
    mapped = event
    if event.get('type') in ('response.output_item.added', 'response.output_item.done'):
        item = event.get('item')
        if isinstance(item, dict):
            restored = restore_item(item, names)
            if restored is not item:
                mapped = {**mapped, 'item': restored}
    response = event.get('response')
    if isinstance(response, dict):
        restored = restore_response(response, names)
        if restored is not response:
            mapped = {**mapped, 'response': restored}
    return mapped


def external_plaintext_call(item, names):
    """External upstreams emit plaintext; keep advertised native calls executable."""
    if (item.get('type') != 'function_call' or item.get('namespace') != NATIVE_NAMESPACE
            or item.get('name') not in HANDOFF_TOOLS or item.get('name') not in names):
        return item
    if item.get('encrypted_function_args', []) != []:
        raise ValueError('unsupported encrypted external handoff')
    return {**item, 'encrypted_function_args': []}


def restore_response(response, names):
    output = response.get('output')
    if not isinstance(output, list):
        return response
    restored = [restore_item(item, names) for item in output]
    if any(a is not b for a, b in zip(output, restored)):
        return {**response, 'output': restored}
    return response


def steer_plaintext(item, names):
    """Steer only unreadable external handoffs through native validation.
    Native encrypted handoffs and unknown targets remain untouched. The
    diagnostic contains no assignment, ciphertext or target."""
    if item.get('type') != 'function_call':
        return item
    if item.get('namespace') != NATIVE_NAMESPACE or item.get('name') not in HANDOFF_TOOLS:
        return item
    if item.get('encrypted_function_args', 'absent') == []:
        return item  # alias-originated plaintext, already readable
    args = _arguments(item)
    spawns = getattr(names, 'spawn_models', {})
    if item.get('name') == 'spawn_agent':
        model = args.get('model')
        entry = by_slug(model) if isinstance(model, str) else None
        if entry is None or not provider_defs.is_external(entry.provider):
            return item
        detail = ('spawn via collaboration_plaintext.spawn_agent '
                  'with fork_turns="none" for externally billed models')
    else:
        target = args.get('target')
        model = _spawn_model(spawns, target)
        entry = by_slug(model) if isinstance(model, str) else None
        if entry is None or not provider_defs.is_external(entry.provider):
            return item
        detail = 'call collaboration_plaintext.' + item['name'] + ' with the same target'
    diagnostic = ('That handoff cannot be delivered readably; ' + detail
                  + ' and resend the message as plain text.')
    return {**item, 'arguments': json.dumps(diagnostic), 'encrypted_function_args': []}


def steer_response(response, names):
    output = response.get('output')
    if not isinstance(output, list):
        return response
    steered = [steer_plaintext(item, names) if isinstance(item, dict) else item
               for item in output]
    if any(a is not b for a, b in zip(output, steered)):
        return {**response, 'output': steered}
    return response


def steer_event(event, names):
    mapped = event
    if event.get('type') in ('response.output_item.added', 'response.output_item.done'):
        item = event.get('item')
        if isinstance(item, dict):
            steered = steer_plaintext(item, names)
            if steered is not item:
                mapped = {**mapped, 'item': steered}
    response = event.get('response')
    if isinstance(response, dict):
        steered = steer_response(response, names)
        if steered is not response:
            mapped = {**mapped, 'response': steered}
    return mapped


def adapt_response(response, names, notes=None):
    """Adapt aliases only; never run provider-specific rewrites on native calls."""
    if not getattr(names, 'stream', False) and 'text/event-stream' not in response.getheader('Content-Type', ''):
        raw = transport.read_capped(response, transport.MAX_UPSTREAM_BODY)
        result = json.loads(raw)
        restored = steer_response(restore_response(result, names), names)
        if notes is not None and isinstance(result.get('model'), str):
            notes['served_model'] = result['model']
        yield json.dumps(restored).encode() if restored is not result else raw
        return
    for frame, data in sse.blocks(sse.lines(transport.passthrough(response))):
        if not data or data == b'[DONE]':
            yield frame
            continue
        event = json.loads(data)
        restored = steer_event(restore_event(event, names), names)
        if event.get('type') == 'response.completed' and notes is not None:
            model = event.get('response', {}).get('model')
            if isinstance(model, str):
                notes['served_model'] = model
        yield sse.replace_data(frame, json.dumps(restored).encode()) if restored is not event else frame
