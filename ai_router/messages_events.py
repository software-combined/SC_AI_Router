"""Read-only Messages lifecycle observation shared by both billing routes.

The adapter owns compatibility repairs; this observer never rewrites a frame.
A stop frame needs a valid start and final stop reason. Unknown events remain
opaque, and the first terminal verdict owns the rest of this response.
"""
import json

from . import outcome, stream_errors, stream_events as events, transport

STOP_REASONS = {
    'end_turn': outcome.SUCCESS, 'stop_sequence': outcome.SUCCESS,
    'tool_use': outcome.SUCCESS, 'max_tokens': outcome.INCOMPLETE,
    'pause_turn': outcome.INCOMPLETE, 'refusal': outcome.REFUSED,
    'model_context_window_exceeded': outcome.CONTEXT_OVERFLOW,
}


def _message(value):
    return (isinstance(value, dict) and value.get('type') == 'message'
            and value.get('role') == 'assistant' and isinstance(value.get('content'), list)
            and all(isinstance(block, dict) for block in value['content']))


def _terminal(frame, native, reason, valid, output, metrics, phase=outcome.STREAM):
    reason = reason if isinstance(reason, str) and reason in STOP_REASONS else None
    category = STOP_REASONS[reason] if valid and reason is not None else outcome.UNKNOWN
    failed = category != outcome.SUCCESS
    if failed:
        failure_class = ('unknown' if category == outcome.UNKNOWN else 'context'
                         if category == outcome.CONTEXT_OVERFLOW else 'final')
        metrics.update(terminal_event=native, failure_class=failure_class)
        if reason is not None:
            metrics['upstream_reason'] = reason
    return events.StreamEvent(
        frame, events.FAILURE if failed else events.COMPLETED, native,
        outcome.UPSTREAM if failed else None, output,
        outcome.Outcome(category, phase, outcome.UPSTREAM, reason, output))


class Decoder:
    """One response's state, independent of logging and attempt authority."""

    def __init__(self):
        self.started = self.closed = self.output = False
        self.valid = True
        self.reason = None

    def observe(self, frame, event, metrics):
        native = event.get('type') if isinstance(event, dict) else None
        kind = events.OPAQUE
        if self.closed or not isinstance(native, str):
            return events.StreamEvent(frame, kind)
        if native in ('error', 'message_error'):
            self.closed = True
            # Keep the legacy event name on the wire, while the shared cause
            # parser reads its nested error rather than that lifecycle label.
            return stream_errors.terminal_event(
                frame, events.FAILURE, native, {**event, 'type': 'error'}, metrics,
                output_seen=self.output, rewrite=False)
        if native == 'message_stop':
            self.closed = True
            return _terminal(frame, native, self.reason, self.started and self.valid,
                             self.output, metrics)
        if native == 'message_start':
            message = event.get('message')
            self.valid &= (not self.started and _message(message)
                           and message['content'] == [] and message.get('stop_reason') is None)
            self.started = True
            kind = events.SETUP if self.valid else events.OPAQUE
        elif native == 'message_delta':
            delta = event.get('delta')
            if not self.started or not isinstance(delta, dict):
                self.valid = False
            else:
                reason = delta.get('stop_reason')
                if reason is not None:
                    self.valid &= (isinstance(reason, str)
                                   and (self.reason is None or reason == self.reason))
                    self.reason = reason
                kind = events.PLUMBING if self.valid else events.OPAQUE
        elif native in ('ping', 'content_block_stop'):
            kind = events.PLUMBING
        elif native in ('content_block_start', 'content_block_delta'):
            block = event.get('content_block' if native == 'content_block_start' else 'delta')
            subtype = block.get('type') if isinstance(block, dict) else None
            if subtype in ('text', 'text_delta', 'tool_use', 'input_json_delta'):
                kind = events.ANSWER
                self.output = True
            elif subtype in ('thinking', 'thinking_delta'):
                kind = events.REASONING
        return events.StreamEvent(frame, kind, native)


def json_events(chunks, metrics):
    """Observe bounded JSON after forwarding its bytes immediately."""
    pending = bytearray()
    overflow = False
    for chunk in chunks:
        if not overflow:
            if len(pending) + len(chunk) > transport.MAX_UPSTREAM_BODY:
                pending.clear()
                overflow = True
            else:
                pending.extend(chunk)
        yield events.StreamEvent(chunk, events.OPAQUE)
    if overflow:
        return
    try:
        message = json.loads(pending)
    except (ValueError, UnicodeDecodeError, RecursionError):
        return
    if not _message(message):
        return
    yield _terminal(b'', 'message', message.get('stop_reason'), True,
                    bool(message['content']), metrics, outcome.STATUS)
