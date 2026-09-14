"""App-injected outputs and readable peer messages become matched tool pairs.

Codex Desktop injects cross-task messages (create_thread,
send_message_to_thread) as Responses items shaped like tool outputs but
with no call_id. OpenRouter rejects that raw shape (HTTP 400), and live
acceptance showed a readable assistant-role plaintext message is not
acted on (the child replied NO-ASSIGNMENT and a router probe returned
no output items). Each standalone output is therefore rendered as a
matched pair -- a synthesized complete `function_call` plus the
`function_call_output` carrying the delegation text verbatim -- which
the model treats as a tool result and the scrub in compaction.py passes
through untouched. No `namespace` is set on either member: OpenRouter
400s when it is present on both members of the pair. Peer messages use the
same projection: a terminal assistant message is also rejected as prefill by
Sonnet. Readable peer text stays tool-level data, never a user instruction.
"""
from .compaction import OUTPUT_TYPES
from .agent_handoffs import plaintext_agent_message
from .errors import PreparationError

TEXT_KEYS = ('output', 'result', 'content', 'text', 'data')

DELIVERED_MESSAGE = 'delivered_message'
DELIVERED_APP_MESSAGE = 'delivered_app_message'
# Every synthesized name the router injects into a model's history comes
# from this set, never an ad hoc string (Plan 172).
DELIVERED_NAMES = frozenset((DELIVERED_MESSAGE, DELIVERED_APP_MESSAGE))


def _readable_text(item):
    """First non-empty text field, verbatim; content blocks join on space."""
    for key in TEXT_KEYS:
        value = item.get(key)
        if isinstance(value, str):
            if value:
                return value
        elif isinstance(value, list):
            text = ' '.join(block.get('text', '') for block in value
                            if isinstance(block, dict)
                            and isinstance(block.get('text'), str))
            if text:
                return text
    return ''


def _is_standalone(item):
    return (isinstance(item, dict) and (item.get('type') == 'agent_message'
            or (item.get('type') in OUTPUT_TYPES
                and not isinstance(item.get('call_id'), str))))


def _call_id(item, index):
    """Deterministic unique id: the item id when present, else its index."""
    item_id = item.get('id')
    if isinstance(item_id, str) and item_id:
        return 'call_' + item_id
    return f'call_standalone_{index}'


def _materialize(item, index):
    if item.get('type') == 'agent_message':
        message = plaintext_agent_message(item)
        item = {'id': item.get('id'), 'name': DELIVERED_MESSAGE,
                'output': ''.join(block['text'] for block in message['content'])}
    text = _readable_text(item)
    if not text:
        raise PreparationError(
            'unsupported standalone tool output; resend as plain text')
    name = item.get('name')
    if not isinstance(name, str) or not name:
        name = DELIVERED_APP_MESSAGE
    cid = _call_id(item, index)
    return [{'type': 'function_call', 'call_id': cid,
             'name': name, 'arguments': '{}'},
            {'type': 'function_call_output', 'call_id': cid,
             'output': text}]


def materialize_outputs(items):
    """Render standalone outputs as matched pairs; same list when none."""
    if not isinstance(items, list):
        return items
    if not any(_is_standalone(item) for item in items):
        return items
    out = []
    for index, item in enumerate(items):
        if _is_standalone(item):
            out.extend(_materialize(item, index))
        else:
            out.append(item)
    return out
