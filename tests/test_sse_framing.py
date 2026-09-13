"""Router-level SSE framing (Plan 156 item 6): split frames, CRLF, comments,
missing data and end-of-stream framing through the live server.

Parser-level cases live in tests/test_stream_context_errors.py; these drive
the same shapes through start_server + post so the relay path itself is
pinned. Fake upstream only; never opens a real network connection.
"""
import json
import unittest
from unittest import mock

from ai_router import router, sse
from tests.fakes import FakeUpstream, install_fake
from tests.harness import post, start_server, test_state

MODEL = 'deepseek/deepseek-v4.1-flash'
SUCCESS = {'type': 'response.completed', 'response': {
    'id': 'resp_1', 'model': MODEL, 'output': [],
    'usage': {'input_tokens': 1, 'output_tokens': 1}}}


class TrickleUpstream(FakeUpstream):
    """Delivers the wire one byte per read, like a slow upstream link."""

    def read1(self, count):
        return super().read(1)


class SseFramingThroughRouterTests(unittest.TestCase):
    def setUp(self):
        self.server = start_server(test_state('unused'))
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, wire, trickle=False):
        fake = TrickleUpstream if trickle else FakeUpstream
        install_fake(self, lambda: fake(
            200, wire, [('Content-Type', 'text/event-stream')]))
        with mock.patch.object(router, 'log_event'):
            response = post(self.server.server_port, '/test-token/responses',
                            {'model': MODEL, 'input': [], 'stream': True})
            return response.status, response.read()

    def test_a_trickled_stream_is_forwarded_byte_for_byte(self):
        wire = (sse.frame(json.dumps(SUCCESS).encode())
                + sse.frame(b'{"type":"response.completed","response":{"id":"resp_2"}}'))
        status, body = self.request(wire, trickle=True)
        self.assertEqual(status, 200)
        self.assertEqual(body, wire)

    def test_crlf_frames_and_comments_are_preserved(self):
        wire = (b': keepalive\r\n\r\n'
                b'id: 7\r\nevent: response.completed\r\n'
                b'data: {"type":"response.completed",\r\n'
                b'data: "response":{"id":"resp_1"}}\r\n\r\n'
                b'data: [DONE]\n\n')
        status, body = self.request(wire, trickle=True)
        self.assertEqual(status, 200)
        self.assertEqual(body, wire)

    def test_a_frame_without_data_is_forwarded_unchanged(self):
        heartbeat = b'event: ping\r\n\r\n'
        wire = heartbeat + sse.frame(json.dumps(SUCCESS).encode())
        status, body = self.request(wire)
        self.assertEqual(status, 200)
        self.assertEqual(body, wire)

    def test_an_incomplete_trailing_frame_becomes_a_terminal_failure(self):
        partial = b'data: {"type":"response.completed"'
        status, body = self.request(partial)
        self.assertEqual(status, 200)
        head, _, data = body.partition(b'\ndata: ')
        self.assertEqual(head, b'event: response.failed')
        event = json.loads(data.strip())
        self.assertEqual(event['type'], 'response.failed')
        self.assertEqual(event['response']['error']['code'], 'UPSTREAM_FAILED')


if __name__ == '__main__':
    unittest.main()
