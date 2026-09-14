"""Normalize external Responses terminal errors without changing success data."""
import json
import re
from . import errors, sse

_CONTEXT_MESSAGE = re.compile(
    r'The prompt is too long: ([0-9]{1,16}), model maximum context length: ([0-9]{1,16})')
MAX_DETAIL_CHARS = 64
# Which tier wrote the frame the client received. A provider terminal frame and
# the router's best-effort frame on a dead socket carry different evidence, and
# the log line cannot tell them apart without this field.
TERMINAL_FROM_UPSTREAM = 'upstream'
TERMINAL_FROM_ROUTER = 'router'
# Answers, not plumbing: frames whose bytes the client cannot un-see. A
# response.created or reasoning frame before a failure costs nothing to
# replace, while a text or tool-call delta is output the client already has.
# `normalize` records which of these it passed through, so the relay can tell
# the two apart without re-parsing a stream it has already forwarded.
ANSWER_FRAME_TYPES = frozenset((
    'response.output_text.delta', 'response.output_text.done',
    'response.function_call_arguments.delta',
    'response.function_call_arguments.done',
    'response.reasoning_summary_text.delta', 'response.reasoning_summary_text.done',
    'response.custom_tool_call_input.delta', 'response.custom_tool_call_input.done',
))


def _answer_item(event):
    """True for an output-item frame that carries an item the client keeps.

    `response.output_item.added`/`done` wrap every item kind, and a reasoning
    item is replaceable: the client shows it, but a retried attempt supersedes
    it the same way it supersedes a setup frame, so it must not block a retry.
    """
    item = event.get('item')
    return (isinstance(item, dict)
            and item.get('type') not in (None, 'reasoning'))
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


def _top_error_type(failure, event):
    """The top-level error_type, the canonical cause on the Responses skin."""
    for source in (failure, event):
        if not isinstance(source, dict):
            continue
        value = _bounded(source.get('error_type'))
        if value:
            return value
        envelope = source.get('error')
        if isinstance(envelope, dict):
            value = _bounded(envelope.get('error_type'))
            if value:
                return value
    return None


def _record_detail(metrics, kind, failure, event):
    """Record why the provider ended the stream, bounded to fixed metadata.

    A reason or code explains an Anthropic-style mid-stream refusal without
    ever logging the message text, which can quote prompt content.
    """
    metrics['terminal_event'] = kind
    metrics['terminal_source'] = TERMINAL_FROM_UPSTREAM
    if kind == 'response.incomplete':
        details = failure.get('incomplete_details') if isinstance(failure, dict) else None
        reason = details.get('reason') if isinstance(details, dict) else None
        value = _bounded(reason)
        if value:
            metrics['upstream_reason'] = value
        return
    envelope = _error_envelope(failure, event)
    if envelope is not None:
        value = _bounded(envelope.get('code')) or _bounded(envelope.get('error_type'))
        if value:
            metrics['upstream_code'] = value
        metadata = envelope.get('metadata')
        provider_code = (_bounded(metadata.get('provider_code'))
                         if isinstance(metadata, dict) else None)
        if provider_code:
            metrics['upstream_provider_code'] = provider_code
    error_type = _top_error_type(failure, event)
    if error_type:
        metrics['upstream_error_type'] = error_type
    endpoint = _terminal_endpoint(failure, event)
    if endpoint:
        metrics['serving_endpoint'] = endpoint


_ENDPOINT_SHAPE = re.compile(r'[A-Za-z0-9_.\-/]{1,%d}' % MAX_DETAIL_CHARS)


def _bounded_endpoint(value):
    """A code-shaped endpoint slug; never prose."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    text = str(value).strip()[:MAX_DETAIL_CHARS]
    return text if _ENDPOINT_SHAPE.fullmatch(text) else None


def metadata_endpoint(source, bounded):
    """First bounded provider from selected available[], then attempts[].

    Shared with `upstream.serving_endpoint`; the bounding rule stays with
    the caller so each log path keeps its own width.
    """
    metadata = source.get('openrouter_metadata') if isinstance(source, dict) else None
    if not isinstance(metadata, dict):
        return None
    endpoints = metadata.get('endpoints')
    available = (endpoints.get('available')
                 if isinstance(endpoints, dict) else None)
    if isinstance(available, list):
        for entry in available:
            if isinstance(entry, dict) and entry.get('selected') is True:
                value = bounded(entry.get('provider'))
                if value:
                    return value
    attempts = metadata.get('attempts')
    if isinstance(attempts, list):
        # The last attempt produced the terminal state; earlier entries name
        # providers that already failed over.
        for attempt in reversed(attempts):
            if isinstance(attempt, dict):
                value = bounded(attempt.get('provider'))
                if value:
                    return value
    return None


def _terminal_endpoint(failure, event):
    """Bounded serving endpoint from a terminal event's metadata, else None.

    Reads the same `openrouter_metadata` shapes `upstream.serving_endpoint`
    reads (selected `endpoints.available[]` entry, then `attempts[]`);
    local because `upstream` already imports this module.
    """
    for source in (failure, event):
        value = metadata_endpoint(source, _bounded_endpoint)
        if value:
            return value
    return None


_FINAL_ERROR_TYPES = frozenset((
    'invalid_request', 'refusal', 'moderation', 'insufficient_quota'))
_TRANSIENT_ERROR_TYPES = frozenset((
    'server_error', 'provider_unavailable', 'provider_overloaded',
    'timeout', 'server'))


def failure_class(failure, event):
    """'context' | 'final' | 'transient' from the canonical cause.

    Decided on the top-level error_type first (the Responses skin's code is
    a lossy collapse); an `invalid_prompt` code with no error_type is a
    deterministic refusal, and anything unrecognised is transient so an
    unknown provider death stays retryable.
    """
    if _context_error(failure) or _context_error(event):
        return 'context'
    error_type = _top_error_type(failure, event)
    if error_type in _FINAL_ERROR_TYPES:
        return 'final'
    if error_type in _TRANSIENT_ERROR_TYPES:
        return 'transient'
    envelope = _error_envelope(failure, event)
    code = (_bounded(envelope.get('code')) if isinstance(envelope, dict) else None)
    if code == 'invalid_prompt' and error_type is None:
        return 'final'
    return 'transient'


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
    provider's schema dump. The emitted code stays `invalid_prompt`: Codex
    classifies that as fatal, while an unknown code would be retried. The
    bounded code still reaches the log.
    """
    envelope = _error_envelope(failure, event)
    if envelope is None:
        return None
    codes = (_bounded(envelope.get('code')), _bounded(envelope.get('error_type')),
             _top_error_type(failure, event))
    if 'invalid_prompt' not in codes:
        return None
    return errors.upstream_invalid_prompt(code='invalid_prompt')


def normalize(chunks, metrics):
    """Keep HTTP status separate from the terminal event's inference outcome."""
    for frame, data in sse.blocks(sse.lines(chunks)):
        try:
            event = json.loads(data)
        except (ValueError, UnicodeDecodeError):
            metrics.pop('answer_frame', None)
            yield frame
            continue
        kind = event.get('type') if isinstance(event, dict) else None
        # Per frame, so a caller that stops reading cannot see a stale verdict.
        if kind in ANSWER_FRAME_TYPES or (kind in ('response.output_item.added',
                                                  'response.output_item.done')
                                         and _answer_item(event)):
            metrics['answer_frame'] = kind
        else:
            metrics.pop('answer_frame', None)
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
            metrics['failure_class'] = failure_class(failure, event)
            refusal = errors.context_window() if context else _prompt_refusal(failure, event)
        if refusal is None:
            metrics['code'] = ('UPSTREAM_INCOMPLETE' if kind == 'response.incomplete'
                               else 'UPSTREAM_STREAM_FAILED')
        else:
            metrics['code'] = ('context_length_exceeded' if context
                               else 'UPSTREAM_INVALID_PROMPT')
        metrics.pop('served_model', None)
        if refusal is not None:
            # The provider's frame is gone: this router wrote the one the
            # client reads, so the attribution must say so, while the bounded
            # upstream event and code stay as the reason.
            metrics['terminal_source'] = TERMINAL_FROM_ROUTER
            frame = sse.frame(json.dumps({
                'type': 'response.failed', 'response': refusal.body()}).encode())
        yield frame
        return  # A terminal failure cannot be followed by a successful completion.
