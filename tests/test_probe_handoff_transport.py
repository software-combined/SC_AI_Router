"""The handoff sink uses production's immediate WebSocket-to-HTTP fallback."""
import http.client
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import probe_agent_handoffs as handoffs


class HandoffTransportTests(unittest.TestCase):
    def test_real_sink_rejects_upgrade_once_without_dispatching_inference(self):
        servers = []
        server_type = handoffs.ThreadingHTTPServer

        def server_for(*args):
            server = server_type(*args)
            servers.append(server)
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            return server

        def before_client(*args, **kwargs):
            for path, headers, status in (
                    ('/v1/responses?synthetic=1', {'Upgrade': 'WebSocket'}, 426),
                    ('/v1/responses', {}, 404),
                    ('/unrelated', {'Upgrade': 'websocket'}, 404)):
                with self.subTest(path=path, headers=headers):
                    conn = http.client.HTTPConnection('127.0.0.1', servers[0].server_port, timeout=3)
                    try:
                        conn.request('GET', path, headers=headers)
                        response = conn.getresponse()
                        self.assertEqual(response.status, status)
                        response.read()
                    finally:
                        conn.close()
            raise InterruptedError('synthetic client interception')

        args = SimpleNamespace(live=False, max_live_calls=0, live_children=False,
            lifecycle=False, installed=False, native_only=False, codex='synthetic', wire_mode='lite')
        with patch.object(handoffs, 'ThreadingHTTPServer', server_for), \
                patch.object(handoffs, 'AppServer', before_client), \
                patch.object(handoffs.subprocess, 'run', return_value=SimpleNamespace(stdout='synthetic')), \
                patch.object(handoffs.Probe, 'respond') as dispatch:
            with self.assertRaises(InterruptedError):
                handoffs.run(args)
            dispatch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
