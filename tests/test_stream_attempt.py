"""The uncommitted attempt's hold: bounded, ordered, lossless (Plan 187).

Unit level for `stream_attempt.AttemptHold` and one relay-level cleanup
case; tests/test_stream_setup_echo.py drives the same rules end to end.
"""
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from ai_router import (provider_defs, providers, relay, sse, stream_attempt,
                       stream_errors, stream_events, stream_relay)
from ai_router.transport import Prepared

ECHO = 'e' * 70000


def _frame(event):
    return sse.frame(json.dumps(event).encode())


def _event(event):
    (only,) = stream_errors.events([_frame(event)], {})
    return only


def _created(native='response.created', **response):
    return _event({'type': native, 'response': {'id': 'r', 'instructions': ECHO,
                                                 **response}})


def _failed(**response):
    return _event({'type': 'response.failed', 'response': {
        'id': 'r', 'instructions': ECHO, 'error': {'code': 'server_error'}, **response}})


def _reasoning(size=10):
    return _event({'type': 'response.reasoning_text.delta', 'delta': 'r' * size})


class AttemptHoldTests(unittest.TestCase):
    def test_large_setup_and_terminal_each_take_one_slot_in_order(self):
        hold = stream_attempt.AttemptHold()
        frames = [_created(), _created('response.in_progress'), _reasoning(), _failed()]
        self.assertTrue(all(hold.take(event) for event in frames))
        self.assertGreater(hold.size(), 3 * stream_attempt.PENDING_LIMIT)
        self.assertEqual(hold.frames, [event.frame for event in frames])
        self.assertEqual((hold.shared, hold.terminal), (len(frames[2].frame), 'upstream'))

    def test_duplicate_or_out_of_order_setup_commits(self):
        cases = ((_created(), _created()),
                 (_created('response.in_progress'),),
                 (_created(), _created('response.in_progress'),
                  _created('response.in_progress')),
                 (_created(), _reasoning(), _created('response.in_progress')))
        for events in cases:
            with self.subTest(kinds=[event.native for event in events]):
                hold = stream_attempt.AttemptHold()
                taken = [hold.take(event) for event in events]
                self.assertEqual(taken, [True] * (len(events) - 1) + [False])
                self.assertLessEqual(len(hold.setup), 2)

    def test_setup_shapes_outside_the_rule_are_opaque(self):
        for response in ({'output': [{'type': 'message'}]}, {'status': 'completed'},
                         {'output': None}, {'status': {}}, {'status': []}):
            with self.subTest(response=response):
                event = _created(**response)
                self.assertEqual(event.kind, stream_events.OPAQUE)
                self.assertFalse(stream_attempt.AttemptHold().take(event))
        missing = _event({'type': 'response.created'})
        self.assertEqual(missing.kind, stream_events.OPAQUE)

    def test_unhashable_type_is_opaque_with_its_bytes(self):
        for kind in ([], {}):
            with self.subTest(kind=kind):
                frame = _frame({'type': kind})
                (event,) = stream_errors.events([frame], {})
                self.assertEqual((event.kind, event.frame), (stream_events.OPAQUE, frame))
                self.assertFalse(stream_attempt.AttemptHold().take(event))

    def test_reasoning_shares_the_small_budget(self):
        hold = stream_attempt.AttemptHold()
        self.assertTrue(hold.take(_reasoning(stream_attempt.PENDING_LIMIT // 2)))
        self.assertFalse(hold.take(_reasoning(stream_attempt.PENDING_LIMIT // 2)))
        self.assertLessEqual(hold.shared, stream_attempt.PENDING_LIMIT)

    def test_comment_frames_wait_without_blocking_setup(self):
        comment = next(stream_errors.events([b': keep-alive\n\n'], {}))
        self.assertEqual(comment.kind, stream_events.PLUMBING)
        hold = stream_attempt.AttemptHold()
        self.assertTrue(hold.take(comment) and hold.take(_created()))

    def test_one_terminal_slot_and_nothing_after_it(self):
        hold = stream_attempt.AttemptHold()
        self.assertTrue(hold.take(_failed()))
        self.assertFalse(hold.take(_reasoning()))
        self.assertFalse(hold.take(_created()))
        self.assertEqual(len(hold.frames), 1)

    def test_terminal_with_output_commits(self):
        event = _failed(output=[{'type': 'function_call', 'name': 'x'}])
        self.assertTrue(event.output)
        self.assertFalse(stream_attempt.AttemptHold().take(event))

    def test_answers_completion_and_opaque_frames_commit(self):
        for event in (_event({'type': 'response.output_text.delta', 'delta': 'x'}),
                      _event({'type': 'response.completed', 'response': {'output': []}}),
                      _event({'type': 'response.unclassified'}),
                      next(stream_errors.events([b'data: [DONE]\n\n'], {}))):
            with self.subTest(kind=event.kind):
                self.assertFalse(stream_attempt.AttemptHold().take(event))

    def test_split_chunks_classify_identically(self):
        wire = b''.join(event.frame for event in (_created(), _reasoning(), _failed()))
        whole = [(e.frame, e.kind, e.source) for e in stream_errors.events([wire], {})]
        for step in (1, 13, 65536):
            with self.subTest(step=step):
                chunks = [wire[i:i + step] for i in range(0, len(wire), step)]
                self.assertEqual([(e.frame, e.kind, e.source)
                                  for e in stream_errors.events(chunks, {})], whole)


class ReplaySafetyTests(unittest.TestCase):
    def test_only_client_run_tool_types_are_safe_to_replay(self):
        cases = ((None, True), ([], True),
                 ([{'type': 'function'}, {'type': 'custom'}], True),
                 ([{'type': 'function'}, {'type': 'web_search'}], False),
                 ([{'type': 'image_generation'}], False),
                 ([{'name': 'untyped'}], False), (['function'], False),
                 ({'type': 'function'}, False))
        for tools, safe in cases:
            with self.subTest(tools=tools):
                body = json.dumps({'model': 'm', 'tools': tools}).encode()
                self.assertIs(stream_attempt.replay_safe(body), safe)
        for body in (b'not json', b'[]', b'\xff'):
            with self.subTest(body=body):
                self.assertFalse(stream_attempt.replay_safe(body))


class CancelledStreamTests(unittest.TestCase):
    def test_client_leaving_during_a_held_attempt_closes_and_releases(self):
        wire = (_created().frame + _created('response.in_progress').frame
                + _frame({'type': 'response.output_text.delta', 'delta': 'hi'}))
        closed, records = [], []

        class Upstream:
            status = 200

            def __init__(self):
                self._buf = wire

            def getheaders(self):
                return [('Content-Type', 'text/event-stream')]

            def getheader(self, name, default=None):
                return 'text/event-stream' if name.lower() == 'content-type' else default

            def read1(self, count):
                piece, self._buf = self._buf[:count], self._buf[count:]
                return piece

        class Conn:
            def __init__(self, *a, **k):
                pass

            def connect(self):
                pass

            def request(self, *a, **k):
                pass

            def getresponse(self):
                return Upstream()

            def close(self):
                closed.append(self)

        class GoneClient:
            def write(self, _):
                raise BrokenPipeError(32, 'Broken pipe')

            def flush(self):
                pass

        class Recorded(stream_relay.StreamRecord):
            __slots__ = ()

            def __init__(self):
                super().__init__()
                records.append(self)

        handler = SimpleNamespace(
            server=SimpleNamespace(lock=None, served_models={}), wfile=GoneClient(),
            send_response=lambda *a: None, send_header=lambda *a: None,
            end_headers=lambda: None, close_connection=False, error=lambda err: None)
        provider = providers.ExternalResponsesProvider(provider_defs.OPENROUTER)
        body = json.dumps({'model': 'm', 'input': [], 'tools': []}).encode()
        prepared = Prepared('openrouter.ai', '/responses', {}, body, set(), 'openrouter')
        metrics = {'provider': 'openrouter', 'protocol': 'responses',
                   'model': 'z-ai/glm-5.3', 'path': '/responses', 'stream': True}
        logged = []
        with mock.patch.object(relay.http.client, 'HTTPSConnection', Conn), \
                mock.patch.object(relay.stream_relay, 'StreamRecord', Recorded), \
                mock.patch.object(relay.transport, 'describe_location',
                                  return_value='socketserver.py:1:write'):
            relay.relay(handler, provider, prepared, metrics, 0.0,
                        log_event=lambda event, **f: logged.append((event, f)))
        self.assertIn('client_disconnected', [event for event, _ in logged])
        self.assertEqual(len(closed), 1)
        self.assertEqual((records[0].hold.frames, records[0].forwarded_bytes), ([], 0))
        self.assertTrue(handler.close_connection)


if __name__ == '__main__':
    unittest.main()
