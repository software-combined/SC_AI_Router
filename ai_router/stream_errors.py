"""Normalize external Responses terminal errors without changing success data."""
import json
import re
from . import errors, sse

_CONTEXT_MESSAGE = re.compile(
    r'The prompt is too long: ([0-9]{1,16}), model maximum context length: ([0-9]{1,16})')
MAX_DETAIL_CHARS = 64
# Same rule the HTTP path applies to a provider code (upstream._CODE_SHAPE):
# an upstream must not get a sentence into the log, so a value that is not
# already code-shaped is dropped rather than recorded.
_CODE_SHAPE = re.compile(r'[A-Za-z0-9_.\-]{1,%d}' % MAX_DETAIL_CHARS)


def _bounded(value):
    """A short code-shaped scalar from provider metadata; never prose."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    text = str(value).strip()[:MAX_DETAIL_CHARS]
    return text if _CODE_SHAPE.fullmatch(text) else None


def _error_envelope(failure, event):
    """The provider's error object from either terminal envelope shape."""
    for source in (failure, event):
        candidate = source.get('error') if isinstance(source, dict) else None
        if isinstance(candidate, dict):
            return candidate
    return None


def _record_detail(metrics, kind, failure, event):
    """Record why the provider ended the stream, bounded to fixed metadata.

    A reason or code explains an Anthropic-style mid-stream refusal without
    ever logging the message text, which can quote prompt content.
    """
    metrics['terminal_event'] = kind
    if kind == 'response.incomplete':
        details = failure.get('incomplete_details') if isinstance(failure, dict) else None
        reason = details.get('reason') if isinstance(details, dict) else None
        value = _bounded(reason)
        if value:
            metrics['upstream_reason'] = value
        return
    envelope = _error_envelope(failure, event)
    if envelope is None:
        return
    value = _bounded(envelope.get('code')) or _bounded(envelope.get('error_type'))
    if value:
        metrics['upstream_code'] = value


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


def _prompt_refusal(failure, event):
    """OpenRouter's own provider-400 code, raised after the stream opened.

    The converted chat body was refused upstream and replaying it cannot
    succeed, so the client gets one actionable sentence instead of the
    provider's schema dump. The bounded code still reaches the log.
    """
    envelope = _error_envelope(failure, event)
    if envelope is None:
        return None
    codes = (_bounded(envelope.get('code')), _bounded(envelope.get('error_type')))
    return errors.upstream_invalid_prompt() if 'invalid_prompt' in codes else None


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
        _record_detail(metrics, kind, failure, event)
        refusal = None
        if kind != 'response.incomplete':
            refusal = errors.context_window() if context else _prompt_refusal(failure, event)
        if refusal is None:
            metrics['code'] = ('UPSTREAM_INCOMPLETE' if kind == 'response.incomplete'
                               else 'UPSTREAM_STREAM_FAILED')
        else:
            metrics['code'] = ('context_length_exceeded' if context
                               else 'UPSTREAM_INVALID_PROMPT')
        metrics.pop('served_model', None)
        if refusal is not None:
            frame = sse.frame(json.dumps({
                'type': 'response.failed', 'response': refusal.body()}).encode())
        yield frame
        return  # A terminal failure cannot be followed by a successful completion.
