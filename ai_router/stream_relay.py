"""One upstream stream: what the client received and whether to retry it.

Leaf for `relay.py`, the same way `stream_errors.py` is: no dispatch, no
credentials, no provider construction. It owns three decisions that only make
sense together, so a reader never has to hold one without the others:

- what the client received, counted by kind (`StreamRecord`),
- that frames a retry would replace wait in `stream_attempt.AttemptHold`
  until the attempt commits or ends, so a retry replaces them instead of
  appending a second copy (`relay_stream`),
- when one retry is safe (`retryable_stream_failure`): the provider failed the
  turn before any byte of the attempt reached the client, the code says the
  provider failed rather than refused the request, and the request offers no
  tool upstream runs itself,
- how that retry opens (`reopen_stream`): the client already holds a 200
  text/event-stream header block, so a non-200 or non-SSE answer cannot be
  appended and the retry is refused instead.

`log_event` stays injected by the caller for the same reason it does in
`relay.py`: a test patching `ai_router.router.log_event` must keep seeing
these events.
"""
import http.client
import time

from . import provider_defs, stream_attempt, stream_errors, stream_events, transport


class StreamRecord:
    """Per-response stream state the log line reports.

    `forwarded_bytes` is everything the client received, `content_delta_bytes`
    is how much of that was answer rather than plumbing, `reasoning_bytes` is
    how much of the plumbing was reasoning, `client_terminal` is which tier
    wrote the terminal frame the client holds, `hold` is the uncommitted
    attempt's frames, and `stream_retry` is whether the caller re-opened the
    upstream once.
    """

    __slots__ = ('forwarded_bytes', 'content_delta_bytes', 'reasoning_bytes',
                 'hold', 'stream_retry', 'client_terminal')

    def __init__(self):
        self.forwarded_bytes = 0
        self.content_delta_bytes = 0
        self.reasoning_bytes = 0
        # Which tier wrote the terminal frame the client holds, or None while it
        # holds none. One durable fact: a retry can neither re-attribute it nor
        # add a second frame, and a death after one never appends a generic
        # frame over the verdict the client already read.
        self.client_terminal = None
        self.stream_retry = 0
        self.hold = stream_attempt.AttemptHold()

    def note_source(self, event):
        """Remember the writer of a terminal frame this attempt sent."""
        if event.source:
            self.client_terminal = event.source

    def flush(self, handler):
        """Write the held frames in order; a retry clears them instead.

        Best-effort: a client that already closed its socket must not turn this
        into an exception inside the relay's error path, which would skip the
        log line and the terminal frame. Returns True only when every held
        byte actually left, so a caller never reports a frame the client
        missed.
        """
        hold = self.hold
        if not hold.frames:
            return False
        held = hold.size()
        try:
            for frame in hold.frames:
                handler.wfile.write(frame)
            handler.wfile.flush()
        except (OSError, ValueError):
            return False
        self.forwarded_bytes += held
        self.reasoning_bytes += hold.reasoning
        # The caller must know a terminal frame left in this write: it may
        # not append its own generic one on top of the provider's verdict.
        if hold.terminal is not None:
            self.client_terminal = hold.terminal
        hold.clear()
        return True


def streamed_metrics(record):
    """The counters every log line for this response carries."""
    unattributed = (record.forwarded_bytes - record.content_delta_bytes
                    - record.reasoning_bytes)
    return {'forwarded_delta_bytes': record.forwarded_bytes,
            'content_delta_bytes': record.content_delta_bytes,
            'reasoning_delta_bytes': record.reasoning_bytes,
            'unattributed_delta_bytes': unattributed}


def relay_stream(handler, provider, response, prepared, metrics, started,
                 headers_done, record):
    """Forward one upstream stream and record what the client received.

    Until the attempt commits, each frame is offered to `record.hold`: setup,
    reasoning and a failure terminal wait there, so an attempt the provider
    fails before any answer leaves nothing behind and the caller's retry
    replaces it whole. The first frame the hold refuses commits the attempt:
    the held frames go out in order, then that frame, and every later frame
    streams straight through. Only the normalizing path can classify frames;
    any other stream forwards every chunk as answer.

    The terminal-source rule: `stream_errors.events` marks a terminal frame
    the provider sent before yielding it, so this leaf only claims the frame
    when it is still unclaimed after the upstream body ended -- that residue is
    the router's own best-effort frame on a socket that died mid-stream.
    """
    # Adapters hand this mapping to the tool repair helpers, whose log lines
    # carry the model; the request metrics are the only place it exists.
    attempt_metrics = {'model': metrics.get('model'),
                       'context_tokens': metrics.get('context_tokens')}
    chunks = provider.adapt(response, prepared.tool_names, attempt_metrics)
    normalized = (provider.defn.dialect == provider_defs.DIALECT_OPENROUTER
                  and metrics.get('protocol') == provider_defs.RESPONSES
                  and metrics['response_kind'] == 'sse'
                  and metrics['response_encoding'] == 'identity')
    frames = (stream_errors.events(chunks, attempt_metrics) if normalized else
              (stream_events.StreamEvent(chunk, stream_events.ANSWER) for chunk in chunks))
    delivered = False
    try:
        for event in frames:
            if 'first_chunk_ms' not in metrics:
                metrics['first_chunk_ms'] = round((time.monotonic() - started) * 1000, 1)
            transport.note_first_data(metrics, headers_done)
            # A retry is only ever decided with nothing forwarded, so an
            # attempt that wrote any byte has committed and holds no more.
            if not record.forwarded_bytes and record.hold.take(event):
                continue
            record.flush(handler)
            handler.wfile.write(event.frame)
            handler.wfile.flush()
            transport.note_first_write(metrics, headers_done)
            metrics.setdefault('time_to_first_delta_ms', round(
                (time.monotonic() - started) * 1000, 1))
            record.forwarded_bytes += len(event.frame)
            record.note_source(event)
            delivered = delivered or record.client_terminal is not None
            if event.kind == stream_events.ANSWER:
                record.content_delta_bytes += len(event.frame)
            elif event.kind == stream_events.REASONING:
                record.reasoning_bytes += len(event.frame)
    finally:
        # The request model is request facts, not an attempt verdict: the
        # caller's mapping must not lose it when the attempt state is merged.
        attempt_metrics.pop('model', None)
        # Only a stream that ended with a terminal frame has a source, and a
        # clean completion never claims one.
        if delivered:
            metrics['terminal_source'] = record.client_terminal
        elif attempt_metrics.get('terminal_event'):
            metrics['terminal_source'] = (attempt_metrics.get('terminal_source')
                                          or stream_errors.TERMINAL_FROM_ROUTER)
        else:
            metrics.pop('terminal_source', None)
        # Decision fields stay in `metrics` for the log line; the caller clears
        # them before a retry so the second attempt cannot inherit the first's
        # verdict. Adapters only ever write to this mapping, so merging it back
        # keeps the success path unchanged.
        metrics.update(attempt_metrics)


def code_of(metrics):
    """The code-shaped verdict this attempt recorded, or None."""
    return stream_errors._bounded(metrics.get('upstream_code') or metrics.get('code'))


def retryable_stream_failure(metrics, record, body):
    """True only for a provider terminal frame before any answer reached the client.

    A retry re-runs the whole request, so it is safe exactly when the client
    has no answer frames to duplicate, the terminal frame came from the
    provider, the provider's own code says it failed the turn rather than
    refusing the request, and the prepared `body` offers no tool upstream
    may already have run (`stream_attempt.replay_safe`, checked last so only
    an otherwise retryable failure reads it). A deterministic refusal would
    fail again, and a post-answer death belongs to the client's turn retry,
    which can switch models.
    """
    # Any byte already flushed blocks the retry, not just answer frames: a
    # second response.created appended after bytes the client holds would give
    # one stream two response identities, whatever those bytes contained.
    return (record.forwarded_bytes == 0
            and metrics.get('terminal_source') == stream_errors.TERMINAL_FROM_UPSTREAM
            and metrics.get('code') == 'UPSTREAM_STREAM_FAILED'
            and metrics.get('failure_class') == 'transient'
            and code_of(metrics) not in (None, 'invalid_prompt',
                                         'context_length_exceeded')
            and stream_attempt.replay_safe(body))


def clear_terminal_fields(metrics):
    """Drop the failed attempt's verdict before the retry overwrites it."""
    for key in ('code', 'upstream_code', 'upstream_error_type', 'upstream_provider_code',
                'failure_class', 'terminal_event', 'upstream_reason',
                'terminal_source', 'serving_endpoint'):
        metrics.pop(key, None)


def reopen_stream(prepared, metrics, attempts, started):
    """Second attempt for a stream the provider failed before it committed.

    Phase timings belong to the first attempt; leaving them out of the retry's
    metrics would silently drop the connect/send numbers the log already had,
    so they are carried over rather than overwritten. The caller owns
    `attempts`, so a reopened connection never outlives the request.
    """
    phases = {key: metrics[key] for key in
              ('connect_ms', 'send_ms', 'headers_ms') if key in metrics}
    fresh = http.client.HTTPSConnection(prepared.host, timeout=120)
    try:
        response, headers_done = transport.post_with_phases(
            fresh, prepared, metrics)
    except BaseException:
        metrics.update(phases)
        fresh.close()
        raise
    attempts.append(fresh)
    metrics.update(phases)
    # The client's status line and headers are already 200 text/event-stream,
    # so the retry cannot become a JSON reply: raw bytes there are not an SSE
    # frame, and a non-identity encoding cannot be appended to what the client
    # is decoding. Close the attempt instead, which lets the relay's error
    # path end the body with a terminal frame and record why the retry failed.
    if response.status != 200:
        response.read()
        metrics['retry_code'] = 'retry_http_%d' % response.status
        raise ValueError('upstream refused the retry')
    kind, encoding = transport.describe_response(response)
    if (kind, encoding) != ('sse', 'identity'):
        metrics['retry_code'] = 'retry_%s_%s' % (kind, encoding)
        raise ValueError('upstream answered the retry with a different body')
    # Cumulative from the original request start: the retry's own connect,
    # upload and header wait belong in the field, and the restored first
    # attempt's phases must not be counted twice.
    metrics['upstream_headers_ms'] = round((headers_done - started) * 1000, 1)
    metrics['response_kind'], metrics['response_encoding'] = kind, encoding
    return response, headers_done
