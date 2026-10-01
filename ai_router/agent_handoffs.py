"""Plaintext aliases for native collaboration; Codex still executes every tool."""
from copy import deepcopy
import json
import uuid

from . import errors, provider_defs, request_context

NATIVE_NAMESPACE = 'collaboration'
PLAINTEXT_NAMESPACE = 'collaboration_plaintext'
HANDOFF_TOOLS = frozenset(('spawn_agent', 'send_message', 'followup_task'))
LANE_HINT_NAMES = frozenset(('spawn_agent', 'close_agent'))
LANE_HINT = ('When all subagent lanes are full, close finished agents, '
             'or all of them if needed, then retry spawn.')
READABLE_MESSAGE = 'The complete readable assignment or message. Do not encrypt it.'


class AliasTools(frozenset):
    """Alias authority, canonical readability and captured metadata for one request."""
    def __new__(cls, names, stream=False, spawn_models=None, location='unknown', catalogue=None, readable=()):
        value = super().__new__(cls, names)
        value.stream = stream
        value.spawn_models = dict(spawn_models or {})
        value.location = location
        value.catalogue = request_context.capture() if catalogue is None else catalogue
        value.readable = frozenset(readable)
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


def readable_handoff_tool(tool, namespace):
    """Copy a complete canonical message schema for external upstreams."""
    if (namespace != NATIVE_NAMESPACE or tool.get('type') != 'function'
            or tool.get('name') not in HANDOFF_TOOLS):
        return tool
    message = tool.get('parameters', {}).get('properties', {}).get('message')
    if not isinstance(message, dict) or message.get('type') != 'string':
        return tool  # Discovery may complete a declaration stub later.
    if message.get('encrypted') is False and message.get('description') == READABLE_MESSAGE:
        return tool
    parameters = deepcopy(tool['parameters'])
    parameters['properties']['message'].update(encrypted=False, description=READABLE_MESSAGE)
    return {**tool, 'parameters': parameters}


def _hint_tool(tool, namespace=None, plaintext=False):
    """`tool`, or a copy with LANE_HINT appended once to spawn/close; walks namespaces."""
    if not isinstance(tool, dict):
        return tool
    if tool.get('type') == 'namespace':
        children = tool.get('tools')
        if not isinstance(children, list):
            return tool
        hinted = _hint_tools(children, tool.get('name'), plaintext)
        return tool if hinted is children else {**tool, 'tools': hinted}
    if plaintext:
        tool = readable_handoff_tool(tool, namespace)
    if tool.get('type') != 'function' or tool.get('name') not in LANE_HINT_NAMES:
        return tool
    text = tool.get('description') or ''
    if LANE_HINT in text:
        return tool
    return {**tool, 'description': (text + '\n' if text else '') + LANE_HINT}


def _hint_tools(tools, namespace=None, plaintext=False):
    hinted = [_hint_tool(tool, namespace, plaintext) for tool in tools]
    return tools if all(new is old for new, old in zip(hinted, tools)) else hinted


def _hint_item(item, plaintext=False):
    """A discovery result or Lite prefix with hinted tools; a changed prefix gets a new ID."""
    tools = item.get('tools') if isinstance(item, dict) else None
    lite = tools is not None and item.get('type') == 'additional_tools' and item.get('role') == 'developer'
    if not isinstance(tools, list) or not (lite or item.get('type') == 'tool_search_output'):
        return item
    hinted = _hint_tools(tools, plaintext=plaintext)
    if hinted is tools or not lite:
        return item if hinted is tools else {**item, 'tools': hinted}
    identity = json.dumps([item.get('id'), hinted], sort_keys=True)
    return {**item, 'tools': hinted,
            'id': 'at_' + str(uuid.uuid5(uuid.NAMESPACE_URL, 'scg-lane-hint:' + identity))}


def hint_full_lanes(payload, *, plaintext=False):
    """Copy declaration hints and, for external routes, readable message schemas."""
    tools = payload.get('tools')
    hinted = _hint_tools(tools, plaintext=plaintext) if isinstance(tools, list) else tools
    if hinted is not tools:
        payload = {**payload, 'tools': hinted}
    items = payload.get('input')
    if not isinstance(items, list):
        return payload
    hinted = [_hint_item(item, plaintext) for item in items]
    return payload if all(new is old for new, old in zip(hinted, items)) else {**payload, 'input': hinted}


def add_plaintext_tools(payload, catalogue=None):
    """Offer aliases only for native tools present in this request: (payload or a copy, names)."""
    container, input_index = _tool_container(payload)
    tools = container.get('tools', [])
    aliases = []
    described = []
    for namespace in tools:
        if namespace.get('type') != 'namespace' or namespace.get('name') != NATIVE_NAMESPACE:
            continue
        for tool in namespace.get('tools', []):
            if tool.get('type') != 'function' or tool.get('name') not in HANDOFF_TOOLS:
                described.append(tool)
                continue
            guidance = (
                'Choose by the recipient provider route. Native subscription GPT uses collaboration. '
                'External recipients, including GPT through OpenRouter, require collaboration_plaintext.'
                + tool['name'] + ' for every assignment and follow-up, even when saved calls use native names.')
            if tool['name'] == 'spawn_agent':
                guidance += (' Pass model and reasoning_effort explicitly for fresh or partial-history children. '
                             'Choose full native history inheritance deliberately. '
                             'External children require fork_turns="none"; encrypted history cannot be translated.')
            tool = {**tool, 'description': tool.get('description', '') + '\n' + guidance}
            described.append(tool)
            alias = {**readable_handoff_tool(tool, NATIVE_NAMESPACE)}
            message = alias.get('parameters', {}).get('properties', {}).get('message')
            if not isinstance(message, dict) or message.get('type') != 'string':
                raise ValueError('unsupported native collaboration message schema')
            alias['description'] = (
                'PLAINTEXT HANDOFF: use collaboration_plaintext.' + tool['name']
                + ' for externally billed agents. '
                + tool.get('description', '') +
                '\nSend the complete readable message. Do not encrypt it.')
            aliases.append(alias)
    names = {tool['name'] for tool in aliases}
    children = spawn_models(payload.get('input', []))
    if len(names) != len(aliases):
        raise ValueError('duplicate native collaboration tool')
    if aliases:
        tools = [{**ns, 'tools': described} if ns.get('name') == NATIVE_NAMESPACE else ns for ns in tools]
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
    return payload, AliasTools(names, payload.get('stream') is True, children,
                               'classic' if input_index is None else 'lite', catalogue=catalogue)


def _plaintext_rejected(reason):
    return errors.ResponseRejected(400, 'invalid_prompt',
        'This handoff was blocked before delivery. Start a new turn and use an advertised '
        'collaboration_plaintext tool with a readable message. Do not resend the encrypted call.', reason)


def restore_item(item, names):
    """Return a native call; only an advertised alias can signal plaintext."""
    if item.get('namespace') != PLAINTEXT_NAMESPACE:
        return item
    if item.get('type') != 'function_call' or item.get('name') not in names:
        raise _plaintext_rejected('HANDOFF_ALIAS_UNADVERTISED')
    if 'encrypted_function_args' in item and item['encrypted_function_args'] != []:
        raise _plaintext_rejected('HANDOFF_ALIAS_ENCRYPTED')
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
        raise _plaintext_rejected('HANDOFF_EXTERNAL_ENCRYPTED')
    return {**item, 'encrypted_function_args': []}


def restore_response(response, names):
    output = response.get('output')
    if not isinstance(output, list):
        return response
    restored = [restore_item(item, names) for item in output]
    if any(a is not b for a, b in zip(output, restored)):
        return {**response, 'output': restored}
    return response


def validate_handoff(item, names):
    """Reject a known unreadable recipient before Codex can execute the call.

    Routing uses the request's captured provider metadata, never model names.
    Only an explicit plaintext signal establishes readability on this route.
    """
    if not isinstance(item, dict) or item.get('type') != 'function_call':
        return
    if item.get('namespace') != NATIVE_NAMESPACE or item.get('name') not in HANDOFF_TOOLS:
        return
    if item.get('encrypted_function_args', 'absent') == []:
        return
    args = _arguments(item)
    spawns = getattr(names, 'spawn_models', {})
    if item.get('name') == 'spawn_agent':
        model = args.get('model')
    else:
        target = args.get('target')
        model = _spawn_model(spawns, target)
    entry = getattr(names, 'catalogue', {}).get(model) if isinstance(model, str) else None
    if entry is None or not provider_defs.is_external(entry.provider):
        return
    extra = ' and fork_turns="none"' if item['name'] == 'spawn_agent' else ' and the same target'
    raise errors.ResponseRejected(400, 'invalid_prompt',
        'This handoff was blocked before delivery. Start a new turn and use '
        'collaboration_plaintext.' + item['name'] + ' with a readable message' + extra
        + '. Do not resend the encrypted call.', 'HANDOFF_REQUIRES_PLAINTEXT')
