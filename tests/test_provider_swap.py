"""Plan 141 acceptance proof: a second provider is one table entry.

Registers a synthetic `acme` provider on top of the real table and asserts
the whole surface follows it: routing target, credential, picker label,
capability gates, the portco allowlist, and per-provider fail-closed
behaviour. No network: the credential is a file in a temp home.
"""
import http.client
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ai_router import (capabilities, catalogue, claude, credentials, key_store,
                       model_refresh, models, provider_defs, providers,
                       registry, setup, upstream)
from tests.fakes import FakeUpstream, install_fake
from tests.harness import start_server

ACME_KEY = 'ACME_API_KEY'
ACME_FILE = 'acme.key'
ACME_ROW = {
    'slug': 'acme/one', 'provider': 'acme', 'display_name': 'Acme: One \u00b7 Acme',
    'vendor': 'Acme', 'reasoning': ['low'], 'default_reasoning': 'low',
    'modalities': ['text'], 'excluded_efforts': [], 'schema_mode': 'native', 'history_mode': 'native',
    'max_tools': None, 'drop_images': False, 'context_window': 8000,
    'priority': 200, 'max_output_tokens': 1000, 'reasoning_summary': 'none',
    'apply_patch': 'none', 'experimental_tools': [], 'web_search': True,
    'tier': 'verified',
}


def _acme_def():
    """A second external provider with its own dialect, shapes and key."""
    return provider_defs.ProviderDef(
        id='acme', label='Acme', kind=provider_defs.EXTERNAL,
        host='acme.example', responses_path='/v1', messages_path='/anthropic',
        key=provider_defs.KeySpec(ACME_KEY, ACME_FILE, example='sk-acme-...'),
        catalogue_shape='manual',
        key_info_url='https://acme.example/v1/key', key_info_shape='plain',
        dialect=provider_defs.DIALECT_OPENAI_COMPATIBLE)


class ProviderSwapTests(unittest.TestCase):
    """The fixture provider is registered exactly as a real one would be."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(self.home), True)
        self._defs = (provider_defs.PROVIDERS, provider_defs.BY_ID)
        self._registry = (registry.MODELS, registry.BY_SLUG)
        self._caps = (capabilities.EXTERNAL_MODELS, capabilities.IMAGE_INPUT_MODELS,
                      capabilities.REASONING_LEVELS, capabilities.EXCLUDED_EFFORTS)
        # Registered before the first mutation so a failure mid-setup cannot
        # leak the synthetic provider or rows into the rest of the suite.
        self.addCleanup(self._restore)
        provider_defs.PROVIDERS = provider_defs.PROVIDERS + (_acme_def(),)
        provider_defs.BY_ID = {p.id: p for p in provider_defs.PROVIDERS}
        existing = json.loads(
            Path(registry.__file__).with_name('models.json').read_text())
        rows = registry.load(json.dumps(existing + [ACME_ROW]))
        registry.MODELS, registry.BY_SLUG = rows, {m.slug: m for m in rows}
        model_refresh.apply(rows)

    def _restore(self):
        provider_defs.PROVIDERS, provider_defs.BY_ID = self._defs
        registry.MODELS, registry.BY_SLUG = self._registry
        (capabilities.EXTERNAL_MODELS, capabilities.IMAGE_INPUT_MODELS,
         capabilities.REASONING_LEVELS, capabilities.EXCLUDED_EFFORTS) = self._caps

    def _credentials(self, env=None):
        return credentials.Credentials({'port': 0, 'token': 't', 'openai_models': []},
                                       self.home, env or {})

    def _key_file(self, name, text):
        path = self.home / name
        path.write_text(text)
        os.chmod(path, 0o600)
        return path

    def _post(self, port, model):
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
        try:
            conn.request('POST', '/test-token/responses',
                         json.dumps({'model': model, 'input': []}),
                         {'Content-Type': 'application/json'})
            response = conn.getresponse()
            return response.status, response.read().decode()
        finally:
            conn.close()

    def test_responses_turn_routes_to_the_new_host_with_its_own_key(self):
        self._key_file(ACME_FILE, 'sk-acme\n')
        self._key_file('openrouter.key', 'sk-or\n')
        provider = providers.select('acme/one', '/responses', [])
        self.assertEqual(provider.name, 'acme')
        prepared = provider.prepare(
            'acme/one', '/responses', {'model': 'acme/one', 'input': []}, b'raw',
            {'Authorization': 'Bearer subscription-secret'}, self._credentials())
        self.assertEqual(prepared.host, 'acme.example')
        self.assertEqual(prepared.path, '/v1/responses')
        self.assertEqual(prepared.headers['Authorization'], 'Bearer sk-acme')
        self.assertNotIn('subscription-secret', json.dumps(prepared.headers))

    def test_messages_turn_uses_the_same_definitions_messages_prefix(self):
        self._key_file(ACME_FILE, 'sk-acme\n')
        provider = claude.select('acme/one', '/v1/messages')
        prepared = provider.prepare('acme/one', '/v1/messages',
                                    {'model': 'acme/one'}, b'{"model":"acme/one"}',
                                    {}, self._credentials())
        self.assertEqual(prepared.host, 'acme.example')
        self.assertEqual(prepared.path, '/anthropic/v1/messages')
        self.assertEqual(prepared.headers['Authorization'], 'Bearer sk-acme')

    def test_picker_labels_come_from_the_new_definitions_label(self):
        row = registry.by_slug('acme/one')
        entry = catalogue.external_entry(row)
        self.assertEqual(entry['display_name'], 'Acme: One \u00b7 Acme')
        self.assertIn('Acme billing.', entry['description'])
        self.assertEqual(catalogue.catalog_name(row), 'Acme: One')

    def test_capability_gates_cover_the_new_providers_rows(self):
        self.assertIn('acme/one', capabilities.EXTERNAL_MODELS)
        self.assertEqual(capabilities.catalogue_patch('acme/one')['input_modalities'],
                         ['text'])
        with self.assertRaises(ValueError):
            capabilities.check_effort('acme/one', 'max')  # the row offers low only

    def test_portco_allowlist_gates_the_new_provider_too(self):
        from ai_router.errors import UnknownModel
        with self.assertRaises(UnknownModel):
            providers.select('acme/one', '/responses', [], allowed=[])
        self.assertEqual(
            providers.select('acme/one', '/responses', [], allowed=['acme/one']).name,
            'acme')

    def test_one_missing_key_does_not_stop_the_other_provider(self):
        # Only OpenRouter is configured: acme fails closed on its own while
        # the configured provider still resolves and still routes.
        self._key_file('openrouter.key', 'sk-or\n')
        creds = self._credentials()
        self.assertEqual(creds.key_for('openrouter'), 'sk-or')
        self.assertIsInstance(creds.key_missing('acme'), LookupError)
        with self.assertRaises(LookupError):
            providers.select('acme/one', '/responses', []).prepare(
                'acme/one', '/responses', {'model': 'acme/one', 'input': []},
                b'raw', {}, creds)
        self.assertEqual(
            providers.select('z-ai/glm-5.3', '/responses', []).name, 'openrouter')

    def test_key_lookup_order_is_the_definitions(self):
        self._key_file(ACME_FILE, 'sk-file\n')
        self.assertEqual(self._credentials({ACME_KEY: 'sk-env'}).key_for('acme'), 'sk-env')
        self.assertEqual(self._credentials().key_for('acme'), 'sk-file')

    def test_a_provider_without_the_responses_path_is_refused_for_codex(self):
        self._key_file(ACME_FILE, 'sk-acme\n')
        messages_only = provider_defs.ProviderDef(
            id='acme', label='Acme', kind=provider_defs.EXTERNAL, host='acme.example',
            messages_path='', key=provider_defs.KeySpec(ACME_KEY, ACME_FILE),
            dialect=provider_defs.DIALECT_OPENAI_COMPATIBLE)
        provider_defs.BY_ID['acme'] = messages_only
        provider_defs.PROVIDERS = tuple(messages_only if p.id == 'acme' else p
                                        for p in provider_defs.PROVIDERS)
        with self.assertRaises(ValueError):
            providers.select('acme/one', '/responses', [])
        self.assertEqual(claude.select('acme/one', '/v1/messages').name, 'acme')

    def test_the_plain_reader_ignores_a_foreign_metadata_envelope(self):
        # The dialect picks the envelope reader. A plain provider whose body
        # happens to carry OpenRouter-looking metadata is read from
        # error.message; only the openrouter dialect re-parses the nested raw
        # text. Neither path may leak the upstream prose.
        body = json.dumps({'error': {
            'message': 'bad tool', 'code': 'invalid_request',
            'metadata': {'raw': '{"error": "invalid tool schema"}'}}}).encode()
        snapshot = {'status': 409, 'body': body}
        plain = upstream.describe_failure(
            None, snapshot,
            {'model': 'acme/one', 'dialect': provider_defs.DIALECT_OPENAI_COMPATIBLE})
        self.assertEqual(plain[0], 409)
        self.assertEqual(plain[2], 'invalid_request')
        self.assertIn('the request was rejected', plain[1])
        self.assertNotIn('schema', plain[1])
        nested = upstream.describe_failure(
            None, snapshot,
            {'model': 'acme/one', 'dialect': provider_defs.DIALECT_OPENROUTER})
        self.assertIn('a tool call was rejected', nested[1])
        self.assertNotIn('invalid tool schema', nested[1])

    def test_auth_decisions_are_capabilities_not_a_provider_name(self):
        acme = provider_defs.get('acme')
        self.assertTrue(acme.sends_context_error_frame())
        self.assertTrue(acme.opens_key_window_on_auth_failure())
        self.assertTrue(acme.caches_deterministic_refusals())
        for subscription in (provider_defs.OPENAI, provider_defs.ANTHROPIC):
            with self.subTest(provider=subscription.id):
                self.assertFalse(subscription.sends_context_error_frame())
                self.assertFalse(subscription.opens_key_window_on_auth_failure())
                self.assertFalse(subscription.caches_deterministic_refusals())

    def test_a_plain_key_check_accepts_any_2xx_without_parsing(self):
        # acme declares key_info_shape='plain': a 2xx is a live key and the
        # endpoint carries no numbers, so no envelope is parsed at all.
        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        asked = []

        def fake_urlopen(req, timeout):
            asked.append(req.full_url)
            return _Response()

        self.assertEqual(
            key_store.check_key('acme', 'sk-live', _urlopen=fake_urlopen),
            ('Acme', None, None))
        self.assertEqual(asked, ['https://acme.example/v1/key'])

    def test_a_401_opens_the_foreign_providers_key_window(self):
        # The relay decides from the definition, not from a name compare: a
        # rejected acme key opens acme's own window and names acme.
        self._key_file(ACME_FILE, 'sk-dead\n')
        state = {'port': 0, 'token': 'test-token', 'openai_models': []}
        server = start_server(state, credentials=self._credentials())
        self.addCleanup(server.shutdown)
        opened = []
        stub = mock.patch.object(
            setup, 'open_key_window',
            side_effect=lambda srv, home, provider_id=None:
            opened.append(provider_id) or True)
        self.addCleanup(stub.stop)
        stub.start()
        install_fake(self, lambda: FakeUpstream(
            401, b'{"error": {"message": "bad key", "code": "invalid_api_key"}}', []))
        def dead_key(provider_id, key, _urlopen=None):
            raise key_store.KeyRejected('Acme rejected the key', status=401)
        with mock.patch.object(key_store, 'check_key', side_effect=dead_key):
            status, body = self._post(server.server_port, 'acme/one')
        self.assertEqual(status, 400)
        self.assertIn('Acme', body)
        self.assertEqual(opened, ['acme'])

    def test_manual_shape_provider_refuses_live_derivation(self):
        with self.assertRaises(SystemExit) as ctx:
            models.require_live_shape('acme')
        self.assertIn('authored by hand', str(ctx.exception))
        self.assertIn('manual', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
