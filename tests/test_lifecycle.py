"""Drain, socket activation, and graceful-restart behavior (Plan 109)."""
import http.client
import inspect
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

from ai_router import activation
import ai_router.__main__ as router_main
from ai_router.router import Handler, Router, _harden_listener
from tests.harness import get as _get, post as _post, start_auth_server as _start_auth_server


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
    @unittest.skipIf(sys.platform == 'darwin'
                     and os.environ.get('GITHUB_ACTIONS') == 'true',
                     'hosted macOS runners blackhole subprocess loopback '
                     '(URLError(TimeoutError) to a live bound child while '
                     'in-process loopback stays green); proven locally and '
                     'on ubuntu/windows CI')
    def test_installed_launcher_boots_keyless_and_serves(self):
        # Production boots `python <home>/router_launch.py` with no cwd help:
        # the pointer must resolve the release or nothing serves. Keyless boot
        # via a fresh setup nonce keeps this offline (no key, no billing).
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            release = home / 'releases' / '9.9.9'
            shutil.copytree(_ROOT / 'ai_router', release / 'ai_router',
                            ignore=shutil.ignore_patterns('__pycache__'))
            (home / 'current').write_text('9.9.9\n')
            shutil.copy(_ROOT / 'packaging' / 'router_launch.py',
                        home / 'router_launch.py')
            probe = socket.socket()
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
            probe.close()
            token = 'launch-proof-token'.ljust(32, 'x')
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
    def test_relay_runs_after_the_request_frame_returns(self):
        # Plan 164: the raw body and parsed payload are locals of
        # _owned_post; calling relay from do_POST lets them die before the
        # stream starts. Lives here, not in test_handler.py, which sits at
        # its 500-line hard cap.
        source = inspect.getsource(Handler._owned_post)
        self.assertNotIn('self.relay(', source)
        self.assertIn('self.relay(*ready)', inspect.getsource(Handler.do_POST))

    def test_sigterm_waits_for_inflight_then_exits(self):
        server = Router({'port': 0, 'token': 't', 'openai_models': []})
        self.addCleanup(server.server_close)
        server.inflight = 1
        exits = []
        with mock.patch('ai_router.router.os._exit', side_effect=lambda c: exits.append(c)), \
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
        with mock.patch('ai_router.router.os._exit'), \
                mock.patch.object(server, 'shutdown'), \
                mock.patch('ai_router.router.log_event',
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

    def test_a_drain_between_admission_and_slot_is_still_503(self):
        # The drain flag and the slot increment are one critical section:
        # hold the lock before sending, flip draining under that same lock,
        # release, and assert the request is refused with the slot unheld.
        server = _start_auth_server(self)
        payload = json.dumps({'model': 'z-ai/glm-5.3', 'input': []}).encode()
        # Hold the lock before the request is even sent, so the handler must
        # block at admission: it cannot slip through before the flip below.
        server.lock.acquire()
        try:
            sock = socket.create_connection(('127.0.0.1', server.server_port), timeout=10)
            self.addCleanup(sock.close)
            sock.sendall(b'\r\n'.join([
                b'POST /test-token/responses HTTP/1.1',
                b'Host: 127.0.0.1',
                b'Content-Type: application/json',
                b'Content-Length: ' + str(len(payload)).encode(),
                b'Connection: close', b'', b'']) + payload)
            # Settle until the handler thread exists and is waiting on the
            # lock; only then flip draining and release, so the handler
            # decides under the same critical section the flag was set in.
            deadline = time.monotonic() + 10
            while (len(threading.enumerate()) < 3
                   and time.monotonic() < deadline):
                time.sleep(0.01)
            time.sleep(0.3)
            server.draining = True
        finally:
            server.lock.release()
        data = b''
        while b'\r\n\r\n' not in data:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
        head = data.split(b'\r\n', 1)[0]
        self.assertIn(b'503', head)
        self.assertIn(b'Retry-After: 2', data)
        self.assertEqual(server.inflight, 0)

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
            with mock.patch('ai_router.router.os._exit',
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


class InFlightBodyDrainTests(unittest.TestCase):
    def test_drain_waits_for_request_still_reading_its_body(self):
        # Plan 090 Step 2: the slot is held from the owned-path check, so a
        # request mid-read_body keeps drain_and_exit from exiting early.
        server = _start_auth_server(self)
        payload = json.dumps({'model': 'z-ai/glm-5.3', 'input': []}).encode()
        sock = socket.create_connection(('127.0.0.1', server.server_port), timeout=10)
        self.addCleanup(sock.close)
        sock.sendall(b'\r\n'.join([
            b'POST /test-token/responses HTTP/1.1',
            b'Host: 127.0.0.1',
            b'Content-Type: application/json',
            b'Content-Length: ' + str(len(payload) + 500).encode(),
            b'Connection: close', b'', b'']) + payload[:len(payload) // 2])
        deadline = time.monotonic() + 10
        while server.inflight == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(server.inflight, 1)
        exits = []
        with mock.patch('ai_router.router.os._exit',
                        side_effect=lambda c: exits.append(c)):
            worker = threading.Thread(target=server.drain_and_exit, daemon=True)
            worker.start()
            time.sleep(0.5)
            self.assertEqual(exits, [], 'drain must wait for the unread body')
            sock.sendall(payload[len(payload) // 2:] + b'x' * 500)
            worker.join(timeout=20)
        self.assertEqual(exits, [0])

    def test_error_paths_release_the_slot_exactly_once(self):
        # Plan 090 Step 2 negative case: an owned request whose upstream
        # transport fails (mapped to 502) must not leak or double-release the
        # slot the wrapper took.
        from ai_router import providers
        server = _start_auth_server(self)

        class _FailConn:
            def __init__(self, *a, **k):
                pass

            def connect(self):
                pass

            def request(self, *a, **k):
                pass

            def getresponse(self):
                raise OSError('upstream unreachable')

            def close(self):
                pass

        patcher = mock.patch.object(http.client, 'HTTPSConnection', _FailConn)
        patcher.start()
        self.addCleanup(patcher.stop)
        response = _post(server.server_port, '/test-token/responses',
                         {'model': 'z-ai/glm-5.3', 'input': []})
        self.assertGreaterEqual(response.status, 400)
        response.read()
        deadline = time.monotonic() + 10
        while server.inflight != 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(server.inflight, 0)

    def test_rejects_outside_the_slot_do_not_hold_it(self):
        # Plan 090 Step 2: /shutdown starts the drain, so it must stay outside
        # the slot; otherwise the drain thread would wait on its own trigger.
        # Sampling inflight when drain is entered (not after the reply) is what
        # makes this fail if /shutdown ever moves inside the slot.
        server = _server(self)
        seen = []
        with mock.patch.object(Router, 'drain_and_exit',
                               side_effect=lambda: seen.append(server.inflight)):
            response = _post(server.server_port, '/test-token/shutdown', {})
            response.read()
        deadline = time.monotonic() + 5
        while not seen and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(seen, [0])


class SingleListenerTests(unittest.TestCase):
    def test_second_bind_to_same_port_raises(self):
        # Plan 090 Step 3: no SO_REUSEPORT, so a second router on the same
        # loopback port fails instead of silently sharing connections.
        # Windows gets the same guarantee from SO_EXCLUSIVEADDRUSE, set in
        # Router.server_bind (its default SO_REUSEADDR would allow sharing).
        server = _server(self)
        with self.assertRaises(OSError):
            Router({'port': server.server_port, 'token': 't', 'openai_models': []})

    def test_a_reuse_address_binder_cannot_take_the_port(self):
        # The hijack shape the Windows fix exists for: a second local
        # process sets SO_REUSEADDR and tries to co-bind. Without
        # SO_EXCLUSIVEADDRUSE it succeeds on Windows, so this fails there
        # unless the exclusive flag really reached the listening socket.
        server = _server(self)
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(probe.close)
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        with self.assertRaises(OSError):
            probe.bind(('127.0.0.1', server.server_port))

    def test_windows_listener_sets_exclusive_bind(self):
        # The Windows branch cannot run on this host; pin its shape: the
        # exclusive flag before bind, and SO_REUSEADDR off (both required).
        fake = mock.Mock()
        with mock.patch.object(socket, 'SO_EXCLUSIVEADDRUSE', 0x4, create=True):
            _harden_listener(fake, platform='nt')
        fake.setsockopt.assert_called_once_with(socket.SOL_SOCKET, 0x4, 1)
        self.assertEqual(Router.allow_reuse_address, os.name != 'nt')
        if os.name == 'nt':
            # The helper no-ops without the flag; Windows must expose it.
            self.assertIsNotNone(getattr(socket, 'SO_EXCLUSIVEADDRUSE', None))


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

    def test_stuck_activation_ipc_falls_back_within_bound(self):
        # A launch_activate_socket that never returns must not wedge boot:
        # the router binds its configured port instead of going deaf.
        with mock.patch('ctypes.CDLL',
                        side_effect=lambda name: time.sleep(60)), \
                mock.patch.object(activation, 'ACTIVATION_WAIT_S', 0.2):
            started = time.monotonic()
            self.assertIsNone(activation.inherited_listener())
            self.assertLess(time.monotonic() - started, 30)


if __name__ == '__main__':
    unittest.main()
