"""Upstream read bounds (Plan 162): capped bodies and bounded SSE lines.

Fake upstream only; never opens a network connection. Reuses tests/fakes.py
and tests/harness.py like tests/test_stream_containment.py does.
"""
import io
import json
import unittest
from unittest import mock

from ai_router import router as router_mod
from ai_router import sse, transport
from ai_router.tool_adapter import stream_events
from tests.fakes import FakeUpstream, install_fake
from tests.harness import (
    auth_file as _auth_file,
    post as _post,
    start_server as _start_server,
    test_state as _test_state,
)


class ReadCappedTests(unittest.TestCase):
    def test_read_capped_returns_the_body_under_the_limit(self):
        body = b'{"ok": true}'
        self.assertEqual(transport.read_capped(io.BytesIO(body), 1024), body)

    def test_read_capped_raises_past_the_limit(self):
        body = b'x' * 129
        with self.assertRaisesRegex(ValueError, 'exceeds 128 bytes'):
            transport.read_capped(io.BytesIO(body), 128)

    def test_caps_match_the_request_ceiling(self):
        self.assertEqual(transport.MAX_UPSTREAM_BODY, router_mod.MAX_BODY)
        self.assertLess(transport.ERROR_BODY_LIMIT, transport.MAX_UPSTREAM_BODY)


class StreamBoundTests(unittest.TestCase):
    def test_newline_free_stream_raises_before_buffering_whole(self):
        big = b'data: ' + b'x' * (sse.MAX_FRAME_BYTES + 1)

        class _NoNewline(io.BytesIO):
            def __init__(self, buf):
                super().__init__(buf)
                self.calls = 0

            def read1(self, n):
                self.calls += 1
                return super().read1(n)

        fake = _NoNewline(big)
        with self.assertRaisesRegex(ValueError, 'exceeds %d' % sse.MAX_FRAME_BYTES):
            list(stream_events(fake, {(None, 'exec'): 'custom'}))
        # Piecewise reads: the bound is checked per 64 KiB piece, so one call
        # can never allocate the whole body before the check runs. (With no
        # newline the tail check fires at the cap; pending never exceeds it
        # by more than one piece.)
        self.assertGreater(fake.calls, 1)


class BoundedUpstreamTests(unittest.TestCase):
    def _server(self):
        state = _test_state(_auth_file(self))
        server = _start_server(state)
        self.addCleanup(server.shutdown)
        return server

    def test_oversized_error_body_is_a_502_not_a_relay(self):
        install_fake(self, lambda: FakeUpstream(
            400, b'{"error": "' + b'x' * (2 * 1024 * 1024) + b'"}'))
        server = self._server()
        with mock.patch.object(router_mod, 'log_event') as logged:
            response = _post(server.server_port, '/test-token/responses',
                             {'model': 'z-ai/glm-5.3', 'input': []})
            self.assertEqual(response.status, 502)
            payload = json.loads(response.read())
        self.assertEqual(payload['error']['code'], 'UPSTREAM_FAILED')
        kinds = [call.args[0] for call in logged.call_args_list]
        self.assertIn('transport_error', kinds)


if __name__ == '__main__':
    unittest.main()
