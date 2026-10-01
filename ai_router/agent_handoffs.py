"""Readable collaboration handoffs on mixed installs; Codex still executes every tool.

Codex delivers a spawn, send or follow-up as plaintext only when the call's
`encrypted_function_args` marker is `[]`; anything else reaches the child
encrypted, which only the native backend can read. Where an external child can
exist, every brief is declared readable: external routes rewrite the canonical
tools, while native routes, whose backend requires the canonical message to stay
encrypted, offer readable copies in their own namespace in place of them. Each
call returns to its canonical name with the marker. An install without an
external key keeps the stock encrypted contract.
"""
from copy import deepcopy
import json
import re
import uuid

from . import errors, provider_defs, request_context

NATIVE_NAMESPACE = 'collaboration'
PLAINTEXT_NAMESPACE = 'collaboration_plaintext'
PLAINTEXT_DESCRIPTION = 'Start subagents and send them messages or follow-up tasks as readable text.'
HANDOFF_TOOLS = frozenset(('spawn_agent', 'send_message', 'followup_task'))
LANE_HINT_NAMES = frozenset(('spawn_agent', 'close_agent'))
LANE_HINT = ('When all subagent lanes are full, close finished agents, '
             'or all of them if needed, then retry spawn.')
SPAWN_HINT = ('Pass model and reasoning_effort explicitly for a fresh child; '
              'a child on an externally billed model needs fork_turns="none".')
READABLE_MESSAGE = 'The complete readable assignment or message. Do not encrypt it.'
# Backend handoff ciphertext: matched all 568 saved encrypted messages (Sep 2026).
CIPHERTEXT = re.compile(r'gAAAA[A-Za-z0-9_-]{40,}={0,2}')


class ReadableHandoffs(frozenset):
    """Handoff tools one request declares readable, plus the facts its response checks read."""
    def __new__(cls, names=(), stream=False, spawn_models=None, location='unknown', catalogue=None):
        value = super().__new__(cls, names)
        value.stream = stream
        value.spawn_models = dict(spawn_models or {})
        value.location = location
        value.catalogue = request_context.capture() if catalogue is None else catalogue
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
        if (not isinstance(item, dict) or item.get('type') != 'function_call'
                or item.get('namespace') != NATIVE_NAMESPACE or item.get('name') != 'spawn_agent'):
            continue
        args = _arguments(item)
        task, model = args.get('task_name'), args.get('model')
        if isinstance(task, str) and task and isinstance(model, str) and model:
            models[task] = model
    return models


def readable_handoff_tool(tool, namespace):
    """Copy a complete canonical message schema as readable."""
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
    """`tool`, or a copy with its hints appended once to spawn/close; walks namespaces."""
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
    spawn = plaintext and namespace == NATIVE_NAMESPACE and tool['name'] == 'spawn_agent'
    text = tool.get('description') or ''
    missing = [hint for hint in ((LANE_HINT, SPAWN_HINT) if spawn else (LANE_HINT,))
               if hint not in text]
    if not missing:
        return tool
    return {**tool, 'description': '\n'.join(([text] if text else []) + missing)}


def _hint_tools(tools, namespace=None, plaintext=False):
    hinted = [_hint_tool(tool, namespace, plaintext) for tool in tools]
    return tools if all(new is old for new, old in zip(hinted, tools)) else hinted


def _handoff(tool):
    return isinstance(tool, dict) and tool.get('name') in HANDOFF_TOOLS


def _alias_tools(tools):
    """Move canonical handoffs, readable, into a plaintext namespace after their own.

    The native backend refuses a canonical handoff unless its message stays
    `encrypted: true`, so the readable copies need their own namespace. Other
    collaboration tools stay put, and an emptied namespace is dropped.
    """
    moved, changed = [], False
    for tool in tools:
        children = (tool.get('tools') if isinstance(tool, dict) and tool.get('type') == 'namespace'
                    and tool.get('name') == NATIVE_NAMESPACE else None)
        if not isinstance(children, list) or not any(map(_handoff, children)):
            moved.append(tool)
            continue
        changed = True
        kept = [child for child in children if not _handoff(child)]
        moved += [{**tool, 'tools': kept}] if kept else []
        # Each alias is its canonical tool's readable form, hints included.
        moved.append({'type': 'namespace', 'name': PLAINTEXT_NAMESPACE,
                      'description': PLAINTEXT_DESCRIPTION,
                      'tools': [_hint_tool(child, NATIVE_NAMESPACE, True)
                                for child in children if _handoff(child)]})
    return moved if changed else tools


def _container(tools, plaintext=False, alias=False):
    hinted = _hint_tools(tools, plaintext=plaintext)
    return _alias_tools(hinted) if alias else hinted


def _hint_item(item, plaintext=False, alias=False):
    """A discovery result or Lite prefix with hinted tools; a changed prefix gets a new ID."""
    tools = item.get('tools') if isinstance(item, dict) else None
    lite = tools is not None and item.get('type') == 'additional_tools' and item.get('role') == 'developer'
    if not isinstance(tools, list) or not (lite or item.get('type') == 'tool_search_output'):
        return item
    hinted = _container(tools, plaintext, alias)
    if hinted is tools or not lite:
        return item if hinted is tools else {**item, 'tools': hinted}
    # Codex hashes prefix payloads into IDs; changed tools need a new, stable
    # identity too. Never modify the client's saved prefix.
    identity = json.dumps([item.get('id'), hinted], sort_keys=True)
    return {**item, 'tools': hinted,
            'id': 'at_' + str(uuid.uuid5(uuid.NAMESPACE_URL, 'scg-lane-hint:' + identity))}


def hint_full_lanes(payload, *, plaintext=False, alias=False):
    """Copy declaration hints; `plaintext` makes canonical handoff messages readable
    and `alias` moves the handoffs, readable, into the plaintext namespace."""
    tools = payload.get('tools')
    hinted = _container(tools, plaintext, alias) if isinstance(tools, list) else tools
    if hinted is not tools:
        payload = {**payload, 'tools': hinted}
    items = payload.get('input')
    if not isinstance(items, list):
        return payload
    hinted = [_hint_item(item, plaintext, alias) for item in items]
    return payload if all(new is old for new, old in zip(hinted, items)) else {**payload, 'input': hinted}


def _collaboration(payload):
    """(location, tools) for each collaboration namespace a request declares."""
    containers = [('classic', payload.get('tools'))]
    items = payload.get('input')
    for item in items if isinstance(items, list) else ():
        if isinstance(item, dict) and item.get('type') == 'tool_search_output':
            containers.append(('discovered', item.get('tools')))
        elif (isinstance(item, dict) and item.get('type') == 'additional_tools'
                and item.get('role') == 'developer'):
            containers.append(('lite', item.get('tools')))
    for location, tools in containers:
        for tool in tools if isinstance(tools, list) else ():
            if (isinstance(tool, dict) and tool.get('type') == 'namespace' and isinstance(tool.get('tools'), list)
                    and tool.get('name') in (NATIVE_NAMESPACE, PLAINTEXT_NAMESPACE)):
                yield location, tool['tools']


def readable_names(payload):
    """Handoff tools `payload` declares readable wherever it declares them."""
    readable, opaque = set(), set()
    for _, tools in _collaboration(payload):
        for tool in tools:
            if (isinstance(tool, dict) and tool.get('type') == 'function'
                    and tool.get('name') in HANDOFF_TOOLS):
                message = tool.get('parameters', {}).get('properties', {}).get('message')
                if isinstance(message, dict):
                    (readable if message.get('encrypted') is False else opaque).add(tool['name'])
    return readable - opaque  # One encrypted declaration keeps the stock contract.


def handoff_facts(payload, names, catalogue=None):
    """The response checks' view of one request: readable names plus captured facts."""
    location = next((where for where, _ in _collaboration(payload)), 'unknown')
    return ReadableHandoffs(names, payload.get('stream') is True,
                            spawn_models(payload.get('input')), location, catalogue)


def native_handoffs(payload, readable, catalogue=None):
    """(payload or a copy, ReadableHandoffs) for one native Responses request.

    `readable` follows the install, never the recipient: where an external
    child can exist, every brief is declared readable in the plaintext
    namespace. Otherwise only the lane hints change and the empty set leaves
    the response as the backend sent it.
    """
    payload = hint_full_lanes(payload, alias=readable)
    return payload, handoff_facts(payload, readable_names(payload) if readable else (), catalogue)


def message_shape(item):
    """'absent', 'readable', 'ciphertext' or 'other'; a classification, never content."""
    message = _arguments(item).get('message')  # Unparseable arguments fail in Codex first.
    if message is None:
        return 'absent'
    if not isinstance(message, str):
        return 'other'
    return 'ciphertext' if CIPHERTEXT.fullmatch(message) else 'readable'


def mark_readable(item, names):
    """A call to a readable handoff declaration as Codex executes it in plaintext.

    An alias call returns to its canonical name with the marker. A canonical
    call gains the marker unless its message is ciphertext, which stays
    unmarked for the guard. The marker only restates this request's readable
    declaration: ciphertext under an alias, or an upstream encryption marker,
    is refused rather than relabelled.
    """
    if (not isinstance(item, dict) or item.get('type') != 'function_call'
            or item.get('name') not in names):
        return item
    namespace, marker = item.get('namespace'), item.get('encrypted_function_args', [])
    alias = namespace == PLAINTEXT_NAMESPACE
    if not alias and namespace != NATIVE_NAMESPACE:
        return item
    if marker != [] or (alias and message_shape(item) == 'ciphertext'):
        raise errors.ResponseRejected(400, 'invalid_prompt',
            'This subagent handoff was blocked before delivery because its message came '
            'back encrypted instead of readable. Send your request again.',
            'HANDOFF_READABLE_ENCRYPTED')
    if alias:
        return {**item, 'namespace': NATIVE_NAMESPACE, 'encrypted_function_args': []}
    if 'encrypted_function_args' in item or message_shape(item) not in ('absent', 'readable'):
        return item
    return {**item, 'encrypted_function_args': []}


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
    raise errors.ResponseRejected(400, 'invalid_prompt',
        "This subagent handoff was blocked before delivery: the subagent's model cannot "
        'read an encrypted message. Choose a ' + provider_defs.OPENAI.subscription_label
        + ' model for that subagent, or make sure your '
        + provider_defs.label_for(provider_defs.DEFAULT_EXTERNAL)
        + ' key is set up, then send your request again.', 'HANDOFF_REQUIRES_PLAINTEXT')
