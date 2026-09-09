"""Plaintext aliases for native collaboration; Codex still executes every tool."""
from copy import deepcopy
import json

from . import sse

NATIVE_NAMESPACE = 'collaboration'
PLAINTEXT_NAMESPACE = 'collaboration_plaintext'
HANDOFF_TOOLS = frozenset(('spawn_agent', 'send_message', 'followup_task'))


class AliasTools(frozenset):
    """Advertised names plus the request's response framing, scoped to one call."""
    def __new__(cls, names, stream=False):
        value = super().__new__(cls, names)
        value.stream = stream
        return value


def add_plaintext_tools(payload):
    """Offer aliases only for native tools present in this request."""
    tools = payload.get('tools', [])
    if any(t.get('name') == PLAINTEXT_NAMESPACE for t in tools):
        raise ValueError('plaintext collaboration namespace collision')
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
                + ' for OpenRouter agents. '
                + tool.get('description', '') +
                '\nPlaintext handoff for mixed-provider agents. Use this variant '
                'for OpenRouter recipients and keep using it for their follow-ups. '
                'Use the original collaboration tool for encrypted native handoffs. '
                'Start mixed-provider children with fork_turns="none" when spawning; '
                'encrypted inherited history cannot be translated.')
            aliases.append(alias)
    names = {tool['name'] for tool in aliases}
    if len(names) != len(aliases):
        raise ValueError('duplicate native collaboration tool')
    if aliases:
        payload['tools'] = [*tools, {'type': 'namespace', 'name': PLAINTEXT_NAMESPACE,
            'description': ('Use this namespace for every initial assignment and follow-up '
                'to OpenRouter agents. Previous calls may appear under collaboration in '
                'history because Codex executes the native tool; that does not change '
                'the need to choose collaboration_plaintext for the next message.'),
            'tools': aliases}]
    return AliasTools(names, payload.get('stream') is True)


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


def restore_response(response, names):
    output = response.get('output')
    if not isinstance(output, list):
        return response
    restored = [restore_item(item, names) for item in output]
    if any(a is not b for a, b in zip(output, restored)):
        return {**response, 'output': restored}
    return response


def _readable_block(block):
    """A plaintext input_text block with no encrypted sidecar."""
    return (isinstance(block, dict) and block.get('type') == 'input_text'
            and 'encrypted_content' not in block and isinstance(block.get('text'), str))


def plaintext_agent_message(item):
    """Represent a readable peer message without elevating its authority."""
    author, recipient = item.get('author'), item.get('recipient')
    content = item.get('content')
    if (not isinstance(author, str) or not author or not isinstance(recipient, str)
            or not recipient or not isinstance(content, list) or not content):
        raise ValueError('unsupported plaintext agent message shape')
    if 'encrypted_content' in item or not all(_readable_block(block) for block in content):
        raise ValueError('unsupported agent message content; use a fresh plaintext handoff')
    return {'type': 'message', 'role': 'assistant', 'content': [
        {'type': 'output_text', 'text': f'Agent message from {author} to {recipient}:\n'},
        *({'type': 'output_text', 'text': block['text']} for block in content)]}


def adapt_response(response, names, notes=None):
    """Adapt aliases only; never run provider-specific rewrites on native calls."""
    if not getattr(names, 'stream', False) and 'text/event-stream' not in response.getheader('Content-Type', ''):
        raw = response.read()
        result = json.loads(raw)
        restored = restore_response(result, names)
        if notes is not None and isinstance(result.get('model'), str):
            notes['served_model'] = result['model']
        yield json.dumps(restored).encode() if restored is not result else raw
        return
    for frame, data in sse.blocks(response):
        if not data or data == b'[DONE]':
            yield frame
            continue
        event = json.loads(data)
        restored = restore_event(event, names)
        if event.get('type') == 'response.completed' and notes is not None:
            model = event.get('response', {}).get('model')
            if isinstance(model, str):
                notes['served_model'] = model
        yield sse.replace_data(frame, json.dumps(restored).encode()) if restored is not event else frame
