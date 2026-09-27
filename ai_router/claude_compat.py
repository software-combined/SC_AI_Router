"""Claude Code compatibility repairs for the external Messages route.

The subscription route stays byte-identical: it is the client's own protocol
against the client's own upstream. The external route runs through
OpenRouter's Anthropic-compatible converter, which implements neither
Anthropic's billing block, its empty-thinking shape, nor its deferred-tool
protocol. Every repair below is narrow, applies only where the shape is what
breaks the route, and leaves every other byte alone.
"""
import json
from uuid import uuid4

from . import sse

BILLING_HEADER = 'x-anthropic-billing-header:'
DEFERRED_PLACEHOLDER = 'DeferredToolPlaceholder'
REFERENCE_TYPE = 'tool_reference'
SERVER_TOOL_PREFIX = 'tool_search_tool'
TOOL_ID_PREFIX = 'toolu_scg_'


def _fresh_tool_id():
    """One client-visible id for one tool call, unique across turns."""
    return TOOL_ID_PREFIX + uuid4().hex


def strip_billing_header(payload):
    """Drop the client's billing block; True when the payload changed.

    Claude Code 2.1.223 sends its attribution line as the first `system`
    block so a gateway can bill against it. `anthropic/claude-fable-5.1`
    answers that text with HTTP 400 `invalid_request`, which the router
    reports as a refusal, so every Fable turn fails. The line only matters
    to Anthropic's own billing, which the external route does not use.
    """
    if not isinstance(payload, dict):
        return False
    system = payload.get('system')
    if not isinstance(system, list):
        return False
    keep = [block for block in system
            if not (isinstance(block, dict)
                    and isinstance(block.get('text'), str)
                    and block['text'].strip().startswith(BILLING_HEADER))]
    if len(keep) == len(system):
        return False
    if keep:
        payload['system'] = keep
    else:
        payload.pop('system', None)
    return True


def flatten_deferred_tools(payload):
    """Serve Claude Code's deferred tool search to an upstream without it.

    With tool search on, Claude Code 2.1.223 withholds the deferred
    definitions and sends a `DeferredToolPlaceholder` instead; the client
    searches its own catalogue, answers the search with `tool_reference`
    blocks, and from then on includes each released definition marked
    `defer_loading`, which Anthropic's own API expands. OpenRouter expands
    nothing, so the placeholder and the server-side tool entry go, the flag
    goes (the released definition is already in the same request's tool
    list, so the model keeps every tool it discovered), and a reference
    block becomes the plain text naming the tool it stood for. The tool_use
    and tool_result pairing is never broken. True when anything changed.
    """
    if not isinstance(payload, dict):
        return False
    changed = _flatten_tools(payload)
    for message in payload.get('messages') or []:
        content = message.get('content') if isinstance(message, dict) else None
        for block in content if isinstance(content, list) else []:
            changed |= _plain_reference(block)
    return changed


def _flatten_tools(payload):
    """Drop the placeholder and the flag; True when the list changed."""
    tools = payload.get('tools')
    if not isinstance(tools, list):
        return False
    kept, changed = [], False
    for tool in tools:
        if not isinstance(tool, dict):
            kept.append(tool)
            continue
        if (tool.get('name') == DEFERRED_PLACEHOLDER
                or str(tool.get('type') or '').startswith(SERVER_TOOL_PREFIX)):
            changed = True
            continue
        if 'defer_loading' in tool:
            tool.pop('defer_loading')
            changed = True
        kept.append(tool)
    if changed:
        payload['tools'] = kept
    return changed


def _plain_reference(block):
    """Name the tools one reference block stood for; True when it changed."""
    if not isinstance(block, dict) or block.get('type') != 'tool_result':
        return False
    inner = block.get('content')
    if not isinstance(inner, list):
        return False
    names = [item.get('tool_name') for item in inner
             if isinstance(item, dict) and item.get('type') == REFERENCE_TYPE]
    if not names:
        return False
    block['content'] = [item for item in inner
                        if not (isinstance(item, dict)
                                and item.get('type') == REFERENCE_TYPE)]
    block['content'].append({'type': 'text',
                             'text': 'The search released: %s.'
                                     % ', '.join(str(name) for name in names)})
    return True


def shape(chunks):
    """Repair streamed Messages shapes before Claude Code sees them.

    OpenRouter returns a trailing `thinking` block holding only a
    signature after a tool result on `google/gemini-3.8-flash`. Claude Code
    discards the whole turn's text when it follows the answer, so the user
    sees an empty reply. A block that streams real thinking is emitted as
    soon as its first `thinking_delta` arrives, so only the empty shape is
    ever held back. DeepSeek V4.1 Flash also returns `call_0` for every tool
    call; Claude Code collapses duplicate ids and keeps only one earlier
    `tool_result`, so each response gets a fresh client-visible id here.
    """
    pending, index = [], None
    for frame, data in sse.blocks(sse.lines(chunks)):
        event = _parsed(data)
        frame = _rewrite_tool_use(frame, event)
        kind = event.get('type')
        if index is None:
            if (kind == 'content_block_start'
                    and _nested_type(event, 'content_block') == 'thinking'):
                index, pending = event.get('index'), [(frame, event)]
                continue
            yield frame
            continue
        pending.append((frame, event))
        if (kind == 'content_block_delta'
                and _nested_type(event, 'delta') == 'thinking_delta'):
            for held, _ in pending:
                yield held
            pending, index = [], None
        elif kind == 'content_block_stop' and event.get('index') == index:
            # Frames from other open blocks interleave with the empty one and
            # still belong to the answer, so only this index is dropped.
            for held, held_event in pending:
                if held_event.get('index') != index:
                    yield held
            pending, index = [], None
    for held, _ in pending:
        yield held


def _rewrite_tool_use(frame, event):
    """Replace one streamed tool id; leave every other frame unchanged."""
    if event.get('type') != 'content_block_start':
        return frame
    block = event.get('content_block')
    if not isinstance(block, dict) or block.get('type') != 'tool_use':
        return frame
    if not isinstance(block.get('id'), str):
        return frame
    block['id'] = _fresh_tool_id()
    return sse.replace_data(frame, json.dumps(event, separators=(',', ':')).encode())


def shape_json(raw):
    """Give JSON tool calls unique client IDs without changing nested input."""
    try:
        payload = json.loads(raw)
    except ValueError:
        return raw
    if not isinstance(payload, dict):
        return raw
    content = payload.get('content')
    changed = False
    for block in content if isinstance(content, list) else []:
        if (isinstance(block, dict) and block.get('type') == 'tool_use'
                and isinstance(block.get('id'), str)):
            block['id'] = _fresh_tool_id()
            changed = True
    return (json.dumps(payload, separators=(',', ':')).encode()
            if changed else raw)


def _parsed(data):
    """One SSE data field as an object; malformed or non-object reads empty."""
    try:
        value = json.loads(data)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _nested_type(event, name):
    """`type` of the named nested object, or None when there is no object."""
    nested = event.get(name)
    return nested.get('type') if isinstance(nested, dict) else None
