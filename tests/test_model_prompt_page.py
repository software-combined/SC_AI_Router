"""The new-model prompt page, route and restart action (Plan 135).

Render checks stay pure; the route checks drive the real handler over
loopback with the restart runner faked, mirroring tests/test_setup_handler.py.
"""
import http.client
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from ai_router import catalogue, model_prompt, model_prompt_page
from ai_router.credentials import Credentials
from tests.test_model_prompt import EXTRA, _with_extra
from tests.harness import start_server as _start_server, tmp_home


class PageRenderTests(unittest.TestCase):
    def test_pending_page_lists_names_and_caps_the_extras(self):
        rows = [(f'vendor/model-{i}', f'Model {i}') for i in range(15)]
        page = model_prompt_page.pending(rows).decode()
        self.assertIn('Model 0', page)
        self.assertIn('and 3 more', page)
        self.assertNotIn('Model 12', page)
        self.assertIn('value="vendor/model-14"', page)  # every row is acknowledged
        self.assertIn('Restart Codex', page)
        self.assertIn('Later', page)

    def test_nothing_to_do_offers_no_restart(self):
        page = model_prompt_page.nothing_to_do().decode()
        self.assertNotIn('<form', page)
        self.assertNotIn('Restart Codex', page)


class RestartTests(unittest.TestCase):
    def test_darwin_quits_and_reopens_the_app_by_name(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return SimpleNamespace(returncode=0)

        self.assertTrue(model_prompt_page.restart_codex(fake_run, platform='darwin'))
        self.assertEqual(calls, [['osascript', '-e', 'quit app "Codex"'],
                                 ['open', '-a', 'Codex']])

    def test_unsupported_platform_stays_false(self):
        self.assertFalse(model_prompt_page.restart_codex(
            lambda *a, **k: SimpleNamespace(returncode=0), platform='linux'))

    def test_a_failed_reopen_after_a_successful_quit_stays_false(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return SimpleNamespace(returncode=0 if cmd[0] == 'osascript' else 1)

        self.assertFalse(model_prompt_page.restart_codex(fake_run, platform='darwin'))
        self.assertEqual(calls, [['osascript', '-e', 'quit app "Codex"'],
                                 ['open', '-a', 'Codex']])

    def test_a_refused_quit_reports_failure_without_reopening(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return SimpleNamespace(returncode=1 if cmd[0] == 'osascript' else 0)

        self.assertFalse(model_prompt_page.restart_codex(fake_run, platform='darwin'))
        self.assertEqual(calls, [['osascript', '-e', 'quit app "Codex"']])


class PromptRouteTests(unittest.TestCase):
    def _server(self, home):
        state = {'port': 0, 'token': 'test-token', 'openai_models': []}
        (home / 'mixed-router-state.json').write_text(json.dumps(state))
        server = _start_server(state, credentials=Credentials(state, home, env={}))
        self.addCleanup(server.shutdown)
        return server

    def _offer(self, home):
        model_prompt.pending(home)  # seed the scope with today's rows
        with mock.patch.object(catalogue, 'MODELS', _with_extra()):
            nonce, _ = model_prompt.notice(home)
        return nonce

    def _get(self, port, path):
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
        self.addCleanup(conn.close)
        conn.request('GET', path)
        return conn.getresponse()

    def _post(self, port, path, body, origin=None):
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
        self.addCleanup(conn.close)
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        if origin is not None:
            headers['Origin'] = origin
        conn.request('POST', path, body=body, headers=headers)
        return conn.getresponse()

    def test_offer_page_then_restart_click_acknowledges_once(self):
        home = tmp_home(self)
        server = self._server(home)
        nonce = self._offer(home)
        path = f'/test-token/model-prompt/{nonce}'
        with mock.patch.object(catalogue, 'MODELS', _with_extra()):
            response = self._get(server.server_port, path)
            body = response.read()
        self.assertEqual(response.status, 200)
        self.assertIn(b'Restart Codex', body)
        self.assertIn(EXTRA.encode(), body)
        restarts = []
        with mock.patch.object(catalogue, 'MODELS', _with_extra()), \
                mock.patch.object(model_prompt_page, 'restart_codex',
                                  side_effect=lambda *a, **k: restarts.append(1) or True):
            response = self._post(server.server_port, path, b'action=restart',
                                  f'http://127.0.0.1:{server.server_port}')
            done = response.read()
        self.assertEqual(response.status, 200)
        self.assertIn(b'Restarting Codex', done)
        self.assertEqual(restarts, [1])
        with mock.patch.object(catalogue, 'MODELS', _with_extra()):
            self.assertIsNone(model_prompt.check_notice(home, 'codex', nonce))

    def test_later_acknowledges_without_restarting(self):
        home = tmp_home(self)
        server = self._server(home)
        nonce = self._offer(home)
        with mock.patch.object(catalogue, 'MODELS', _with_extra()), \
                mock.patch.object(model_prompt_page, 'restart_codex',
                                  side_effect=AssertionError('must not restart')):
            response = self._post(server.server_port,
                                  f'/test-token/model-prompt/{nonce}',
                                  b'action=later',
                                  f'http://127.0.0.1:{server.server_port}')
            body = response.read()
        self.assertEqual(response.status, 200)
        self.assertIn(b'No problem', body)
        with mock.patch.object(catalogue, 'MODELS', _with_extra()):
            self.assertEqual(model_prompt.pending(home), [])

    def test_unknown_nonce_renders_the_expired_page(self):
        home = tmp_home(self)
        server = self._server(home)
        self._offer(home)
        response = self._get(server.server_port, '/test-token/model-prompt/wrong')
        self.assertEqual(response.status, 404)
        self.assertIn(b'no longer valid', response.read())

    def test_cross_origin_post_is_refused(self):
        home = tmp_home(self)
        server = self._server(home)
        nonce = self._offer(home)
        with mock.patch.object(model_prompt_page, 'restart_codex',
                               side_effect=AssertionError('must not restart')):
            response = self._post(server.server_port,
                                  f'/test-token/model-prompt/{nonce}',
                                  b'action=restart', 'http://evil.example')
        self.assertEqual(response.status, 403)

    def test_failed_restart_renders_the_manual_instruction(self):
        home = tmp_home(self)
        server = self._server(home)
        nonce = self._offer(home)
        with mock.patch.object(catalogue, 'MODELS', _with_extra()), \
                mock.patch.object(model_prompt_page, 'restart_codex',
                                  return_value=False):
            response = self._post(server.server_port,
                                  f'/test-token/model-prompt/{nonce}',
                                  b'action=restart',
                                  f'http://127.0.0.1:{server.server_port}')
            body = response.read()
        self.assertEqual(response.status, 200)
        self.assertIn(b'Restart Codex yourself', body)


if __name__ == '__main__':
    unittest.main()
