"""Mid-stream failure containment and SSE frame bound (Plan 096).

Fake upstream only; never opens a real network connection. Reuses the
handler helpers like tests/test_ingress_guards.py does.
"""
import io
import json
import unittest
from unittest import mock

from ai_router import router as router_mod
from ai_router import sse, transport
from tests.fakes import FakeUpstream, install_fake
from tests.test_handler import _auth_file, _post
from tests.test_mixed_router import _start_server, _test_state


class SseFrameBoundTests(unittest.TestCase):
    def test_over_cap_frame_raises_bounded_error(self):
        big = b'data: ' + b'x' * (sse.MAX_FRAME_BYTES + 1) + b'\n\n'
        with self.assertRaisesRegex(ValueError, 'exceeds %d' % sse.MAX_FRAME_BYTES):
            list(sse.blocks(iter(big.splitlines(keepends=True))))

    def test_under_cap_large_frame_still_parses(self):
        payload = b'x' * (1024 * 1024)
        frame = b'data: ' + payload + b'\n\n'
        lines = frame.splitlines(keepends=True)
        self.assertEqual(list(sse.blocks(iter(lines))), [(frame, payload)])

    def test_cap_matches_request_body_ceiling(self):
        self.assertEqual(sse.MAX_FRAME_BYTES, router_mod.MAX_BODY)


class RelayContainmentTests(unittest.TestCase):
    def _server(self, **state_overrides):
        state = _test_state(_auth_file(self))
        state.update(state_overrides)
        server = _start_server(state)
        self.addCleanup(server.shutdown)
        return server

    def _events(self, body):
        events = []
        for block in body.split(b'\n\n'):
            for line in block.splitlines():
                if line.startswith(b'data:'):
                    events.append(json.loads(line[5:].strip()))
        return events

    def test_non_dict_sse_payload_ends_stream_with_response_failed(self):
        wire = b'data: [1,2,3]\n\n'
        install_fake(self, lambda: FakeUpstream(
            200, wire, [('Content-Type', 'text/event-stream')]))
        server = self._server()
        with mock.patch.object(router_mod, 'log_event') as logged:
            response = _post(server.server_port, '/test-token/responses',
                             {'model': 'z-ai/glm-5.3', 'input': [],
                              'stream': True,
                              'tools': [{'type': 'custom', 'name': 'exec'}]})
            self.assertEqual(response.status, 200)
            events = self._events(response.read())
        self.assertEqual(events[-1]['type'], 'response.failed')
        self.assertEqual(events[-1]['response']['error']['code'], 'UPSTREAM_FAILED')
        kinds = [call.args[0] for call in logged.call_args_list]
        self.assertIn('transport_error', kinds)
        entry = next(call for call in logged.call_args_list
                     if call.args[0] == 'transport_error')
        self.assertEqual(entry.kwargs['error_type'], 'AttributeError')
        self.assertIn('location', entry.kwargs)

    def test_pre_headers_failure_keeps_502_mapping(self):
        def stall():
            raise TimeoutError('timed out')
        install_fake(self, stall)
        server = self._server()
        response = _post(server.server_port, '/test-token/responses',
                         {'model': 'z-ai/glm-5.3', 'input': []})
        self.assertEqual(response.status, 502)
        self.assertEqual(json.loads(response.read())['error']['code'], 'UPSTREAM_FAILED')

    def test_non_sse_mid_stream_failure_closes_without_terminal_frame(self):
        class ChunkedUpstream(FakeUpstream):
            def __iter__(self):
                yield b'{"output":'
                raise AttributeError('boom')

        install_fake(self, lambda: ChunkedUpstream(
            200, b'{"output": []}', [('Content-Type', 'application/json')]))
        server = self._server()
        response = _post(server.server_port, '/test-token/responses',
                         {'model': 'z-ai/glm-5.3', 'input': []})
        self.assertEqual(response.status, 200)
        self.assertNotIn(b'response.failed', response.read())


class EmitTerminalFailureTests(unittest.TestCase):
    def _frame(self, **metrics):
        buf = io.BytesIO()
        transport.emit_terminal_failure(buf, dict(metrics, protocol='responses'))
        return buf.getvalue()

    def test_emits_generic_frame_on_responses_sse(self):
        out = self._frame(stream=True, response_kind='sse',
                          response_encoding='identity')
        self.assertTrue(out.startswith(b'event: response.failed\ndata: '))
        event = json.loads(out.split(b'data: ', 1)[1])
        self.assertEqual(event['type'], 'response.failed')
        self.assertEqual(event['response']['error']['code'], 'UPSTREAM_FAILED')

    def test_silent_for_claude_non_sse_and_unstreamed(self):
        buf = io.BytesIO()
        transport.emit_terminal_failure(
            buf, {'stream': True, 'response_kind': 'sse', 'protocol': 'messages'})
        self.assertEqual(buf.getvalue(), b'')
        for metrics in ({'stream': True, 'response_kind': 'json'},
                        {'stream': False, 'response_kind': 'sse'},
                        {'stream': True, 'response_kind': 'other'},
                        {'stream': True, 'response_kind': 'sse',
                         'response_encoding': 'gzip'}):
            with self.subTest(metrics=metrics):
                self.assertEqual(self._frame(**metrics), b'')

    def test_dead_socket_never_raises(self):
        for error in (OSError('gone'), ValueError('I/O operation on closed file')):
            with self.subTest(error=type(error).__name__):
                class Dead:
                    def write(self, _):
                        raise error

                    def flush(self):
                        raise error

                transport.emit_terminal_failure(
                    Dead(), {'stream': True, 'response_kind': 'sse',
                             'response_encoding': 'identity',
                             'protocol': 'responses'})


if __name__ == '__main__':
    unittest.main()
