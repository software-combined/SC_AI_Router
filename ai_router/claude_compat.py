"""Claude Code compatibility repairs for the external Messages route.

The subscription route stays byte-identical: it is the client's own protocol
against the client's own upstream. The external route runs through
OpenRouter's Anthropic-compatible converter, and two shapes that converter
produces make Claude Code 2.1.223 lose the user's answer. Both repairs are
narrow, apply only where the shape is what breaks the client, and leave every
other byte alone.
"""
import json

from . import sse

BILLING_HEADER = 'x-anthropic-billing-header:'


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


def shape(chunks):
    """Drop thinking blocks that carry a signature but no thinking.

    OpenRouter returns a trailing `thinking` block holding only a
    signature after a tool result on `google/gemini-3.8-flash`. Claude Code
    discards the whole turn's text when it follows the answer, so the user
    sees an empty reply. A block that streams real thinking is emitted as
    soon as its first `thinking_delta` arrives, so only the empty shape is
    ever held back.
    """
    pending, index = [], None
    for frame, data in sse.blocks(sse.lines(chunks)):
        event = _parsed(data)
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
