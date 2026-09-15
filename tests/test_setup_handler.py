"""First-run key window over loopback (Plan 047 G). No network: OpenRouter
key checks run through an injected urlopen fake."""
import http.client
import json
import os
import shutil
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from ai_router.credentials import Credentials
from tests.test_setup import _key_ok, _state
from tests.harness import start_server as _start_server


class SetupHandlerTests(unittest.TestCase):
    def _server(self, home, **over):
        state = {'port': 0, 'token': 'test-token', 'openai_models': [],
                 'setup': {'nonce': 'n' * 16, 'expires': 9_999_999_999}}
        state.update(over)
        (home / 'mixed-router-state.json').write_text(json.dumps(state))
        server = _start_server(state, credentials=Credentials(state, home, env={}))
        self.addCleanup(server.shutdown)
        return server

    def _get(self, port, path, origin=None):
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
        headers = {}
        if origin is not None:
            headers['Origin'] = origin
        conn.request('GET', path, headers=headers)
        return conn.getresponse()

    def _post(self, port, path, body, origin=None, accept=None):
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        if origin is not None:
            headers['Origin'] = origin
        if accept is not None:
            headers['Accept'] = accept
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

    def test_json_accept_returns_json_to_the_popup(self):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        server = self._server(home)
        with mock.patch('urllib.request.urlopen', _key_ok()):
            response = self._post(server.server_port,
                                  '/test-token/setup/' + 'n' * 16,
                                  b'key=sk-live&mode=none&profile=dev',
                                  accept='application/json')
            payload = json.loads(response.read())
        self.assertEqual(response.status, 200)
        self.assertIn('application/json', response.getheader('Content-Type'))
        self.assertEqual(payload['ok'], True)
        self.assertEqual(payload['mode'], 'none')

    def test_json_accept_persists_the_claude_choice(self):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        server = self._server(home)
        with mock.patch('urllib.request.urlopen', _key_ok()):
            response = self._post(server.server_port,
                                  '/test-token/setup/' + 'n' * 16,
                                  b'key=sk-live&mode=none&profile=general'
                                  b'&claude_mode=subscription',
                                  accept='application/json')
            payload = json.loads(response.read())
        saved = json.loads((home / 'mixed-router-state.json').read_text())
        self.assertEqual(payload['claude_mode'], 'subscription')
        self.assertEqual(saved['claude_mode'], 'subscription')
        self.assertEqual(saved['anthropic_mode'], 'subscription')

    def test_browser_page_names_the_client_it_serves(self):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        server = self._server(home, clients='claude')
        with mock.patch('urllib.request.urlopen', _key_ok()):
            response = self._post(server.server_port,
                                  '/test-token/setup/' + 'n' * 16,
                                  b'key=sk-live&mode=none')
            body = response.read()
        self.assertIn(b'Restart Claude Code', body)
        self.assertNotIn(b'restart Codex', body)

    def test_claude_only_post_leaves_codex_settings_alone(self):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        server = self._server(home, clients='claude', openai_mode='none')
        (home / 'mixed-router-state.json').write_text(json.dumps(
            json.loads((home / 'mixed-router-state.json').read_text()) | {
                'agents_profile': 'dev'}))
        with mock.patch('urllib.request.urlopen', _key_ok()), \
                mock.patch('ai_router.agents.install') as installed:
            response = self._post(server.server_port,
                                  '/test-token/setup/' + 'n' * 16,
                                  b'key=sk-live&claude_mode=none',
                                  accept='application/json')
            payload = json.loads(response.read())
        saved = json.loads((home / 'mixed-router-state.json').read_text())
        self.assertEqual(payload['ok'], True)
        self.assertEqual(saved['openai_mode'], 'none', 'Codex mode untouched')
        self.assertEqual(saved['agents_profile'], 'dev', 'starter untouched')
        self.assertEqual(saved['claude_mode'], 'none')
        installed.assert_not_called()

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
        import socket
        import threading
        from ai_router.router import Router
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(listener.close)
        listener.bind(('127.0.0.1', 0))
        listener.listen(5)
        port = listener.getsockname()[1]
        # Inherited fd must be for the configured port (production launchd
        # declares SockServiceName = state port); foreign fds fall back.
        state = _state(home, port=port,
                       setup={'nonce': 'n' * 16, 'expires': 9_999_999_999})
        (home / 'mixed-router-state.json').write_text(json.dumps(state))
        server = Router(dict(state), fileno=listener.fileno(),
                        credentials=Credentials(dict(state), home, env={}))
        self.addCleanup(server.server_close)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
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


    def test_a_non_ascii_nonce_answers_404(self):
        # Raw 0xff over the socket: http.server never percent-decodes the
        # target, so %FF would arrive as ASCII and miss the point. Before
        # the bytes compare this dropped the connection (TypeError).
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        server = self._server(home)
        sock = socket.create_connection(('127.0.0.1', server.server_port), timeout=10)
        self.addCleanup(sock.close)
        sock.sendall(b'GET /test-token/setup/\xff HTTP/1.1\r\n'
                     b'Host: 127.0.0.1\r\nConnection: close\r\n\r\n')
        data = b''
        while b'\r\n\r\n' not in data:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
        self.assertIn(b'404', data.split(b'\r\n', 1)[0])


if __name__ == '__main__':
    unittest.main()
