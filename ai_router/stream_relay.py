"""Stream forwarding, client-byte accounting and terminal outcome ownership."""
import json
import time

from . import (messages_events, outcome, provider_defs, request_evidence, sse, stream_attempt, stream_errors,
               stream_events, transport)

TERMINAL_FIELDS = (
    'code', 'upstream_code', 'upstream_error_type', 'upstream_provider_code',
    'failure_class', 'terminal_event', 'upstream_reason', 'terminal_source',
    'serving_endpoint')


class StreamRecord:
    """Per-response byte counters, held frames and the settled outcome."""

    __slots__ = ('forwarded_bytes', 'content_delta_bytes', 'reasoning_bytes',
                 'hold', 'stream_retry', 'client_terminal', 'delivery_failed',
                 'outcome', 'normalized', 'replay_blocked')

    def __init__(self):
        self.forwarded_bytes = 0
        self.content_delta_bytes = 0
        self.reasoning_bytes = 0
        self.outcome = None
        self.normalized = self.delivery_failed = False
        self.replay_blocked = False
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


def _raw_terminal(frame, metrics, decoder=None):
    """Classify one complete raw frame as a non-fatal observation."""
    return _raw_classify(frame, metrics, json.loads, decoder)


def _raw_hint(data, metrics, decoder=None):
    """Classify one complete oversized frame from its parsed event."""
    return _raw_classify(
        data, metrics,
        json.loads if decoder else lambda payload: json.JSONDecoder().raw_decode(payload)[0], decoder)


def _raw_classify(data, metrics, decode, decoder):
    try:
        payload = b'\n'.join(
            line[5:].lstrip() for line in data.splitlines()
            if line.startswith(b'data:')).strip()
        event = decode(payload.decode())
        if decoder is not None:
            return decoder.observe(data, event, metrics)
        lifecycle = stream_events.classify(payload, event)
        native = event.get('type') if isinstance(event, dict) else None
        return stream_errors.terminal_event(
            data, lifecycle, native, event, metrics,
            output_seen=False, rewrite=False)
    except Exception:
        return None


def _raw_events(chunks, metrics):
    decoder = messages_events.Decoder() if metrics.get('protocol') == provider_defs.MESSAGES else None
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
            observed = (_raw_hint(frame, metrics, decoder)
                        if len(frame) > sse.MAX_FRAME_BYTES
                        else _raw_terminal(frame, metrics, decoder))
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
                       'attempt_evidence': metrics.get('attempt_evidence'),
                       'request_id': metrics.get('request_id'), 'attempt': attempt,
                       'context_tokens': metrics.get('context_tokens')}
    raw_encoded = metrics['response_encoding'] != 'identity'
    # Native Responses can stream without declaring an SSE content type.
    streamed = (metrics['response_kind'] == 'sse'
                or (metrics.get('stream') is True and metrics['response_kind'] == 'other'
                    and metrics.get('protocol') == provider_defs.RESPONSES))
    messages_external = (metrics.get('protocol') == provider_defs.MESSAGES
                         and provider.defn.kind == provider_defs.EXTERNAL
                         and metrics.get('path') == '/v1/messages')
    normalized = ((messages_external or provider.defn.dialect == provider_defs.DIALECT_OPENROUTER
                  and metrics.get('protocol') == provider_defs.RESPONSES
                   ) and metrics['response_kind'] == 'sse'
                  and metrics['response_encoding'] == 'identity')
    record.normalized = normalized
    messages_json = (metrics.get('protocol') == provider_defs.MESSAGES
                     and metrics.get('path') == '/v1/messages'
                     and metrics['response_kind'] == 'json')
    terminal_metrics = None
    chunks = (transport.passthrough(response) if raw_encoded
              else provider.adapt(response, prepared.tool_names, attempt_metrics))
    if raw_encoded:
        frames = (stream_events.StreamEvent(chunk, stream_events.OPAQUE)
                  for chunk in chunks)
    elif normalized and messages_external:
        frames = provider.events(response, metrics)
    elif normalized:
        frames = stream_errors.events(chunks, attempt_metrics)
    elif streamed:
        frames = _raw_events(chunks, metrics)
    elif messages_json:
        frames = messages_events.json_events(chunks, metrics)
    else:
        kind = stream_events.ANSWER if metrics['response_kind'] == 'json' else stream_events.OPAQUE
        frames = (stream_events.StreamEvent(chunk, kind)
                  for chunk in chunks)
    try:
        for event in frames:
            if 'first_chunk_ms' not in metrics:
                metrics['first_chunk_ms'] = round((time.monotonic() - started) * 1000, 1)
            transport.note_first_data(metrics, headers_done)
            record.replay_blocked |= event.commit
            held = normalized and not (record.forwarded_bytes or record.replay_blocked) and record.hold.take(event)
            settled_now = event.outcome is not None and record.outcome is None
            if settled_now:
                request_evidence.verdict(metrics, event.outcome)
                terminal_metrics = {key: metrics.get(key) for key in TERMINAL_FIELDS}
                if held:
                    record.outcome = event.outcome
            if not held and record.hold.frames and not record.flush(handler):
                raise record.delivery_failed or OSError('held frame delivery failed')
            if not event.frame:
                if settled_now:
                    record.outcome = event.outcome
                    record.note_source(event)
                continue
            if held:
                continue
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
        if metrics['response_kind'] == 'json' and not raw_encoded and not messages_json:
            # Known non-stream JSON keeps its EOF rule; opaque data proves no outcome.
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
