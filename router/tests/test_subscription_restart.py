"""An ongoing native chat must resume after its router loses discovery state."""
import json
import threading
import unittest
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from ai_router import provider_defs, subscription_discovery
from tests.fakes import FakeUpstream, install_fake
from tests.harness import post, start_server
from tests.test_subscription_discovery import _Response


HEADERS = {'Authorization': 'Bearer synthetic-client',
           'ChatGPT-Account-ID': 'synthetic-account', 'version': '0.159.2'}
MODEL = 'gpt-6.1-sol'
ROWS = ({'slug': MODEL, 'display_name': 'GPT-6.1-Sol'},)


class SubscriptionRestartTests(unittest.TestCase):
    def setUp(self):
        self.sent = install_fake(
            self, lambda: FakeUpstream(200, b'{"output": []}', []))
        self.real_fetch = subscription_discovery.fetch_native
        patcher = mock.patch.object(
            subscription_discovery, 'fetch_native', return_value=ROWS)
        self.fetch = patcher.start()
        self.addCleanup(patcher.stop)

    def server(self, **overrides):
        server = start_server({'port': 0, 'token': 'test-token',
                               'openai_models': ['gpt-6-sol'], **overrides})
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def request(self, server, model=MODEL, headers=None, path='/responses'):
        payload = {'model': model, 'input': [
            {'role': 'user', 'content': 'Reply RESTART_OK.'}]}
        response = post(server.server_port, '/test-token/backend-api/codex' + path,
                        payload, HEADERS if headers is None else headers)
        return response.status, json.loads(response.read())

    def test_existing_chat_resumes_after_restart_without_models_get(self):
        original = self.server()
        self.assertEqual(self.request(original)[0], 200)
        restarted = self.server()
        self.assertEqual(self.request(restarted)[0], 200)
        self.assertEqual(self.fetch.call_count, 2)
        self.assertEqual(len(self.sent), 2)
        for host, _, path, body, headers in self.sent:
            self.assertEqual(host, provider_defs.OPENAI.host)
            self.assertEqual(path, '/backend-api/codex/responses')
            self.assertEqual(json.loads(body)['model'], MODEL)
            self.assertEqual(headers['Authorization'], HEADERS['Authorization'])

    def test_compaction_can_be_the_first_post_after_restart(self):
        self.assertEqual(self.request(self.server(), path='/responses/compact')[0], 200)
        self.fetch.assert_called_once()
        headers, version, token = self.fetch.call_args.args
        self.assertEqual((version, token), ('0.159.2', 'test-token'))
        self.assertEqual({key: headers[key] for key in HEADERS}, HEADERS)
        self.assertEqual(self.sent[0][2], '/backend-api/codex/responses/compact')

    def test_two_resuming_chats_share_one_discovery_fetch(self):
        server = self.server()
        entered, release = threading.Event(), threading.Event()

        def fetch(*_args):
            entered.set()
            self.assertTrue(release.wait(3))
            return ROWS

        self.fetch.side_effect = fetch
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.request, server)
            self.assertTrue(entered.wait(3))
            second = pool.submit(self.request, server)
            release.set()
            self.assertEqual([first.result()[0], second.result()[0]], [200, 200])
        self.assertEqual(self.fetch.call_count, 1)
        self.assertEqual(len(self.sent), 2)

    def test_account_and_client_version_keep_separate_membership(self):
        server = self.server()
        other = {**HEADERS, 'ChatGPT-Account-ID': 'other-account'}
        upgraded = {**HEADERS, 'version': '0.160.0'}
        self.fetch.side_effect = [ROWS, (), ROWS]
        self.assertEqual(self.request(server)[0], 200)
        self.assertEqual(self.request(server, headers=other)[0], 400)
        self.assertEqual(self.request(server, headers=upgraded)[0], 200)
        self.assertEqual(self.fetch.call_count, 3)
        self.assertEqual(server.state['openai_models'], ['gpt-6-sol'])
        self.assertEqual(len(self.sent), 2)

    def test_unadvertised_model_stays_unknown_without_repeated_discovery(self):
        server = self.server()
        self.fetch.return_value = ()
        for _ in range(2):
            status, body = self.request(server)
            self.assertEqual(status, 400)
            self.assertEqual(body['error']['code'], 'UNKNOWN_MODEL')
        self.assertEqual(self.fetch.call_count, 1)
        self.assertEqual(self.sent, [])

    def test_discovery_failure_is_retryable_and_never_sends_inference(self):
        self.fetch.side_effect = TimeoutError('synthetic discovery timeout')
        status, body = self.request(self.server())
        self.assertEqual(status, 503)
        self.assertEqual(body['error']['code'], 'UPSTREAM_UNAVAILABLE')
        self.assertEqual(self.fetch.call_count, 1)
        self.assertEqual(self.sent, [])

    def test_authentication_rejection_never_grants_membership(self):
        self.fetch.side_effect = urllib.error.HTTPError(
            'https://example.invalid/models', 401, 'Denied', {}, None)
        server = self.server()
        status, body = self.request(server)
        self.assertEqual(status, 401)
        self.assertEqual(body['error']['code'], 'SUBSCRIPTION_AUTH_REJECTED')
        self.assertEqual(server._subscription_snapshots, {})
        self.assertEqual(self.sent, [])

    def test_external_and_no_subscription_requests_do_not_fetch_native_models(self):
        for mode in ('subscription', 'none'):
            with self.subTest(mode=mode):
                self.assertEqual(self.request(
                    self.server(openai_mode=mode), model='z-ai/glm-5.3')[0], 200)
        self.fetch.assert_not_called()
        self.assertTrue(all(row[0] != provider_defs.OPENAI.host for row in self.sent))

    def test_legacy_helper_membership_does_not_require_native_discovery(self):
        self.assertEqual(self.request(self.server(), model='gpt-5.6-luna')[0], 200)
        self.fetch.assert_not_called()
        self.assertEqual(self.sent[0][0], provider_defs.OPENAI.host)

    def test_unidentified_request_does_not_fetch_another_accounts_models(self):
        status, body = self.request(self.server(), headers={})
        self.assertEqual(status, 400)
        self.assertEqual(body['error']['code'], 'UNKNOWN_MODEL')
        self.fetch.assert_not_called()
        self.assertEqual(self.sent, [])

    def test_discovery_get_drops_post_body_headers(self):
        seen = {}

        def urlopen(request, timeout):
            seen.update({key.lower(): value for key, value in request.header_items()})
            return _Response(json.dumps({'models': list(ROWS)}).encode())

        rows = self.real_fetch({**HEADERS, 'Content-Length': '99',
                               'Content-Encoding': 'gzip', 'Content-Type': 'application/json'},
                              '0.159.2', 'test-token', _urlopen=urlopen)
        self.assertEqual(rows, ROWS)
        self.assertEqual(seen['authorization'], HEADERS['Authorization'])
        for key in ('content-length', 'content-encoding', 'content-type'):
            self.assertNotIn(key, seen)


if __name__ == '__main__':
    unittest.main()
