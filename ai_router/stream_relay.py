"""Stream forwarding, client-byte accounting and terminal outcome ownership."""
import json
import time

from . import (outcome, provider_defs, sse, stream_attempt, stream_errors,
               stream_events, transport)

TERMINAL_FIELDS = (
    'code', 'upstream_code', 'upstream_error_type', 'upstream_provider_code',
    'failure_class', 'terminal_event', 'upstream_reason', 'terminal_source',
    'serving_endpoint')


class StreamRecord:
    """Per-response byte counters, held frames and the settled outcome."""

    __slots__ = ('forwarded_bytes', 'content_delta_bytes', 'reasoning_bytes',
                 'hold', 'stream_retry', 'client_terminal', 'delivery_failed',
                 'outcome', 'normalized')

    def __init__(self):
        self.forwarded_bytes = 0
        self.content_delta_bytes = 0
        self.reasoning_bytes = 0
        self.outcome = None
        self.normalized = self.delivery_failed = False
        # One terminal source survives retries and late generic frames.
        self.client_terminal = None
        self.stream_retry = 0
        self.hold = stream_attempt.AttemptHold()

    def note_source(self, event):
        """Remember the writer of a terminal frame this attempt sent."""
        if event.source and self.client_terminal is None:
            self.client_terminal = event.source

    def flush(self, handler):
        """Write held frames in order; return True only when all left."""
        hold = self.hold
        if not hold.frames:
            return False
        held = hold.size()
        try:
            for frame in hold.frames:
                transport.write_full(handler.wfile, frame)
        except (OSError, ValueError) as exc:
            self.delivery_failed = exc
            if hold.terminal is not None:
                self.outcome = None
            return False
        self.forwarded_bytes += held
        self.reasoning_bytes += hold.reasoning
        # Preserve the source of any terminal frame that left this write.
        if hold.terminal is not None:
            self.client_terminal = hold.terminal
        hold.clear()
        return True


def streamed_metrics(record):
    """The counters every log line for this response carries."""
    unattributed = record.forwarded_bytes - record.content_delta_bytes - record.reasoning_bytes
    return {
        'forwarded_delta_bytes': record.forwarded_bytes,
        'content_delta_bytes': record.content_delta_bytes,
        'reasoning_delta_bytes': record.reasoning_bytes,
        'unattributed_delta_bytes': unattributed,
    }


def _raw_terminal(frame, metrics):
    """Classify one complete raw frame as a non-fatal observation."""
    return _raw_classify(frame, metrics, json.loads)


def _raw_hint(data, metrics):
    """Classify one complete oversized frame from its parsed event."""
    return _raw_classify(
        data, metrics,
        lambda payload: json.JSONDecoder().raw_decode(payload)[0])


def _raw_classify(data, metrics, decode):
    try:
        payload = b'\n'.join(
            line[5:].lstrip() for line in data.splitlines()
            if line.startswith(b'data:')).strip()
        event = decode(payload.decode())
        lifecycle = stream_events.classify(payload, event)
        native = event.get('type') if isinstance(event, dict) else None
        if metrics.get('protocol') == provider_defs.MESSAGES:
            if native == 'message_stop':
                lifecycle = stream_events.COMPLETED
            elif native in ('message_error', 'error'):
                lifecycle = stream_events.FAILURE
            else:
                lifecycle = stream_events.ANSWER
        return stream_errors.terminal_event(
            data, lifecycle, native, event, metrics,
            output_seen=False, rewrite=False)
    except Exception:
        return None


def _raw_events(chunks, metrics):
    pending = bytearray()
    emitted_pending = 0
    overflow = False
    for chunk in chunks:
        if not chunk:
            continue
        if overflow:
            yield stream_events.StreamEvent(chunk, stream_events.OPAQUE)
            continue
        pending.extend(chunk)
        rest, frames = sse.split_frames(pending)
        pending = bytearray(rest)
        prefix = emitted_pending
        for raw_frame in frames:
            frame = bytes(raw_frame)
            observed = (_raw_hint(frame, metrics)
                        if len(frame) > sse.MAX_FRAME_BYTES
                        else _raw_terminal(frame, metrics))
            if prefix:
                suffix = frame[prefix:]
                if suffix:
                    yield stream_events.StreamEvent(suffix, stream_events.OPAQUE)
                if observed is not None:
                    yield observed.with_frame(b'')
                prefix = 0
            elif observed is not None:
                yield observed
            else:
                yield stream_events.StreamEvent(frame, stream_events.OPAQUE)
        if frames:
            emitted_pending = 0
        if pending:
            tail = bytes(pending[emitted_pending:])
            if tail:
                yield stream_events.StreamEvent(tail, stream_events.OPAQUE)
            emitted_pending = len(pending)
        else:
            emitted_pending = 0
        if len(pending) > sse.MAX_FRAME_BYTES:
            pending.clear()
            emitted_pending = 0
            overflow = True


def relay_stream(handler, provider, response, prepared, metrics, started,
                 headers_done, record, *, attempt=None):
    """Forward one stream; normalized frames may wait for safe replay."""
    # Tool repair logs need request model/context without changing the request.
    attempt_metrics = {'model': metrics.get('model'),
                       'request_id': metrics.get('request_id'), 'attempt': attempt,
                       'context_tokens': metrics.get('context_tokens')}
    raw_encoded = metrics['response_encoding'] != 'identity'
    normalized = (provider.defn.dialect == provider_defs.DIALECT_OPENROUTER
                  and metrics.get('protocol') == provider_defs.RESPONSES
                  and metrics['response_kind'] == 'sse'
                  and metrics['response_encoding'] == 'identity')
    record.normalized = normalized
    terminal_metrics = None
    chunks = (transport.passthrough(response) if raw_encoded
              else provider.adapt(response, prepared.tool_names, attempt_metrics))
    if raw_encoded:
        frames = (stream_events.StreamEvent(chunk, stream_events.OPAQUE)
                  for chunk in chunks)
    elif normalized:
        frames = stream_errors.events(chunks, attempt_metrics)
    elif metrics['response_kind'] == 'sse':
        frames = _raw_events(chunks, metrics)
    else:
        frames = (stream_events.StreamEvent(chunk, stream_events.ANSWER)
                  for chunk in chunks)
    try:
        for event in frames:
            if 'first_chunk_ms' not in metrics:
                metrics['first_chunk_ms'] = round((time.monotonic() - started) * 1000, 1)
            transport.note_first_data(metrics, headers_done)
            held = normalized and not record.forwarded_bytes and record.hold.take(event)
            settled_now = event.outcome is not None and record.outcome is None
            if settled_now:
                terminal_metrics = {key: metrics.get(key) for key in TERMINAL_FIELDS}
                if held:
                    record.outcome = event.outcome
            if not event.frame:
                if settled_now:
                    record.outcome = event.outcome
                    record.note_source(event)
                continue
            # Forwarded bytes commit the attempt and disable replay.
            if held:
                continue
            if record.hold.frames and not record.flush(handler):
                raise record.delivery_failed or OSError('held frame delivery failed')
            try:
                transport.write_full(handler.wfile, event.frame)
            except (OSError, ValueError) as exc:
                record.delivery_failed = exc
                raise
            transport.note_first_write(metrics, headers_done)
            metrics.setdefault('time_to_first_delta_ms', round((time.monotonic() - started) * 1000, 1))
            record.forwarded_bytes += len(event.frame)
            if settled_now:
                record.outcome = event.outcome
                record.note_source(event)
            if event.kind == stream_events.ANSWER:
                record.content_delta_bytes += len(event.frame)
            elif event.kind == stream_events.REASONING:
                record.reasoning_bytes += len(event.frame)
        if metrics['response_kind'] != 'sse':
            # A complete non-SSE body has no terminal frame; EOF is its success.
            record.outcome = outcome.Outcome(outcome.SUCCESS, outcome.STATUS, outcome.UPSTREAM)
    finally:
        # Keep request model/context facts when attempt facts merge back.
        attempt_metrics.pop('model', None)
        if terminal_metrics is not None:
            clear_terminal_fields(metrics)
            metrics.update({key: value for key, value in terminal_metrics.items() if value is not None})
        # Only a terminal frame claims a source; clean completion has none.
        if record.client_terminal:
            metrics['terminal_source'] = record.client_terminal
        elif attempt_metrics.get('terminal_event'):
            metrics['terminal_source'] = (attempt_metrics.get('terminal_source')
                                          or stream_errors.TERMINAL_FROM_ROUTER)
        else:
            metrics.pop('terminal_source', None)
        # Merge attempt facts back; retry callers clear verdict fields first.
        metrics.update(attempt_metrics)


def clear_terminal_fields(metrics):
    """Drop the failed attempt's verdict before the retry overwrites it."""
    for key in TERMINAL_FIELDS:
        metrics.pop(key, None)
