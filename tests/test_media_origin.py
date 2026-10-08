"""Images follow the originating chat, not another turn or the client profile."""
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from ai_router import media_origin, provider_defs, request_context, subscription_recovery
from ai_router.errors import PreparationError
from tests.fakes import FakeUpstream, install_fake
from tests.harness import isolated_home, post, start_server
from tests.model_route_fixtures import HEADERS, media_success


class OriginRoutesTests(unittest.TestCase):
    def setUp(self):
        isolated_home(self)
        self.reply = lambda: FakeUpstream(200, b'{"output":[]}',
                                         [('Content-Type', 'application/json')])
        self.sends = install_fake(self, lambda: self.reply())
        self.server = start_server({'port': 0, 'token': 'test-token',
            'openai_mode': 'subscription', 'openai_models': ['gpt-6-astra']})
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, path, payload, headers):
        reply = post(self.server.server_port, '/test-token' + path, payload, headers)
        status, raw = reply.status, reply.read()
        reply.close()
        return status, raw

    def chat(self, model, turn):
        headers = {**HEADERS, 'X-Codex-Turn-Metadata': json.dumps({'turn_id': turn})}
        status, _ = self.request('/responses', {'model': model,
            'input': [{'role': 'user', 'content': 'a synthetic drawing task'}]}, headers)
        self.assertEqual(status, 200)

    def image(self, turn, model='gpt-image-2', **options):
        self.reply = lambda: media_success('openai/gpt-image-2', 'image')
        return self.request('/images/generations', {'model': model,
            'prompt': 'a red square', **options},
            {**HEADERS, 'X-Codex-Image-Turn-Id': turn})

    def test_interleaved_native_and_external_chats_keep_their_connections(self):
        self.chat('openai/gpt-6-luna', 'external-turn')
        self.chat('gpt-6-astra', 'native-turn')
        self.sends.clear()
        for turn, host, path, model in (
                ('external-turn', provider_defs.OPENROUTER.host, '/api/v1/images', 'openai/gpt-image-2'),
                ('native-turn', provider_defs.OPENAI.host, '/backend-api/codex/images/generations', 'gpt-image-2')):
            with self.subTest(turn=turn):
                self.assertEqual(self.image(turn)[0], 200)
                send = self.sends[-1]
                self.assertEqual((send[0], send[2], json.loads(send[3])['model']), (host, path, model))
                headers = {k.lower(): v for k, v in send[4].items()}
                self.assertEqual(headers['authorization'], 'Bearer test-key' if turn == 'external-turn'
                                 else HEADERS['Authorization'])
                if turn == 'external-turn':
                    self.assertNotIn('chatgpt-account-id', headers)

    def test_unknown_or_conflicting_turn_never_guesses_from_profile(self):
        self.chat('gpt-6-astra', 'conflict')
        self.chat('openai/gpt-6-luna', 'conflict')
        self.sends.clear()
        for turn in ('unknown', 'conflict'):
            with self.subTest(turn=turn):
                self.assertEqual(self.image(turn)[0], 400)
                self.assertEqual(self.sends, [])

    def test_explicit_image_model_stays_separate_and_cannot_change_provider(self):
        self.chat('gpt-6-astra', 'native')
        self.chat('openai/gpt-6-luna', 'external')
        self.sends.clear()
        self.assertEqual(self.image('native', 'openai/gpt-image-2')[0], 400)
        self.assertEqual(self.sends, [])
        self.assertEqual(self.image('external', 'openai/gpt-image-2.5-flare')[0], 200)
        self.assertEqual(json.loads(self.sends[-1][3])['model'], 'openai/gpt-image-2.5-flare')

    def test_explicit_chat_model_works_without_native_turn_header(self):
        self.reply = lambda: media_success('openai/gpt-image-2', 'image')
        status, _ = self.request('/images/generations', {'chat_model': 'openai/gpt-6-luna',
            'model': 'gpt-image-2', 'prompt': 'a red square'}, HEADERS)
        self.assertEqual(status, 200)
        self.assertEqual(self.sends[-1][0], provider_defs.OPENROUTER.host)

    def test_conflicting_explicit_chat_model_does_not_override_turn(self):
        self.chat('gpt-6-astra', 'native')
        self.sends.clear()
        self.assertEqual(self.image('native', chat_model='openai/gpt-6-luna')[0], 400)
        self.assertEqual(self.sends, [])

    def test_external_edit_translates_inline_images_but_refuses_native_file_ids(self):
        self.chat('openai/gpt-6-luna', 'external')
        self.reply = lambda: media_success('openai/gpt-image-2', 'image')
        self.sends.clear()
        headers = {**HEADERS, 'x-codex-image-turn-id': 'external'}
        payload = {'model': 'gpt-image-2', 'prompt': 'make the square green',
                   'images': [{'image_url': 'data:image/png;base64,QUJD'}]}
        self.assertEqual(self.request('/images/edits', payload, headers)[0], 200)
        self.assertEqual(json.loads(self.sends[-1][3])['input_references'],
            [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,QUJD'}}])
        payload['images'] = [{'file_id': 'file-native'}]
        self.sends.clear()
        self.assertEqual(self.request('/images/edits', payload, headers)[0], 400)
        self.assertEqual(self.sends, [])

    def test_changed_policy_denies_media_without_provider_fallback(self):
        self.chat('openai/gpt-6-luna', 'external')
        self.server.state['allowed_models'] = ['openai/gpt-6-luna']
        self.sends.clear()
        self.assertEqual(self.image('external')[0], 400)
        self.assertEqual(self.sends, [])

    def test_recovered_native_turn_keeps_admitted_connection_but_obeys_current_mode(self):
        model = 'gpt-resumed-fixture'
        with mock.patch.object(subscription_recovery, 'request_models', return_value=(model,)):
            self.chat(model, 'recovered')
        self.sends.clear()
        self.assertEqual(self.image('recovered')[0], 200)
        self.assertEqual(self.sends[-1][:3],
                         (provider_defs.OPENAI.host, 'POST', '/backend-api/codex/images/generations'))
        self.server.state['openai_mode'] = 'none'
        self.sends.clear()
        self.assertEqual(self.image('recovered')[0], 400)
        self.assertEqual(self.sends, [])


class TurnBindingTests(unittest.TestCase):
    def test_expiry_and_capacity_remove_old_bindings(self):
        routes = media_origin.TurnRoutes()
        prepared = SimpleNamespace(provider='openrouter',
            context=request_context.resolve('openai/gpt-6-luna', request_context.capture()))
        with mock.patch.object(media_origin, 'MAX_TURNS', 1), \
                mock.patch.object(media_origin.time, 'monotonic', return_value=1):
            routes.remember('old', prepared)
            routes.remember('kept', prepared)
            with self.assertRaises(PreparationError):
                routes.lookup('old')
            self.assertEqual(routes.lookup('kept').provider, 'openrouter')
        with mock.patch.object(media_origin.time, 'monotonic', return_value=3602):
            with self.assertRaises(PreparationError):
                routes.lookup('kept')

    def test_codex_metadata_forms_are_case_insensitive_and_content_free(self):
        for payload, headers in (({'client_metadata': {'turn_id': 'one'}}, {}),
                ({'client_metadata': {'x-codex-turn-metadata': '{"turn_id":"one"}'}}, {}),
                ({}, {'X-Codex-Turn-Metadata': '{"turn_id":"one"}'})):
            self.assertEqual(media_origin.turn_id(payload, headers), 'one')
        self.assertIsNone(media_origin.turn_id({}, {'x-codex-turn-metadata': 'not-json'}))


if __name__ == '__main__':
    unittest.main()
