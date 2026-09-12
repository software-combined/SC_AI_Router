"""Normalize external Responses terminal errors without changing success data."""
import json
import re
from . import errors, sse

_CONTEXT_MESSAGE = re.compile(
    r'The prompt is too long: ([0-9]{1,16}), model maximum context length: ([0-9]{1,16})')


def _context_error(data, depth=0):
    """Explicit codes or the exact numeric refusal in an error envelope."""
    if not isinstance(data, dict):
        return False
    if data.get('error_type') == 'context_length_exceeded':
        return True
    error = data.get('error')
    if not isinstance(error, dict):
        return False
    if error.get('code') == 'context_length_exceeded':
        return True
    if error.get('error_type') == 'context_length_exceeded':
        return True
    message = error.get('message')
    match = _CONTEXT_MESSAGE.fullmatch(message.strip()) if isinstance(message, str) else None
    if match and int(match[1]) > int(match[2]) > 0:
        return True
    metadata = error.get('metadata')
    if isinstance(metadata, dict) and metadata.get('error_type') == 'context_length_exceeded':
        return True
    raw = metadata.get('raw') if isinstance(metadata, dict) else None
    if isinstance(raw, str) and depth < 2:
        try:
            return _context_error(json.loads(raw), depth + 1)
        except ValueError:
            return False
    return False


def is_context_error(body):
    """Classify an upstream error, never search arbitrary user-bearing prose."""
    try:
        return _context_error(json.loads(body))
    except (ValueError, TypeError):
        return False


def normalize(chunks, metrics):
    """Keep HTTP status separate from the terminal event's inference outcome."""
    for frame, data in sse.blocks(sse.lines(chunks)):
        try:
            event = json.loads(data)
        except (ValueError, UnicodeDecodeError):
            yield frame
            continue
        kind = event.get('type') if isinstance(event, dict) else None
        if kind not in ('response.failed', 'response.incomplete', 'error'):
            yield frame
            continue
        failure = event.get('response') if kind.startswith('response.') else event
        if kind == 'error' and 'error' not in event:
            failure = {'error': event}
        context = (kind != 'response.incomplete'
                   and (_context_error(failure) or _context_error(event)))
        metrics['code'] = 'context_length_exceeded' if context else 'UPSTREAM_STREAM_FAILED'
        metrics.pop('served_model', None)
        if context:
            frame = sse.frame(json.dumps({
                'type': 'response.failed', 'response': errors.context_window().body()}).encode())
        yield frame
        return  # A terminal failure cannot be followed by a successful completion.
