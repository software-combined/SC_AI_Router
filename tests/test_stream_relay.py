"""Stream records, replay rejection, and raw terminal observations."""
import gzip
import io
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from compression import zstd

from ai_router import (attempt_policy, outcome, provider_defs, providers, relay, sse,
                       stream_errors, stream_events, stream_relay, transport)

SAFE = b'{"tools": [{"type": "function", "name": "exec"}]}'
EXTERNAL = providers.ExternalResponsesProvider(provider_defs.get(provider_defs.DEFAULT_EXTERNAL))
TRANSIENT = outcome.Outcome(outcome.TRANSIENT, outcome.STREAM, outcome.UPSTREAM, 'server_error')


def settled(event):
    frame = sse.frame(json.dumps(event).encode())
    return list(stream_errors.events([frame], {}))[-1].outcome


class RetryDecisionTests(unittest.TestCase):
    def rejection(self, settled_outcome=TRANSIENT, record=None, body=SAFE):
        ledger = attempt_policy.Ledger(EXTERNAL, {'protocol': provider_defs.RESPONSES})
        record = record or stream_relay.StreamRecord()
        return attempt_policy.replay_rejection(ledger, settled_outcome, record, body)

    def test_provider_failure_without_answer_is_retryable(self):
        self.assertIsNone(self.rejection())

    def test_any_forwarded_byte_blocks_the_retry(self):
        record = stream_relay.StreamRecord()
        # An answer frame is the obvious case; a flushed plumbing frame counts
        # too, because a second response.created after it would give one stream
        # two response identities.
        record.content_delta_bytes = 12
        record.forwarded_bytes = 12
        self.assertEqual(self.rejection(record=record), 'committed')

    def test_flushed_plumbing_alone_blocks_the_retry(self):
        record = stream_relay.StreamRecord()
        record.forwarded_bytes = 70000
        self.assertEqual(self.rejection(record=record), 'committed')

    def test_router_synthesised_frame_is_not_retried(self):
        routed = outcome.Outcome(outcome.TRANSIENT, outcome.STREAM, outcome.ROUTER)
        self.assertEqual(self.rejection(routed), 'router_terminal')

    def test_deterministic_and_reason_only_failures_are_not_retried(self):
        cases = {
            outcome.REFUSED: {'type': 'response.failed', 'response': {
                'error': {'code': 'invalid_prompt'}}},
            outcome.INCOMPLETE: {'type': 'response.incomplete', 'response': {
                'incomplete_details': {'reason': 'max_output_tokens'}}},
            outcome.CONTEXT_OVERFLOW: {'type': 'response.failed', 'response': {
                'error': {'code': 'context_length_exceeded'}}},
            outcome.QUOTA: {'type': 'response.failed', 'response': {
                'error_type': 'insufficient_quota', 'error': {'code': 'server_error'}}},
        }
        for category, event in cases.items():
            with self.subTest(category=category):
                classified = settled(event)
                self.assertEqual(classified.category, category)
                self.assertEqual(self.rejection(classified), 'not_transient')

    def test_an_unnamed_provider_failure_is_unknown_and_not_replayed(self):
        event = {'type': 'response.failed', 'response': {'error': {'code': 'overloaded'}}}
        self.assertEqual(settled(event).category, outcome.TRANSIENT)
        self.assertIsNone(self.rejection(settled(event)))

        unknown = {'type': 'response.failed', 'response': {
            'error': {'code': 'bad_schema'}}}
        self.assertEqual(settled(unknown).category, outcome.UNKNOWN)
        self.assertEqual(self.rejection(settled(unknown)), 'not_transient')

    def test_hosted_tool_blocks_an_otherwise_retryable_failure(self):
        hosted = b'{"tools": [{"type": "function"}, {"type": "web_search"}]}'
        self.assertEqual(self.rejection(body=hosted), 'side_effects')

    def test_a_stream_with_no_terminal_frame_is_unknown_and_not_retried(self):
        ledger = attempt_policy.Ledger(EXTERNAL, {'protocol': provider_defs.RESPONSES})
        self.assertFalse(ledger.replay(stream_relay.StreamRecord(), SAFE))
        self.assertEqual(ledger.outcome.category, outcome.UNKNOWN)
        self.assertFalse(ledger.outcome.replayable)
        self.assertEqual(ledger.decisions, [])


class HeldFrameTests(unittest.TestCase):
    class _Client:
        def __init__(self):
            self.wfile = self
            self.written = bytearray()

        def write(self, data):
            self.written += data

        def flush(self):
            pass

    def test_flush_writes_held_bytes_once(self):
        client = self._Client()
        record = stream_relay.StreamRecord()
        held = b'data: {"type": "response.created", "response": {"id": "r"}}\n\n'
        self.assertTrue(record.hold.take(stream_events.StreamEvent(
            held, stream_events.SETUP, 'response.created', setup_slot=0)))
        record.flush(client)
        self.assertEqual(bytes(client.written), held)
        self.assertEqual(record.forwarded_bytes, len(held))
        record.flush(client)
        self.assertEqual(len(client.written), len(held))

    def test_streamed_metrics_report_every_counter(self):
        record = stream_relay.StreamRecord()
        record.forwarded_bytes, record.content_delta_bytes = 11, 4
        record.reasoning_bytes = 6
        self.assertEqual(stream_relay.streamed_metrics(record),
                         {'forwarded_delta_bytes': 11, 'content_delta_bytes': 4,
                          'reasoning_delta_bytes': 6,
                          'unattributed_delta_bytes': 1})

    def test_clear_terminal_fields_drops_only_the_verdict(self):
        metrics = {'code': 'UPSTREAM_STREAM_FAILED', 'upstream_code': 'server_error',
                   'upstream_error_type': 'server_error',
                   'upstream_provider_code': 'p1', 'failure_class': 'transient',
                   'terminal_event': 'response.failed', 'upstream_reason': 'x',
                   'model': 'z-ai/glm-5.3-flash'}
        stream_relay.clear_terminal_fields(metrics)
        self.assertEqual(metrics, {'model': 'z-ai/glm-5.3-flash'})


class RawStreamOutcomeTests(unittest.TestCase):
    def _raw(self, frame, encoding='identity'):
        client = SimpleNamespace(wfile=io.BytesIO())
        provider = SimpleNamespace(
            defn=SimpleNamespace(id='openai', dialect=provider_defs.DIALECT_OPENAI),
            adapt=lambda *args: iter((frame,)))
        metrics = {'protocol': provider_defs.RESPONSES, 'response_kind': 'sse',
                   'response_encoding': encoding, 'model': 'm'}
        record = stream_relay.StreamRecord()
        stream_relay.relay_stream(
            client, provider, io.BytesIO(frame), SimpleNamespace(tool_names=set()), metrics,
            0.0, 0.0, record)
        record.flush(client)
        return client.wfile.getvalue(), metrics, record

    def test_raw_completion_is_success_and_raw_failure_uses_shared_outcome(self):
        _, metrics, record = self._raw(
            b'data: {"type":"response.completed","response":{"output":[]}}\n\n')
        self.assertEqual(record.outcome.category, outcome.SUCCESS)
        self.assertIsNone(record.client_terminal)
        self.assertNotIn('terminal_source', metrics)

        _, metrics, record = self._raw(
            b'data: {"type":"response.failed","response":{"error":{"code":"overloaded"}}}\n\n')
        self.assertEqual(record.outcome.category, outcome.TRANSIENT)
        self.assertEqual(record.client_terminal, stream_errors.TERMINAL_FROM_UPSTREAM)
        self.assertEqual(metrics['failure_class'], 'transient')
        self.assertEqual(metrics['code'], 'UPSTREAM_STREAM_FAILED')

        _, metrics, record = self._raw(
            b'data: {"type":"response.failed","response":{"error":{"code":"bad"}}}\n\n')
        self.assertEqual(record.outcome.category, outcome.UNKNOWN)
        self.assertEqual(record.client_terminal, stream_errors.TERMINAL_FROM_UPSTREAM)
        self.assertEqual(metrics['failure_class'], 'unknown')
        self.assertEqual(metrics['code'], 'UPSTREAM_STREAM_FAILED')

    def test_raw_terminal_is_lossless_and_never_replayed(self):
        frame = b'data: {"type":"response.failed","response":{"error":{"code":"bad"}}}\n\n'
        written, _, record = self._raw(frame)
        ledger = attempt_policy.Ledger(EXTERNAL, {'protocol': provider_defs.RESPONSES})
        self.assertFalse(ledger.replay(record, SAFE))
        self.assertEqual(written, frame)
        self.assertEqual(ledger.decisions, ['stream_replay:committed'])

    def test_raw_malformed_completion_matches_normalized_unknown(self):
        event = {'type': 'response.completed', 'response': {
            'error': {'code': 'server_error'}}}
        frame = sse.frame(json.dumps(event).encode())
        self.assertEqual(settled(event).category, outcome.UNKNOWN)
        _, _, record = self._raw(frame)
        self.assertEqual(record.outcome.category, outcome.UNKNOWN)

    def test_raw_first_terminal_latches_outcome(self):
        failed = b'data: {"type":"response.failed","response":{"error":{"code":"bad"}}}\n\n'
        completed = b'data: {"type":"response.completed","response":{"output":[]}}\n\n'
        _, _, record = self._raw(failed + completed)
        self.assertEqual(record.outcome.category, outcome.UNKNOWN)

    def test_overcap_raw_completion_keeps_one_success_terminal(self):
        raw = (b'data: {"type":"response.completed","response":{"output":[]}}'
               + b'x' * sse.MAX_FRAME_BYTES + b'\n\n')
        written, metrics, record = self._raw(raw)
        self.assertEqual(written, raw)
        self.assertEqual(record.outcome.category, outcome.SUCCESS)
        self.assertNotIn(b'response.failed', written)
        self.assertNotIn('terminal_source', metrics)

    def test_raw_frames_are_emitted_once_per_frame(self):
        first = b'data: {"type":"response.created","response":{"id":"r"}}\n\n'
        second = b'data: {"type":"response.completed","response":{"output":[]}}\n\n'
        for chunks in ((first + second,), (first, second)):
            with self.subTest(chunks=len(chunks)):
                client = SimpleNamespace(wfile=io.BytesIO())
                provider = SimpleNamespace(
                    defn=SimpleNamespace(id='openai',
                                         dialect=provider_defs.DIALECT_OPENAI),
                    adapt=lambda *args: iter(chunks))
                metrics = {'protocol': provider_defs.RESPONSES,
                           'response_kind': 'sse',
                           'response_encoding': 'identity', 'model': 'm'}
                events = list(stream_relay._raw_events(
                    provider.adapt(None, None, None), metrics))
                self.assertEqual([bytes(event.frame) for event in events], [first, second])

    def test_partial_raw_bytes_are_forwarded_before_the_frame_completes(self):
        partial = b'data: {"type":"response.failed","response":{"error":{"code":"overloaded"}}}\n'
        completion = b'\n'
        metrics = {'protocol': provider_defs.RESPONSES, 'response_kind': 'sse',
                   'response_encoding': 'identity', 'model': 'm'}
        events = stream_relay._raw_events(iter((partial, completion)), metrics)
        first = next(events)
        self.assertEqual(first.frame, partial)
        remainder = list(events)
        self.assertEqual(first.frame + b''.join(event.frame for event in remainder), partial + completion)
        self.assertEqual(remainder[-1].outcome.category, outcome.TRANSIENT)
        self.assertEqual(remainder[-1].source, stream_errors.TERMINAL_FROM_UPSTREAM)

    def test_raw_encoded_sse_forwards_exact_bytes_without_parsing(self):
        raw = b'data: {"type":"response.completed","response":{"output":[]}}\n\n'
        for encode in (gzip.compress, zstd.compress):
            with self.subTest(encoding=encode.__module__):
                body = encode(raw)
                written, _, _ = self._raw(body, 'gzip' if encode is gzip.compress else 'zstd')
                self.assertEqual(written, body)

    def test_deeply_nested_raw_json_is_forwarded_unchanged(self):
        frame = b'data: ' + b'[' * 2000 + b'1' + b']' * 2000 + b'\n\n'
        metrics = {'protocol': provider_defs.RESPONSES, 'response_kind': 'sse', 'response_encoding': 'identity'}
        events = list(stream_relay._raw_events([frame], metrics))
        self.assertEqual(b''.join(event.frame for event in events), frame)
        self.assertTrue(all(event.outcome is None for event in events))

    def test_raw_truncated_sse_forwards_the_incomplete_tail(self):
        body = b'data: {"type":"response.completed","response":{"output":[]}}\n'
        written, _, _ = self._raw(body)
        self.assertEqual(written, body)

    def test_full_relay_keeps_incomplete_raw_tail_without_synthetic_terminal(self):
        raw = b'data: {"type":"response.completed","response":{"output":[]}}\n'

        class Response:
            status = 200
            def __init__(self):
                self.raw = raw
            def getheaders(self):
                return [('Content-Type', 'text/event-stream')]
            def getheader(self, name, default=None):
                return 'text/event-stream' if name.lower() == 'content-type' else default
            def read1(self, count):
                data, self.raw = self.raw[:count], self.raw[count:]
                return data

        class Connection:
            def connect(self): pass
            def request(self, *args, **kwargs): pass
            def getresponse(self): return Response()
            def close(self): pass

        defn = SimpleNamespace(
            id='openai', kind=provider_defs.SUBSCRIPTION,
            dialect=provider_defs.DIALECT_OPENAI,
            caches_deterministic_refusals=lambda: False,
            opens_key_window_on_auth_failure=lambda: False,
            sends_context_error_frame=lambda: False)
        provider = SimpleNamespace(
            defn=defn, adapt=lambda *args: iter((raw,)))
        writer = io.BytesIO()
        handler = SimpleNamespace(
            server=SimpleNamespace(credentials=SimpleNamespace(
                key_rejected=lambda provider: False), lock=None, served_models={}),
            wfile=writer, send_response=lambda *args: None,
            send_header=lambda *args: None, end_headers=lambda: None,
            close_connection=False, error=lambda *args, **kwargs: None)
        prepared = transport.Prepared(
            'api.openai.com', '/responses', {}, b'{"input":[]}', set(), 'openai')
        metrics = {'provider': 'openai', 'protocol': provider_defs.RESPONSES,
                   'model': 'm', 'path': '/responses', 'stream': True}
        events = []
        with mock.patch.object(relay.http.client, 'HTTPSConnection',
                               lambda *args, **kwargs: Connection()):
            relay.relay(handler, provider, prepared, metrics, 0.0,
                        log_event=lambda event, **fields: events.append((event, fields)))
        self.assertEqual(writer.getvalue(), raw)
        self.assertNotIn(b'response.failed', writer.getvalue())

if __name__ == '__main__':
    unittest.main()
