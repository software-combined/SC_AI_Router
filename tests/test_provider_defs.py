"""Plan 141: the provider definition table is the one owner of upstream facts.

Every built-in provider is a well-formed definition, registry rows validate
against it, and the boundary scan keeps host/key/catalogue literals out of
the rest of the runtime.
"""
import ast
import json
import unittest
from pathlib import Path

from ai_router import provider_defs, registry

ROOT = Path(__file__).resolve().parents[1]

# Literals that identify an upstream; each must live in provider_defs.py only.
PROVIDER_LITERALS = ('openrouter.ai', 'chatgpt.com', 'api.anthropic.com',
                     'OPENROUTER_API_KEY', 'openrouter.key')


class DefinitionTests(unittest.TestCase):
    def test_ids_are_unique_and_resolvable(self):
        ids = [p.id for p in provider_defs.PROVIDERS]
        self.assertEqual(len(ids), len(set(ids)))
        for provider_id in ids:
            self.assertIs(provider_defs.get(provider_id),
                          provider_defs.BY_ID[provider_id])
            self.assertEqual(provider_defs.label_for(provider_id),
                             provider_defs.get(provider_id).label)
        self.assertIsNone(provider_defs.get('nope'))
        self.assertEqual(provider_defs.label_for('nope'), 'nope')

    def test_external_defs_carry_a_key_and_a_catalogue_contract(self):
        for defn in provider_defs.external_defs():
            with self.subTest(provider=defn.id):
                self.assertEqual(defn.kind, provider_defs.EXTERNAL)
                self.assertIsNotNone(defn.key)
                self.assertTrue(defn.key.env and defn.key.file)
                self.assertTrue(defn.serves(provider_defs.RESPONSES)
                                or defn.serves(provider_defs.MESSAGES))

    def test_subscription_defs_hold_no_router_key(self):
        for defn in provider_defs.PROVIDERS:
            if defn.kind == provider_defs.SUBSCRIPTION:
                with self.subTest(provider=defn.id):
                    self.assertIsNone(defn.key)
                    self.assertIsNone(defn.key_info_url)

    def test_path_prefixes_compose(self):
        self.assertEqual(
            provider_defs.OPENROUTER.path_for(provider_defs.MESSAGES, '/v1/messages'),
            '/api/v1/messages')
        self.assertEqual(
            provider_defs.OPENROUTER.path_for(provider_defs.RESPONSES, '/responses'),
            '/api/v1/responses')
        # Anthropic's prefix is empty: the client path travels as-is.
        self.assertEqual(
            provider_defs.ANTHROPIC.path_for(provider_defs.MESSAGES, '/v1/messages'),
            '/v1/messages')
        with self.assertRaises(ValueError):
            provider_defs.ANTHROPIC.path_for(provider_defs.RESPONSES, '/responses')

    def test_malformed_defs_are_rejected(self):
        with self.assertRaises(ValueError):  # serves no protocol
            provider_defs.ProviderDef(id='x', label='X', kind='external',
                                      host='example.invalid')
        with self.assertRaises(ValueError):  # external without a key spec
            provider_defs.ProviderDef(id='x', label='X', kind='external',
                                      host='example.invalid', responses_path='/r')
        with self.assertRaises(ValueError):  # unknown kind
            provider_defs.ProviderDef(id='x', label='X', kind='wat',
                                      host='example.invalid', responses_path='/r')
        with self.assertRaises(ValueError):  # subscription with a key spec
            provider_defs.ProviderDef(
                id='x', label='X', kind='subscription', host='example.invalid',
                responses_path='/r', key=provider_defs.KeySpec('E', 'f'))


class RegistryCompatibilityTests(unittest.TestCase):
    def _row(self, **over):
        row = {'slug': 'vendor/model', 'provider': 'openrouter', 'display_name': 'V: M',
               'vendor': 'V', 'reasoning': ['low'], 'default_reasoning': 'low',
               'modalities': ['text'], 'excluded_efforts': [], 'schema_mode': 'native',
               'max_tools': None, 'drop_images': False, 'context_window': 1000,
               'priority': 100, 'max_output_tokens': 100, 'reasoning_summary': 'none',
               'apply_patch': 'none', 'experimental_tools': [], 'web_search': True,
               'tier': 'verified'}
        row.update(over)
        return [row]

    def test_every_built_in_id_loads(self):
        for provider_id in provider_defs.BY_ID:
            with self.subTest(provider=provider_id):
                rows = registry.load(json.dumps(self._row(provider=provider_id)))
                self.assertEqual(rows[0].provider, provider_id)

    def test_unknown_provider_is_rejected(self):
        with self.assertRaises(SystemExit):
            registry.load(json.dumps(self._row(provider='not-a-provider')))

    def test_the_live_registry_uses_known_providers(self):
        for model in registry.MODELS:
            with self.subTest(slug=model.slug):
                self.assertIsNotNone(provider_defs.get(model.provider))


class ProviderLiteralBoundaryTests(unittest.TestCase):
    """No upstream host, key name or key file outside the definition table."""

    def _offenders(self, root):
        found = []
        for path in sorted((root / 'ai_router').rglob('*.py')):
            if path.name == 'provider_defs.py' or '__pycache__' in path.parts:
                continue
            text = path.read_text()
            for literal in PROVIDER_LITERALS:
                if literal in text:
                    found.append(f'{path.name} names {literal}')
        return found

    def test_no_provider_literals_outside_the_table(self):
        self.assertEqual(self._offenders(ROOT), [])

    def test_detector_rejects_a_synthetic_violation(self):
        # The scan must fail when a literal is present, not pass vacuously.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'ai_router').mkdir()
            (root / 'ai_router' / 'bad.py').write_text("HOST = 'openrouter.ai'\n")
            self.assertEqual(self._offenders(root), ['bad.py names openrouter.ai'])
            (root / 'ai_router' / 'bad.py').write_text('import os\n')
            self.assertEqual(self._offenders(root), [])


class LeafPurityTests(unittest.TestCase):
    def test_defs_module_imports_nothing(self):
        tree = ast.parse((ROOT / 'ai_router' / 'provider_defs.py').read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                self.fail('provider_defs.py must not import anything')


if __name__ == '__main__':
    unittest.main()
