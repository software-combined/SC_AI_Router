"""Standalone app-injected tool outputs become readable plaintext.

Codex Desktop injects cross-task messages (create_thread,
send_message_to_thread) as Responses items shaped like tool outputs but
with no call_id. Providers that cannot accept the native shape receive a
readable assistant-role plaintext message instead; the scrub in
compaction.py never drops that shape.
"""
from .compaction import OUTPUT_TYPES
from .errors import PreparationError

TEXT_KEYS = ('output', 'result', 'content', 'text', 'data')


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
    return (isinstance(item, dict) and item.get('type') in OUTPUT_TYPES
            and not isinstance(item.get('call_id'), str))


def _materialize(item):
    text = _readable_text(item)
    if not text:
        raise PreparationError(
            'unsupported standalone tool output; resend as plain text')
    name = item.get('name')
    if not isinstance(name, str) or not name:
        name = 'codex_app'
    return {'type': 'message', 'role': 'assistant',
            'content': [{'type': 'output_text',
                         'text': f'Delegated task message via {name}:\n{text}'}]}


def materialize_outputs(items):
    """Render standalone outputs as plaintext; same list when none found."""
    if not isinstance(items, list):
        return items
    if not any(_is_standalone(item) for item in items):
        return items
    return [_materialize(item) if _is_standalone(item) else item
            for item in items]
