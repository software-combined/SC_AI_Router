"""ChatGPT requests on the switched Codex route never leave the machine.

Switch Codex points Codex at the router through a provider entry that needs
no OpenAI sign-in and sends `x-scg-codex-route` with every request. Codex
then sends no ChatGPT credentials, so a subscription turn forwarded as usual
failed upstream and Codex retried it five times before showing an error with
the router's address. These pin the one local answer on that route, and the
routes that must not change.
"""
import dataclasses
import json
import unittest
from unittest import mock

from ai_router import availability, codex_route
from ai_router.registry import by_slug
from tests.fakes import FakeUpstream, install_fake
from tests.harness import auth_file, post, start_server, test_state

ROUTED = {'x-scg-codex-route': 'routed'}
TWIN = 'openai/gpt-6-astra'
TWIN_PICK = 'Pick "OpenAI: GPT-6 Astra · OpenRouter"'
HELPER = {'x-codex-turn-metadata': json.dumps({'thread_source': 'thread_title'})}


class SwitchedRouteTests(unittest.TestCase):
    def _send(self, body, headers=None, path='/responses', **state):
        """(status, content type, body bytes, upstream calls) for one request."""
        recorded = install_fake(self, lambda: FakeUpstream(
            200, b'{"output": []}', [('Content-Type', 'application/json')]))
        config = test_state(auth_file(self))
        config['openai_models'] = ['gpt-6-astra', 'gpt-5.5']
        config.update(state)
        server = start_server(config)
        self.addCleanup(server.shutdown)
        response = post(server.server_port, '/test-token' + path, body, headers)
        return (response.status, response.getheader('Content-Type'),
                response.read(), recorded)

    def _refusal(self, body, headers=ROUTED, path='/responses', **state):
        """The final 400's message; the request must not have been sent."""
        status, kind, raw, recorded = self._send(body, headers, path, **state)
        self.assertEqual((status, kind, recorded), (400, 'application/json', []))
        error = json.loads(raw)['error']
        self.assertEqual(error['code'], 'invalid_prompt')
        return error['message']

    def _snapshot(self, models):
        saved = dict(availability._SNAPSHOTS)
        availability._SNAPSHOTS['openrouter'] = {
            'provider': 'openrouter', 'key': 'k', 'region': 'global',
            'models': frozenset(models), 'fetched_at': 0}
        self.addCleanup(availability._SNAPSHOTS.update, saved)
        self.addCleanup(availability._SNAPSHOTS.clear)

    def test_a_streaming_turn_gets_one_final_frame_and_nothing_is_sent(self):
        with mock.patch('ai_router.router.log_event') as log:
            status, kind, raw, recorded = self._send(
                {'model': 'gpt-6-astra', 'input': [], 'stream': True}, ROUTED)
        self.assertEqual((status, kind, recorded), (200, 'text/event-stream', []))
        self.assertTrue(raw.startswith(b'event: response.failed\ndata: '))
        event = json.loads(raw.split(b'data: ', 1)[1])
        self.assertEqual(event['type'], 'response.failed')
        self.assertEqual(event['response']['error']['code'], 'invalid_prompt')
        self.assertIn(TWIN_PICK, event['response']['error']['message'])
        # Codex shows this text as sent: no address, path token or retry hint.
        for leaked in (b'test-token', b'127.0.0.1', b'http', b'temporarily unavailable'):
            self.assertNotIn(leaked, raw)
        rejected = next(c.kwargs for c in log.call_args_list
                        if c.args == ('request_rejected',))
        self.assertEqual((rejected['status'], rejected['code']), (200, 'invalid_prompt'))

    def test_other_requests_get_a_final_400_and_nothing_is_sent(self):
        for path in ('/responses', '/responses/compact'):
            with self.subTest(path=path):
                message = self._refusal({'model': 'gpt-6-astra', 'input': []}, path=path)
                self.assertIn(TWIN_PICK, message)

    def test_the_header_decides_in_any_case_even_with_a_login(self):
        # Keyed on the route header, never on missing credentials.
        for headers in ({'X-SCG-Codex-Route': 'routed'}, {'X-Scg-Codex-Route': 'routed'},
                        {**ROUTED, 'Authorization': 'Bearer subscription-secret'}):
            with self.subTest(headers=headers):
                self._refusal({'model': 'gpt-6-astra', 'input': []}, headers)

    def test_native_paths_get_the_no_subscription_answers(self):
        for path, code in (('/alpha/search', 'NATIVE_UNAVAILABLE'),
                           ('/guardian', 'GUARDIAN_NEEDS_SUBSCRIPTION')):
            with self.subTest(path=path):
                status, _, raw, recorded = self._send({'input': []}, ROUTED, path)
                self.assertEqual((status, recorded), (404, []))
                self.assertEqual(json.loads(raw)['error']['code'], code)

    def test_routed_models_are_forwarded_without_the_route_header(self):
        status, _, _, recorded = self._send(
            {'model': 'deepseek/deepseek-v4.1-flash-1017', 'input': []},
            {'X-SCG-Codex-Route': 'routed'})
        self.assertEqual(status, 200)
        self.assertEqual([call[0] for call in recorded], ['openrouter.ai'])
        self.assertNotIn(codex_route.HEADER, {name.lower() for name in recorded[0][4]})

    def test_without_the_header_a_chatgpt_turn_is_forwarded_as_before(self):
        status, _, _, recorded = self._send({'model': 'gpt-6-astra', 'input': []})
        self.assertEqual(status, 200)
        self.assertEqual([(call[0], call[2]) for call in recorded],
                         [('chatgpt.com', '/backend-api/codex/responses')])

    def test_the_twin_is_named_only_when_this_machines_picker_lists_it(self):
        generic = codex_route.message()
        turn = {'model': 'gpt-6-astra', 'input': []}
        self.assertEqual(self._refusal({'model': 'gpt-5.5', 'input': []}), generic)
        # GPT-5.6 Terra has no OpenRouter row any more, so nothing is named.
        self.assertEqual(self._refusal({'model': 'gpt-5.6-terra', 'input': []},
                                       openai_models=['gpt-6-astra', 'gpt-5.6-terra']), generic)
        self.assertEqual(self._refusal(turn, allowed_models=['deepseek/deepseek-v4.1-flash-1017']),
                         generic)
        unlisted = dataclasses.replace(by_slug(TWIN), listed=False)
        with mock.patch.dict('ai_router.registry.BY_SLUG', {TWIN: unlisted}):
            self.assertEqual(self._refusal(turn), generic)
        self._snapshot({'deepseek/deepseek-v4.1-flash-1017'})
        self.assertEqual(self._refusal(turn), generic)

    def test_helper_turns_are_refused_even_with_the_twin_fallback_on(self):
        # The helper fallback takes over only after an upstream refusal, and
        # this route sends nothing: neither the subscription nor the twin.
        message = self._refusal({'model': 'gpt-5.6-luna', 'input': []},
                                {**ROUTED, **HELPER}, openai_helper_fallback=True)
        self.assertIn('Pick "OpenAI: GPT-6 Luna · OpenRouter"', message)


if __name__ == '__main__':
    unittest.main()
