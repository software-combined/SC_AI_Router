"""One response boundary and metadata-only raw terminal observations."""
import io
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from ai_router import (outcome, provider_defs, relay, sse, stream_errors,
                       stream_relay, transport)
from tests.fakes import FakeUpstream
from tests.test_stream_outcome_recovery import (
    _defn, _metrics, _prepared, _provider)


class ManualResponseCommitmentTests(unittest.TestCase):
    def test_header_failure_cannot_start_a_second_response(self):
        raw = b'upstream sent an unrecognised error body'
        for status in (418, 200):
            with self.subTest(status=status):
                response_starts = []
                error_calls = []
                handler = SimpleNamespace(
                    server=SimpleNamespace(credentials=SimpleNamespace(
                        key_rejected=lambda provider: False), lock=None,
                        served_models={}),
                    wfile=io.BytesIO(), close_connection=False,
                    response_committed=False,
                    send_response=lambda code: response_starts.append(code),
                    send_header=lambda *args: (_ for _ in ()).throw(
                        BrokenPipeError('client gone')),
                    end_headers=lambda: None,
                    error=lambda err, **kwargs: error_calls.append(err))
                prepared = _prepared('openrouter.ai', 'openrouter')
                response = FakeUpstream(status, raw, [])
                provider = _provider(
                    _defn('openrouter', provider_defs.EXTERNAL,
                          provider_defs.DIALECT_OPENROUTER), ())
                with mock.patch.object(
                        relay.strip_retry, 'post_with_retry',
                        return_value=(response, 0.0, prepared, raw)):
                    relay.relay(
                        handler, provider, prepared, _metrics('openrouter'), 0.0,
                        log_event=lambda *args, **kwargs: None)
                self.assertEqual(response_starts, [status])
                self.assertEqual(error_calls, [])
                self.assertTrue(handler.response_committed)


class ZeroByteObservationTests(unittest.TestCase):
    def test_split_raw_terminal_observation_does_not_flush(self):
        frame = sse.frame(json.dumps({
            'type': 'response.failed',
            'response': {'error': {'code': 'overloaded'}}}).encode())
        chunks = (frame[:-1], frame[-1:])

        class Writer:
            def __init__(self):
                self.writes = []
            def write(self, data):
                self.writes.append(data)
                return len(data)
            def flush(self):
                if self.writes and self.writes[-1] == b'':
                    raise ValueError('I/O operation on closed file')

        writer = Writer()
        client = SimpleNamespace(wfile=writer)
        provider = SimpleNamespace(
            defn=SimpleNamespace(id='openai', dialect=provider_defs.DIALECT_OPENAI),
            adapt=lambda *args: iter(chunks))
        metrics = {'protocol': provider_defs.RESPONSES,
                   'response_kind': 'sse', 'response_encoding': 'identity',
                   'model': 'm'}
        record = stream_relay.StreamRecord()
        stream_relay.relay_stream(
            client, provider, object(), SimpleNamespace(tool_names=set()),
            metrics, 0.0, 0.0, record)

        self.assertEqual(b''.join(writer.writes), frame)
        self.assertNotIn(b'', writer.writes)
        self.assertEqual(record.forwarded_bytes, len(frame))
        self.assertEqual(record.outcome.category, outcome.TRANSIENT)
        self.assertEqual(record.client_terminal,
                         stream_errors.TERMINAL_FROM_UPSTREAM)


class RawTerminalParityTests(unittest.TestCase):
    CASES = (
        ('response.failed+overloaded',
         {'type': 'response.failed', 'response': {'error': {'code': 'overloaded'}}},
         {'category': outcome.TRANSIENT, 'code': 'overloaded',
          'failure_class': 'transient', 'terminal_code': 'UPSTREAM_STREAM_FAILED',
          'source': stream_errors.TERMINAL_FROM_UPSTREAM}),
        ('bare-error+invalid_prompt',
         {'type': 'error', 'code': 'invalid_prompt'},
         {'category': outcome.REFUSED, 'code': 'invalid_prompt',
          'failure_class': 'final', 'terminal_code': 'UPSTREAM_INVALID_PROMPT',
          'source': stream_errors.TERMINAL_FROM_ROUTER}),
        ('response.completed+failed-status',
         {'type': 'response.completed', 'response': {
             'status': 'failed', 'error': {'code': 'server_error'}}},
         {'category': outcome.UNKNOWN, 'code': 'server_error',
          'failure_class': 'transient', 'terminal_code': 'UPSTREAM_STREAM_FAILED',
          'source': stream_errors.TERMINAL_FROM_ROUTER}),
    )

    @staticmethod
    def _event(case, over_cap):
        event = json.loads(json.dumps(case))
        if over_cap:
            padding = 'x' * (sse.MAX_FRAME_BYTES + 1)
            if isinstance(event.get('response'), dict):
                event['response']['padding'] = padding
            else:
                event['padding'] = padding
        return event

    @staticmethod
    def _facts(event, metrics):
        return {
            'category': event.outcome.category,
            'code': event.outcome.code,
            'failure_class': metrics.get('failure_class'),
            'terminal_code': metrics.get('code'),
            'source': event.source,
        }

    def test_bounded_and_overcap_raw_match_normalized_terminal_policy(self):
        for name, case, expected in self.CASES:
            with self.subTest(name=name):
                bounded = sse.frame(json.dumps(self._event(case, False)).encode())
                normalized_metrics = {}
                normalized = list(stream_errors.events([bounded], normalized_metrics))[-1]
                self.assertEqual(self._facts(normalized, normalized_metrics), expected)
                for over_cap in (False, True):
                    with self.subTest(over_cap=over_cap):
                        frame = sse.frame(json.dumps(
                            self._event(case, over_cap)).encode())
                        metrics = {'protocol': provider_defs.RESPONSES,
                                   'response_kind': 'sse',
                                   'response_encoding': 'identity'}
                        with mock.patch.object(sse, 'MAX_FRAME_BYTES', 128):
                            raw = list(stream_relay._raw_events([frame], metrics))
                        self.assertEqual(b''.join(event.frame for event in raw), frame)
                        terminal = [event for event in raw if event.outcome is not None][-1]
                        self.assertEqual(
                            self._facts(terminal, metrics),
                            dict(expected, source=stream_errors.TERMINAL_FROM_UPSTREAM))

    def test_oversized_terminal_split_before_separator_is_lossless_and_delayed(self):
        with mock.patch.object(sse, 'MAX_FRAME_BYTES', 128):
            event = {'type': 'response.failed', 'response': {
                'error': {'code': 'overloaded'}, 'padding': ''}}
            padding = sse.MAX_FRAME_BYTES + 1 - len(sse.frame(
                json.dumps(event).encode()))
            event['response']['padding'] = 'x' * padding
            frame = sse.frame(json.dumps(event).encode())
            self.assertEqual(len(frame), sse.MAX_FRAME_BYTES + 1)
            prefix, completion = frame[:-2], frame[-2:]
            self.assertLessEqual(len(prefix), sse.MAX_FRAME_BYTES)
            metrics = {'protocol': provider_defs.RESPONSES,
                       'response_kind': 'sse', 'response_encoding': 'identity'}
            with mock.patch.object(stream_relay, '_raw_hint',
                                   wraps=stream_relay._raw_hint) as hint:
                events = list(stream_relay._raw_events(
                    (prefix, completion), metrics))
        self.assertEqual(b''.join(event.frame for event in events), frame)
        self.assertTrue(all(event.outcome is None for event in events[:-1]))
        self.assertEqual(events[-1].outcome.category, outcome.TRANSIENT)
        self.assertEqual(hint.call_count, 1)
        self.assertEqual(hint.call_args.args[0], frame)

    def test_overflow_forwards_bytes_but_never_observes_later_terminals(self):
        first = b'data: {"type":"response.failed","response":{"error":{"code":"overloaded"}}}\n'
        completion = b'\n'
        with mock.patch.object(sse, 'MAX_FRAME_BYTES', 16):
            metrics = {'protocol': provider_defs.RESPONSES,
                       'response_kind': 'sse', 'response_encoding': 'identity'}
            with mock.patch.object(stream_relay, '_raw_hint',
                                   wraps=stream_relay._raw_hint) as hint:
                events = list(stream_relay._raw_events(
                    (first, completion), metrics))
        self.assertEqual(b''.join(event.frame for event in events),
                         first + completion)
        self.assertTrue(all(event.outcome is None for event in events))
        hint.assert_not_called()


if __name__ == '__main__':
    unittest.main()
