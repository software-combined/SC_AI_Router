"""Normalize external Responses terminal errors without changing success data."""
import json
import re
from . import errors, outcome, sse, stream_events

_CONTEXT_MESSAGE = re.compile(
    r'The prompt is too long: ([0-9]{1,16}), model maximum context length: ([0-9]{1,16})')
MAX_DETAIL_CHARS = 64
TERMINAL_FROM_UPSTREAM = 'upstream'
TERMINAL_FROM_ROUTER = 'router'
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
        # Provider envelopes use top-level `type`; event lifecycle never does.
        value = _bounded(source.get('type'))
        if (source is failure and value
                and value not in stream_events.FAILURE_TYPES
                and value != 'response.completed'):
            return value
        envelope = source.get('error')
        if isinstance(envelope, dict):
            value = (_bounded(envelope.get('error_type'))
                     or _bounded(envelope.get('type')))
            if value:
                return value
    return None


def error_codes(failure, event, depth=0):
    values = []
    for source in (failure, event):
        if not isinstance(source, dict):
            continue
        values += [_bounded(source.get(key)) for key in ('error_type', 'code')]
        top_type = _bounded(source.get('type'))
        if (source is failure and top_type
                and top_type not in stream_events.FAILURE_TYPES
                and top_type != 'response.completed'):
            values.append(top_type)
        envelope = source.get('error')
        if not isinstance(envelope, dict):
            continue
        values += [_bounded(envelope.get(key))
                   for key in ('code', 'error_type', 'type')]
        metadata = envelope.get('metadata')
        if not isinstance(metadata, dict):
            continue
        values.append(_bounded(metadata.get('provider_code')))
        raw = metadata.get('raw')
        if isinstance(raw, str) and depth < 2:
            try:
                nested = json.loads(raw)
                values += error_codes(nested, nested, depth + 1)
            except (ValueError, TypeError):
                pass
    return tuple(dict.fromkeys(value for value in values if value))


def record_detail(metrics, kind, failure, event):
    """Record bounded terminal metadata, never provider message text."""
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
    """First bounded provider from selected available[], then attempts[]."""
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
        for attempt in reversed(attempts):
            if isinstance(attempt, dict):
                value = bounded(attempt.get('provider'))
                if value:
                    return value
    return None


def _terminal_endpoint(failure, event):
    """Bounded serving endpoint from terminal metadata, else None."""
    for source in (failure, event):
        value = metadata_endpoint(source, _bounded_endpoint)
        if value:
            return value
    return None


def failure_class(failure, event):
    """Class name from the shared cause; unknown is never replayable."""
    category = _category_from_causes(failure, event)
    return ('context' if _context_error(failure) or _context_error(event)
            else 'transient' if category == outcome.TRANSIENT
            else 'unknown' if category == outcome.UNKNOWN else 'final')


def _context_error(data, depth=0):
    """Explicit codes or the exact numeric refusal in an error envelope."""
    if not isinstance(data, dict):
        return False
    if 'context_length_exceeded' in error_codes(data, data):
        return True
    error = data.get('error')
    if not isinstance(error, dict):
        return False
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
    """Rewrite OpenRouter's provider-400 `invalid_prompt` as one safe line."""
    envelope = _error_envelope(failure, event)
    if envelope is None:
        return None
    codes = error_codes(failure, event)
    if 'invalid_prompt' not in codes:
        return None
    return errors.upstream_invalid_prompt(code='invalid_prompt')

def terminal_code(kind, failure, event, generic_terminal=False):
    """Canonical terminal code for raw and normalized stream observations."""
    return ('UPSTREAM_INCOMPLETE' if kind == 'response.incomplete' else
            'UPSTREAM_STREAM_FAILED' if generic_terminal
            else 'context_length_exceeded' if _context_error(failure) or _context_error(event)
            else 'UPSTREAM_INVALID_PROMPT' if _prompt_refusal(failure, event) is not None else 'UPSTREAM_STREAM_FAILED')


def terminal_event(frame, lifecycle, kind, event, metrics, *,
                   output_seen=False, rewrite=True):
    """Classify one parsed event through the shared terminal policy.

    `rewrite=False` keeps a raw provider frame byte-for-byte while retaining
    the same verdict fields a normalized frame would settle.
    """
    response = event.get('response') if isinstance(event, dict) else None
    terminal_output = bool(
        isinstance(response, dict) and response.get('output'))
    if lifecycle != stream_events.FAILURE:
        settled = (outcome.Outcome(
            outcome.SUCCESS, outcome.STREAM, outcome.UPSTREAM,
            output=output_seen or terminal_output)
            if lifecycle == stream_events.COMPLETED else None)
        return stream_events.StreamEvent(
            frame, lifecycle, kind, output=terminal_output, outcome=settled, setup_slot=(stream_events.SETUP_ORDER.index(kind)
                        if lifecycle == stream_events.SETUP else None))

    failure = stream_events.failure_for(kind, event)
    context = (kind != 'response.incomplete'
               and (_context_error(failure) or _context_error(event)))
    record_detail(metrics, kind, failure, event)
    refusal = None
    generic_terminal = False
    metrics['failure_class'] = ('final' if kind == 'response.incomplete'
                                else failure_class(failure, event))
    if kind != 'response.incomplete':
        refusal = errors.context_window() if context else _prompt_refusal(failure, event)
        if refusal is None and kind == 'response.completed':
            # Never let a malformed completion reach a type-driven client.
            refusal = errors.upstream_failed()
            generic_terminal = True
    metrics['code'] = terminal_code(kind, failure, event, generic_terminal)
    metrics.pop('served_model', None)
    terminal_output = bool(
        event.get('output') or (isinstance(failure, dict)
                                and failure.get('output')))
    if refusal is not None and rewrite:
        source = TERMINAL_FROM_ROUTER
        metrics['terminal_source'] = source
        body = refusal.body()
        if terminal_output:
            body['output'] = (event.get('output')
                              if event.get('output') is not None
                              else failure.get('output'))
        frame = sse.frame(json.dumps({
            'type': 'response.failed', 'response': body}).encode())
    else:
        source = TERMINAL_FROM_UPSTREAM
    category = (outcome.INCOMPLETE if kind == 'response.incomplete'
                else outcome.CONTEXT_OVERFLOW if context
                else outcome.UNKNOWN if generic_terminal
                else outcome.REFUSED if refusal is not None
                else _category_from_causes(failure, event))
    settled = outcome.Outcome(
        category, outcome.STREAM, source,
        (outcome.code_for(category, _top_error_type(failure, event),
                          error_codes(failure, event))
         or metrics.get('upstream_reason')),
        output_seen or terminal_output)
    return stream_events.StreamEvent(
        frame, lifecycle, kind, source, terminal_output, settled)


def events(chunks, metrics):
    """Yield each frame once with its lifecycle and terminal outcome."""
    output_seen = success_seen = False
    for frame, data in sse.blocks(sse.lines(chunks)):
        try:
            event = json.loads(data)
        except (ValueError, UnicodeDecodeError):
            event = None
        lifecycle = stream_events.classify(data, event)
        kind = event.get('type') if isinstance(event, dict) else None
        if success_seen and lifecycle in (
                stream_events.FAILURE, stream_events.ANSWER,
                stream_events.REASONING, stream_events.SETUP):
            continue
        observed = terminal_event(
            frame, lifecycle, kind, event, metrics,
            output_seen=output_seen, rewrite=True)
        if lifecycle != stream_events.FAILURE:
            output_seen = (output_seen or lifecycle == stream_events.ANSWER
                           or observed.output)
            yield observed
            if lifecycle == stream_events.COMPLETED:
                success_seen = True
            continue
        yield observed
        return


def _category_from_causes(failure, event):
    """Shared category from the canonical error type and native codes."""
    return outcome.category_for(_top_error_type(failure, event),
                                error_codes(failure, event))


def normalize(chunks, metrics):
    """The frame bytes of `events`, for a caller that only forwards them."""
    for event in events(chunks, metrics):
        yield event.frame
