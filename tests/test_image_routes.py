"""Native Codex Images requests retain billing, credentials and result bytes."""
import json
import unittest
from unittest import mock

from ai_router import availability, provider_defs, registry
from tests.fakes import FakeUpstream, install_fake
from tests.harness import isolated_home, post, start_server
from tests.model_route_fixtures import HEADERS, media_success


class ImageRoutesTests(unittest.TestCase):
    def setUp(self):
        isolated_home(self)
        self.response = media_success('openai/gpt-image-2', 'image')
        self.sends = install_fake(self, lambda: self.response)
        self.server = start_server({'port': 0, 'token': 'test-token',
                                    'openai_mode': 'none', 'openai_models': []})
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, model, path='/images/generations', **options):
        payload = {'model': model, 'prompt': 'a red square', **options}
        response = post(self.server.server_port, '/test-token/backend-api/codex' + path,
                        payload, HEADERS)
        raw, status = response.read(), response.status
        response.close()
        return status, raw

    def test_native_image_model_uses_external_key_in_external_only_mode(self):
        status, raw = self.request('gpt-image-2', size='auto', background='opaque')
        self.assertEqual(status, 200)
        self.assertEqual(raw, self.response._buf)
        send, = self.sends
        self.assertEqual(send[:3], (provider_defs.OPENROUTER.host, 'POST', '/api/v1/images'))
        self.assertEqual(json.loads(send[3]), {'model': 'openai/gpt-image-2',
            'prompt': 'a red square', 'background': 'opaque'})
        headers = {k.lower(): v for k, v in send[4].items()}
        self.assertEqual(headers['authorization'], 'Bearer test-key')
        for name in ('x-api-key', 'anthropic-beta', 'chatgpt-account-id'):
            self.assertNotIn(name, headers)

    def test_subscription_images_and_edits_keep_signed_payload_and_login(self):
        self.server.state['openai_mode'] = 'subscription'
        for path in ('/images/generations', '/images/edits'):
            with self.subTest(path=path):
                self.sends.clear()
                self.response = media_success('gpt-image-2', 'image')
                status, _ = self.request('gpt-image-2', path)
                self.assertEqual(status, 200)
                send, = self.sends
                self.assertEqual(send[:3], (provider_defs.OPENAI.host, 'POST',
                    provider_defs.OPENAI.path_for(provider_defs.IMAGES, path[len('/images'):])))
                self.assertEqual(json.loads(send[3]), {'model': 'gpt-image-2', 'prompt': 'a red square'})
                self.assertEqual(send[4]['Authorization'], HEADERS['Authorization'])
                self.assertNotIn('test-key', json.dumps(send[4]))

    def test_explicit_external_image_rows_route_their_exact_model(self):
        self.server.state['openai_mode'] = 'subscription'
        for row in registry.MODELS:
            if row.media_kind != 'image':
                continue
            with self.subTest(model=row.slug):
                self.sends.clear()
                self.response = media_success(row.upstream_id or row.slug, 'image')
                status, _ = self.request(row.slug)
                self.assertEqual(status, 200)
                send, = self.sends
                self.assertEqual(json.loads(send[3])['model'], row.upstream_id or row.slug)
                self.assertEqual(send[4]['Authorization'], 'Bearer test-key')

    def test_external_edits_unknown_models_and_policy_denials_send_nothing(self):
        cases = (('gpt-image-2', '/images/edits', None, True),
                 ('unregistered-image', '/images/generations', None, True),
                 ('gpt-image-2', '/images/generations', [], True),
                 ('gpt-image-2', '/images/generations', None, False))
        for model, path, allowed, permitted in cases:
            with self.subTest(model=model, path=path, allowed=allowed, permitted=permitted):
                self.sends.clear()
                self.server.state['allowed_models'] = allowed
                with mock.patch.object(availability, 'permitted', return_value=permitted):
                    status, _ = self.request(model, path)
                self.assertEqual(status, 400)
                self.assertEqual(self.sends, [])

    def test_malformed_success_is_refused_before_client_completion(self):
        for value in ({'created': 1, 'data': []}, {'data': [{'b64_json': 'QUJD'}]}):
            with self.subTest(value=value):
                self.sends.clear()
                self.response = FakeUpstream(200, json.dumps(value).encode(),
                                            [('Content-Type', 'application/json')])
                status, _ = self.request('gpt-image-2')
                self.assertEqual(status, 502)
                self.assertEqual(len(self.sends), 1)
