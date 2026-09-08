"""First-run key window over loopback (Plan 047 G). No network: OpenRouter
key checks run through an injected urlopen fake."""
import http.client
import json
import os
import shutil
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock
from codex_router import setup
from codex_router.runtime import load_state
from tests.test_mixed_router import _start_server

NOW = 1_700_000_000


def _state(home, **over):
    state = {'port': 1, 'token': 'test-token', 'openai_models': [],
             'setup': {'nonce': 'n' * 16, 'expires': NOW + 900}}
    state.update(over)
    return state


def _key_ok(key='sk-test'):
    payload = json.dumps({'data': {'label': 'probe', 'limit': 10,
                                   'usage': 3}}).encode()
    assert key

    class Resp:
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False
        def read(self, *args):
            return payload

    def fake(req, timeout=None):
        assert req.get_header('Authorization', '').startswith('Bearer ')
        return Resp()
    return fake


def _key_rejected():
    def fake(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 401, 'Unauthorized', {}, None)
    return fake


class SetupUnitTests(unittest.TestCase):
    def test_nonce_validation(self):
        state = _state(None)
        self.assertTrue(setup.valid_nonce(state, 'n' * 16, NOW))
        self.assertFalse(setup.valid_nonce(state, 'n' * 16, NOW + 901))
        self.assertFalse(setup.valid_nonce(state, 'wrong', NOW))
        self.assertFalse(setup.valid_nonce(state, '', NOW))
        self.assertFalse(setup.valid_nonce({'setup': {'nonce': 'n' * 16}}, 'n' * 16, NOW))
        self.assertFalse(setup.valid_nonce({}, 'n' * 16, NOW))

    def test_get_renders_form(self):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        status, body = setup.handle_setup(_state(home), home, 'n' * 16, False, None,
                                          _urlopen=_key_ok(), _now=NOW)
        self.assertEqual(status, 200)
        self.assertIn(b'<form', body)
        self.assertIn(b'n' * 16, body)

    def test_unknown_link_is_404(self):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        status, _ = setup.handle_setup(_state(home), home, 'wrong', False, None,
                                       _urlopen=_key_ok(), _now=NOW)
        self.assertEqual(status, 404)

    def test_post_stores_key_and_closes_setup(self):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        state_path = home / 'mixed-router-state.json'
        state = _state(home)
        state_path.write_text(json.dumps(state))
        form = b'key=sk-test&mode=none'
        status, body = setup.handle_setup(state, home, 'n' * 16, True, form,
                                          _urlopen=_key_ok(), _now=NOW)
        self.assertEqual(status, 200)
        self.assertIn(b'Remaining credit', body)
        key_path = home / 'openrouter.key'
        self.assertEqual(key_path.read_text(), 'sk-test\n')
        self.assertEqual(oct(key_path.stat().st_mode & 0o777), '0o600')
        saved = json.loads(state_path.read_text())
        self.assertNotIn('setup', saved)
        self.assertEqual(saved['openai_mode'], 'none')
        self.assertEqual(saved['token'], 'test-token')
        self.assertNotIn('setup', state)

    def test_post_rejects_bad_key_modes_and_clashes(self):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        state = _state(home)
        status, _ = setup.handle_setup(state, home, 'n' * 16, True, b'key=&mode=none',
                                       _urlopen=_key_ok(), _now=NOW)
        self.assertEqual(status, 422)
        status, _ = setup.handle_setup(state, home, 'n' * 16, True,
                                       b'key=sk-test&mode=bogus',
                                       _urlopen=_key_ok(), _now=NOW)
        self.assertEqual(status, 422)
        status, _ = setup.handle_setup(state, home, 'n' * 16, True,
                                       b'key=sk-test&mode=subscription',
                                       _urlopen=_key_rejected(), _now=NOW)
        self.assertEqual(status, 422)
        self.assertFalse((home / 'openrouter.key').exists())

        def boom(req, timeout=None):
            raise OSError('down')
        status, _ = setup.handle_setup(state, home, 'n' * 16, True,
                                       b'key=sk-test&mode=subscription',
                                       _urlopen=boom, _now=NOW)
        self.assertEqual(status, 502)
        (home / 'openrouter.key').write_text('old\n')
        status, body = setup.handle_setup(state, home, 'n' * 16, True,
                                          b'key=sk-test&mode=subscription',
                                          _urlopen=_key_ok(), _now=NOW)
        self.assertEqual(status, 409)
        self.assertEqual((home / 'openrouter.key').read_text(), 'old\n')

    def test_load_state_boots_keyless_on_fresh_nonce(self):
        import time as _time
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        path = home / 'mixed-router-state.json'
        with mock.patch.dict(os.environ, {'OPENROUTER_API_KEY': ''}):
            with mock.patch('codex_router.runtime.ROUTER_HOME', home):
                from codex_router.runtime import load_state as load
                fresh = _state(home)
                fresh['setup']['expires'] = int(_time.time()) + 900
                path.write_text(json.dumps(fresh))
                self.assertEqual(load(path)['token'], 'test-token')
                fresh['setup']['expires'] = int(_time.time()) - 1
                path.write_text(json.dumps(fresh))
                with self.assertRaisesRegex(SystemExit, 'credential problem'):
                    load(path)


class SetupHandlerTests(unittest.TestCase):
    def _server(self, home, **over):
        state = {'port': 0, 'token': 'test-token', 'openai_models': [],
                 'setup': {'nonce': 'n' * 16, 'expires': 9_999_999_999}}
        state.update(over)
        import json as _json
        (home / 'mixed-router-state.json').write_text(_json.dumps(state))
        patcher = mock.patch('codex_router.router.ROUTER_HOME', home)
        patcher.start()
        self.addCleanup(patcher.stop)
        server = _start_server(state)
        self.addCleanup(server.shutdown)
        return server

    def _get(self, port, path, origin=None):
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
        headers = {}
        if origin is not None:
            headers['Origin'] = origin
        conn.request('GET', path, headers=headers)
        return conn.getresponse()

    def _post(self, port, path, body, origin=None):
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        if origin is not None:
            headers['Origin'] = origin
        conn.request('POST', path, body=body, headers=headers)
        return conn.getresponse()

    def test_get_form_and_unknown_nonce(self):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        server = self._server(home)
        response = self._get(server.server_port, '/test-token/setup/' + 'n' * 16)
        self.assertEqual(response.status, 200)
        self.assertIn('text/html', response.getheader('Content-Type'))
        self.assertIn(b'<form', response.read())
        response = self._get(server.server_port, '/test-token/setup/wrong')
        self.assertEqual(response.status, 404)

    def test_post_same_origin_stores_key(self):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        server = self._server(home)
        origin = f'http://127.0.0.1:{server.server_port}'
        with mock.patch('urllib.request.urlopen', _key_ok()):
            response = self._post(server.server_port,
                                  '/test-token/setup/' + 'n' * 16,
                                  b'key=sk-live&mode=subscription', origin)
        self.assertEqual(response.status, 200)
        self.assertIn(b'Connected', response.read())
        self.assertEqual((home / 'openrouter.key').read_text(), 'sk-live\n')

    def test_foreign_origin_rejected(self):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        server = self._server(home)
        response = self._post(server.server_port,
                              '/test-token/setup/' + 'n' * 16,
                              b'key=sk-live&mode=subscription',
                              'https://evil.example')
        self.assertEqual(response.status, 403)
        self.assertFalse((home / 'openrouter.key').exists())

    def test_setup_post_over_inherited_listener(self):
        # Production boots socket-activated (no server_bind, no server_port):
        # the setup POST must work there, not just on directly bound servers.
        import socket as _socket
        import threading as _threading
        from codex_router.router import Router
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        state = {'port': 0, 'token': 'test-token', 'openai_models': [],
                 'setup': {'nonce': 'n' * 16, 'expires': 9_999_999_999}}
        (home / 'mixed-router-state.json').write_text(json.dumps(state))
        listener = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        self.addCleanup(listener.close)
        listener.bind(('127.0.0.1', 0))
        listener.listen(5)
        port = listener.getsockname()[1]
        with mock.patch('codex_router.router.ROUTER_HOME', home):
            server = Router(dict(state), fileno=listener.fileno())
        self.addCleanup(server.server_close)
        thread = _threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        with mock.patch('urllib.request.urlopen', _key_ok()):
            conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
            conn.request('POST', '/test-token/setup/' + 'n' * 16,
                         body=b'key=sk-live&mode=subscription',
                         headers={'Content-Type': 'application/x-www-form-urlencoded',
                                  'Origin': f'http://127.0.0.1:{port}'})
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            response.read()
        self.assertEqual((home / 'openrouter.key').read_text(), 'sk-live\n')

    def test_keyless_state_rejects_billable_routes(self):
        from tests.fakes import FakeUpstream, install_fake
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        env = mock.patch.dict(os.environ, {'OPENROUTER_API_KEY': ''})
        env.start()
        self.addCleanup(env.stop)
        server = self._server(home)
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{"output": []}', []))
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        conn.request('POST', '/test-token/responses',
                     body=json.dumps({'model': 'z-ai/glm-5.3-flash',
                                      'input': [{'type': 'message', 'role': 'user',
                                                 'content': 'hi'}]}),
                     headers={'Content-Type': 'application/json'})
        response = conn.getresponse()
        response.read()
        self.assertEqual(response.status, 400)
        self.assertEqual(recorded, [])

    def test_nonce_single_use(self):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        server = self._server(home)
        with mock.patch('urllib.request.urlopen', _key_ok()):
            first = self._post(server.server_port,
                               '/test-token/setup/' + 'n' * 16,
                               b'key=sk-live&mode=subscription')
            self.assertEqual(first.status, 200)
            first.read()
            second = self._post(server.server_port,
                                '/test-token/setup/' + 'n' * 16,
                                b'key=sk-live&mode=subscription')
            self.assertEqual(second.status, 404)


if __name__ == '__main__':
    unittest.main()
