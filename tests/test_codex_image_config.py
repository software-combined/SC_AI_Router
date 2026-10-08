"""Codex image capability uses a local credential and requires no ChatGPT login."""
import tomllib
import unittest
from urllib.parse import urlsplit

from tests.install_fixtures import install_mod

switch = install_mod._client_choice._switch


class CodexImageConfigTests(unittest.TestCase):
    def test_external_only_variants_enable_images_with_install_scoped_local_auth(self):
        for mode, variant in (('none', 'default'), ('subscription', 'switched')):
            for token in ('first-install-token', 'other-install-token'):
                with self.subTest(mode=mode, variant=variant, token=token):
                    doc = tomllib.loads(switch.build('/r', {'port': 4321, 'token': token},
                                                    mode, False, variant))
                    self.assertEqual(doc['model_provider'], 'scg_router')
                    provider = doc['model_providers']['scg_router']
                    self.assertIs(provider['requires_openai_auth'], False)
                    self.assertEqual(provider['http_headers']['x-scg-codex-route'], 'routed')
                    self.assertEqual(provider['http_headers']['x-openai-actor-authorization'],
                                     'Bearer ' + token)
                    self.assertEqual(urlsplit(provider['base_url']).hostname, '127.0.0.1')
                    self.assertNotIn('env_key', provider)
                    self.assertNotIn('experimental_bearer_token', provider)

    def test_subscription_variants_do_not_carry_local_image_auth(self):
        for variant in ('default', 'switched_back'):
            with self.subTest(variant=variant):
                block = switch.build('/r', {'port': 4321, 'token': 'install-token'},
                                     'subscription', False, variant)
                self.assertNotIn('x-openai-actor-authorization', block)
                self.assertNotIn('model_provider =', block)
                provider = tomllib.loads(block).get('model_providers', {}).get('scg_router')
                if provider is not None:
                    self.assertIs(provider['requires_openai_auth'], True)
