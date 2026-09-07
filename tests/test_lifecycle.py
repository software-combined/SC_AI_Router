"""Drain, socket activation, and graceful-restart behavior (Plan 045)."""
import http.client
import json
import socket
import threading
import time
import unittest
from unittest import mock

from codex_router import activation
import codex_router.__main__ as router_main
from codex_router.router import Router


def _server(test, **overrides):
    state = {'port': 0, 'token': 'test-token', 'openai_models': []}
    state.update(overrides)
    server = Router(state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    test.addCleanup(server.shutdown)
    test.addCleanup(server.server_close)
    return server


def _get(port, path):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    conn.request('GET', path)
    return conn.getresponse()


def _post(port, path, payload):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    conn.request('POST', path, body=json.dumps(payload),
                 headers={'Content-Type': 'application/json'})
    return conn.getresponse()


class DrainTests(unittest.TestCase):
    def test_sigterm_waits_for_inflight_then_exits(self):
        server = Router({'port': 0, 'token': 't', 'openai_models': []})
        self.addCleanup(server.server_close)
        server.inflight = 1
        exits = []
        with mock.patch('codex_router.router.os._exit', side_effect=lambda c: exits.append(c)), \
                mock.patch.object(server, 'shutdown'):
            worker = threading.Thread(target=server.drain_and_exit, daemon=True)
            worker.start()
            time.sleep(0.3)
            self.assertEqual(exits, [])
            server.inflight = 0
            worker.join(timeout=10)
        self.assertEqual(exits, [0])
        self.assertTrue(server.draining)

    def test_drain_deadline_forces_exit(self):
        server = Router({'port': 0, 'token': 't', 'openai_models': []})
        self.addCleanup(server.server_close)
        server.drain_deadline_s = 0.2
        server.inflight = 1
        events = []
        with mock.patch('codex_router.router.os._exit'), \
                mock.patch.object(server, 'shutdown'), \
                mock.patch('codex_router.router.log_event',
                           side_effect=lambda e, **kw: events.append((e, kw))):
            server.drain_and_exit()
        forced = [kw for e, kw in events if e == 'exit']
        self.assertTrue(forced and forced[0]['forced'] is True)

    def test_requests_during_drain_get_503_with_retry_after(self):
        server = _server(self)
        server.draining = True
        response = _post(server.server_port, '/test-token/responses', {'model': 'x'})
        self.assertEqual(response.status, 503)
        self.assertEqual(response.getheader('Retry-After'), '2')
        response = _post(server.server_port, '/nope/responses', {'model': 'x'})
        self.assertEqual(response.status, 403)

    def test_health_reports_draining(self):
        server = _server(self)
        body = json.loads(_get(server.server_port, '/test-token/health').read())
        self.assertFalse(body['draining'])
        server.draining = True
        response = _get(server.server_port, '/test-token/health')
        self.assertEqual(response.status, 200)
        self.assertTrue(json.loads(response.read())['draining'])


    def test_drain_thread_survives_serve_forever_return(self):
        # The missed race: shutdown() unblocks serve_forever, main returns,
        # and only a non-daemon drain thread lives to honor the deadline.
        server = Router({'port': 0, 'token': 't', 'openai_models': []})
        self.addCleanup(server.server_close)
        server.drain_deadline_s = 30
        served = threading.Thread(target=server.serve_forever, daemon=True)
        served.start()
        server.inflight = 1
        exits = []
        worker = None
        try:
            with mock.patch('codex_router.router.os._exit',
                            side_effect=lambda c: exits.append(c)):
                worker = router_main._start_drain_thread(server)
                self.assertFalse(worker.daemon)
                served.join(timeout=10)
                time.sleep(0.3)
                self.assertTrue(worker.is_alive(), 'drain must outlive serve_forever')
                self.assertEqual(exits, [])
                server.inflight = 0
                worker.join(timeout=10)
        finally:
            server.inflight = 0
        self.assertEqual(exits, [0])


class SocketActivationTests(unittest.TestCase):
    def test_fileno_listener_serves_without_binding(self):
        # A connected socketpair cannot listen, so the test passes a real
        # listening socket: the proof is serving on the inherited address.
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(listener.close)
        listener.bind(('127.0.0.1', 0))
        listener.listen(5)
        server = Router({'port': 0, 'token': 'test-token', 'openai_models': []},
                        fileno=listener.fileno())
        self.addCleanup(server.server_close)
        self.assertEqual(server.socket.getsockname(), listener.getsockname())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        conn = http.client.HTTPConnection(
            '127.0.0.1', listener.getsockname()[1], timeout=10)
        conn.request('GET', '/test-token/health')
        self.assertEqual(conn.getresponse().status, 200)

    def test_inherited_listener_returns_none_without_launchd(self):
        with mock.patch('ctypes.CDLL', side_effect=AttributeError('no symbol')):
            self.assertIsNone(activation.inherited_listener())


if __name__ == '__main__':
    unittest.main()
