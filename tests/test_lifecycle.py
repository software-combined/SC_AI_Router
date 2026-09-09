"""Drain, socket activation, and graceful-restart behavior (Plan 045)."""
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from codex_router import activation
import codex_router.__main__ as router_main
from codex_router.router import Router


_ROOT = Path(__file__).resolve().parents[1]


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


class ShutdownEndpointTests(unittest.TestCase):
    def test_post_shutdown_drains_and_reports(self):
        server = _server(self)
        with mock.patch.object(Router, 'drain_and_exit') as drain:
            response = _post(server.server_port, '/test-token/shutdown', {})
            body = json.loads(response.read())
        self.assertEqual(response.status, 200)
        self.assertEqual(body, {'status': 'draining'})
        drain.assert_called_once_with()

    def test_get_shutdown_is_unsupported(self):
        server = _server(self)
        self.assertEqual(_get(server.server_port, '/test-token/shutdown').status, 404)

    def test_shutdown_needs_path_token(self):
        server = _server(self)
        with mock.patch.object(Router, 'drain_and_exit') as drain:
            response = _post(server.server_port, '/wrong-token/shutdown', {})
            response.read()
        self.assertEqual(response.status, 403)
        drain.assert_not_called()


class LauncherBootTests(unittest.TestCase):
    def test_installed_launcher_boots_keyless_and_serves(self):
        # Production boots `python <home>/router_launch.py` with no cwd help:
        # the pointer must resolve the release or nothing serves. Keyless boot
        # via a fresh setup nonce keeps this offline (no key, no billing).
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            release = home / 'releases' / '9.9.9'
            shutil.copytree(_ROOT / 'codex_router', release / 'codex_router',
                            ignore=shutil.ignore_patterns('__pycache__'))
            (home / 'current').write_text('9.9.9\n')
            shutil.copy(_ROOT / 'packaging' / 'router_launch.py',
                        home / 'router_launch.py')
            probe = socket.socket()
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
            probe.close()
            token = 'launch-proof-token'
            (home / 'mixed-router-state.json').write_text(json.dumps({
                'port': port, 'token': token, 'openai_models': [],
                'setup': {'nonce': 'n' * 16,
                          'expires': int(time.time()) + 900}}))
            proc = subprocess.Popen(
                [sys.executable, str(home / 'router_launch.py')],
                env={**os.environ, 'ROUTER_HOME': str(home)},
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            try:
                base = f'http://127.0.0.1:{port}/{token}'
                # Bypass ambient proxies: loopback must never leave the
                # machine, whatever the runner exports (urllib honors
                # http_proxy; http.client, used elsewhere, does not).
                direct = urllib.request.build_opener(
                    urllib.request.ProxyHandler({}))
                deadline = time.monotonic() + 30
                last_error = '<no attempts>'
                while time.monotonic() < deadline:
                    try:
                        with direct.open(base + '/health', timeout=2) as r:
                            if r.status == 200 and json.load(r).get('status') == 'ok':
                                break
                    except OSError as exc:
                        # ECONNREFUSED = nothing listening; ETIMEDOUT = SYN
                        # blackholed. Recorded for CI forensics, not asserted.
                        last_error = repr(exc)
                        time.sleep(0.2)
                else:
                    alive = proc.poll() is None
                    proc.terminate()
                    _, err = proc.communicate(timeout=20)
                    # The child logs router_started to logs/router.jsonl at
                    # boot: its presence means the child bound somewhere
                    # unexpected, its absence means it hung before serving.
                    log = home / 'logs' / 'router.jsonl'
                    started = log.read_text() if log.exists() else '<no log>'
                    self.fail('installed launcher never served /health '
                              f'(alive={alive}): '
                              + (err or '').strip()[-1000:]
                              + ' | log tail: ' + started.strip()[-1000:]
                              + ' | last poll error: ' + last_error[-300:])
                with direct.open(base + '/setup/' + 'n' * 16,
                                 timeout=5) as r:
                    self.assertEqual(r.status, 200)
            finally:
                proc.terminate()
                proc.wait(timeout=20)

    def test_launcher_refuses_garbage_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            (home / 'current').write_bytes(b'\x00\xff\xfe\x01')
            shutil.copy(_ROOT / 'packaging' / 'router_launch.py',
                        home / 'router_launch.py')
            proc = subprocess.run(
                [sys.executable, str(home / 'router_launch.py')],
                capture_output=True, text=True, timeout=30,
                env={**os.environ, 'ROUTER_HOME': str(home)})
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn('pointer', proc.stderr)

    def test_launcher_refuses_missing_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            shutil.copy(_ROOT / 'packaging' / 'router_launch.py',
                        home / 'router_launch.py')
            proc = subprocess.run(
                [sys.executable, str(home / 'router_launch.py')],
                capture_output=True, text=True, timeout=30,
                env={**os.environ, 'ROUTER_HOME': str(home)})
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn('pointer', proc.stderr)


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
        port = listener.getsockname()[1]
        server = Router({'port': port, 'token': 'test-token', 'openai_models': []},
                        fileno=listener.fileno())
        self.addCleanup(server.server_close)
        self.assertEqual(server.socket.getsockname(), listener.getsockname())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        conn = http.client.HTTPConnection(
            '127.0.0.1', port, timeout=10)
        conn.request('GET', '/test-token/health')
        self.assertEqual(conn.getresponse().status, 200)

    def test_foreign_listener_falls_back_to_configured_port(self):
        # A launchd socket for another port (e.g. the CI runner's own
        # Listeners entry) must not capture the router: it serves the
        # configured port instead of going deaf with no error.
        foreign = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(foreign.close)
        foreign.bind(('127.0.0.1', 0))
        foreign.listen(5)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        server = Router({'port': port, 'token': 'test-token', 'openai_models': []},
                        fileno=foreign.fileno())
        self.addCleanup(server.server_close)
        self.assertEqual(server.socket.getsockname(), ('127.0.0.1', port))

    def test_inherited_listener_returns_none_without_launchd(self):
        with mock.patch('ctypes.CDLL', side_effect=AttributeError('no symbol')):
            self.assertIsNone(activation.inherited_listener())


if __name__ == '__main__':
    unittest.main()
