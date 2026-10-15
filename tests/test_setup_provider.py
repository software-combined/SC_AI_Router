"""Plan 141: the first-run window is scoped to one provider.

The provider id rides in the pending-window state; the form, the validation
and the stored file all follow it. Split from test_setup.py to keep both
files inside the test size cap. No network: urlopen is faked.
"""
import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from ai_router import key_store, provider_defs, setup, setup_page
from tests._platform import assert_owner_only

NOW = 1_700_000_000


def _state(home, **over):
    state = {'port': 1, 'token': 'test-token', 'openai_models': []}
    state.update(over)
    return state


def _key_ok(key='sk-test'):
    payload = json.dumps({'data': {'label': 'probe', 'limit': 10,
                                   'usage': 3}}).encode()

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


def _register_acme(test):
    """A second external provider, registered as a real one would be."""
    acme = provider_defs.ProviderDef(
        id='acme', label='Acme', kind=provider_defs.EXTERNAL,
        host='acme.example', responses_path='/v1',
        key=provider_defs.KeySpec('ACME_API_KEY', 'acme.key',
                                  example='sk-acme-...'),
        catalogue_shape='manual',
        dialect=provider_defs.DIALECT_OPENAI_COMPATIBLE)
    test.addCleanup(setattr, provider_defs, 'PROVIDERS', provider_defs.PROVIDERS)
    test.addCleanup(setattr, provider_defs, 'BY_ID', dict(provider_defs.BY_ID))
    provider_defs.PROVIDERS = provider_defs.PROVIDERS + (acme,)
    provider_defs.BY_ID = {p.id: p for p in provider_defs.PROVIDERS}
    return acme


class ProviderWindowTests(unittest.TestCase):
    def _home(self, state=None):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        (home / 'mixed-router-state.json').write_text(
            json.dumps(state or _state(home)))
        return home

    def _server(self, state):
        return SimpleNamespace(state=state, lock=threading.Lock())

    def test_window_provider_falls_back_for_unknown_or_subscription_ids(self):
        # Plan 141: the pending window names one provider; anything that is
        # not an external definition resolves to the default, so a crafted
        # or stale state value can never pick another provider's key file.
        for bad in ('openai', 'anthropic', 'nope', '../evil.key', 42, '', None):
            state = _state(None, setup={'nonce': 'n' * 16, 'expires': NOW + 900,
                                        'provider': bad})
            with self.subTest(provider=bad):
                self.assertEqual(key_store.window_provider(state), 'openrouter')
        self.assertEqual(key_store.window_provider({}), 'openrouter')
        self.assertEqual(key_store.window_provider(
            _state(None, setup={'nonce': 'n' * 16, 'expires': NOW + 900,
                                'provider': 'openrouter'})), 'openrouter')

    def test_window_records_the_provider_and_the_form_names_it(self):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        state = _state(home)
        (home / 'mixed-router-state.json').write_text(json.dumps(state))
        opened = []
        server = SimpleNamespace(state=state, lock=threading.Lock())
        self.assertTrue(setup.open_key_window(server, home, 'openrouter',
                                              _opener=opened.append,
                                              _prompt=lambda url, **kw: True))
        self.assertEqual(state['setup']['provider'], 'openrouter')
        self.assertEqual(
            json.loads((home / 'mixed-router-state.json').read_text())['setup']['provider'],
            'openrouter')
        self.assertIn(b'OpenRouter', setup_page.form('n' * 16, 'openrouter'))

    def test_a_second_provider_gets_its_own_window_and_key_file(self):
        # Plan 141: the window, the form and the stored file all follow the
        # provider the request named, never the default provider.
        from ai_router import provider_defs
        acme = provider_defs.ProviderDef(
            id='acme', label='Acme', kind=provider_defs.EXTERNAL,
            host='acme.example', responses_path='/v1',
            key=provider_defs.KeySpec('ACME_API_KEY', 'acme.key',
                                      example='sk-acme-...'),
            catalogue_shape='manual',
            dialect=provider_defs.DIALECT_OPENAI_COMPATIBLE)
        self.addCleanup(setattr, provider_defs, 'PROVIDERS', provider_defs.PROVIDERS)
        self.addCleanup(setattr, provider_defs, 'BY_ID', dict(provider_defs.BY_ID))
        provider_defs.PROVIDERS = provider_defs.PROVIDERS + (acme,)
        provider_defs.BY_ID = {p.id: p for p in provider_defs.PROVIDERS}

        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        state = _state(home)
        (home / 'mixed-router-state.json').write_text(json.dumps(state))
        server = SimpleNamespace(state=state, lock=threading.Lock())
        self.assertTrue(setup.open_key_window(server, home, 'acme',
                                              _opener=lambda url: True,
                                              _prompt=lambda url, **kw: True))
        self.assertEqual(key_store.window_provider(state), 'acme')
        self.assertIn(b'Acme', setup_page.form('n' * 16, 'acme'))

        nonce = state['setup']['nonce']
        status, payload = setup.handle_setup_json(
            state, home, nonce, b'key=sk-acme&mode=none',
            _urlopen=_key_ok(), _now=NOW)
        self.assertEqual(status, 200)
        self.assertTrue(payload['ok'])
        self.assertEqual((home / 'acme.key').read_text(), 'sk-acme\n')
        self.assertFalse((home / 'openrouter.key').exists())

    def test_a_pending_window_stays_bound_to_its_provider(self):
        # One nonce, one provider: a second provider's request defers
        # (returns False) instead of retargeting the open window, so a
        # key can never be saved under the wrong provider.
        from ai_router import provider_defs
        acme = provider_defs.ProviderDef(
            id='acme', label='Acme', kind=provider_defs.EXTERNAL,
            host='acme.example', responses_path='/v1',
            key=provider_defs.KeySpec('ACME_API_KEY', 'acme.key'),
            catalogue_shape='manual',
            dialect=provider_defs.DIALECT_OPENAI_COMPATIBLE)
        self.addCleanup(setattr, provider_defs, 'PROVIDERS', provider_defs.PROVIDERS)
        self.addCleanup(setattr, provider_defs, 'BY_ID', dict(provider_defs.BY_ID))
        provider_defs.PROVIDERS = provider_defs.PROVIDERS + (acme,)
        provider_defs.BY_ID = {p.id: p for p in provider_defs.PROVIDERS}

        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        state = _state(home)
        (home / 'mixed-router-state.json').write_text(json.dumps(state))
        server = SimpleNamespace(state=state, lock=threading.Lock())
        self.assertTrue(setup.open_key_window(server, home, 'openrouter',
                                              _opener=lambda url: True,
                                              _prompt=lambda url, **kw: True))
        self.assertEqual(key_store.window_provider(state), 'openrouter')
        # Same provider reuses the window; another provider defers.
        self.assertTrue(setup.open_key_window(server, home, 'openrouter',
                                              _opener=lambda url: True,
                                              _prompt=lambda url, **kw: True))
        self.assertFalse(setup.open_key_window(server, home, 'acme',
                                               _opener=lambda url: True,
                                               _prompt=lambda url, **kw: True))
        self.assertEqual(key_store.window_provider(state), 'openrouter')
        stored = json.loads((home / 'mixed-router-state.json').read_text())
        self.assertEqual(stored['setup']['provider'], 'openrouter')

    def test_a_deferred_window_leaves_the_running_provider_unchanged(self):
        # The state file and the live state must agree: a deferred second
        # provider leaves the window collecting for its own provider.
        from ai_router import provider_defs
        acme = provider_defs.ProviderDef(
            id='acme', label='Acme', kind=provider_defs.EXTERNAL,
            host='acme.example', responses_path='/v1',
            key=provider_defs.KeySpec('ACME_API_KEY', 'acme.key'),
            catalogue_shape='manual',
            dialect=provider_defs.DIALECT_OPENAI_COMPATIBLE)
        self.addCleanup(setattr, provider_defs, 'PROVIDERS', provider_defs.PROVIDERS)
        self.addCleanup(setattr, provider_defs, 'BY_ID', dict(provider_defs.BY_ID))
        provider_defs.PROVIDERS = provider_defs.PROVIDERS + (acme,)
        provider_defs.BY_ID = {p.id: p for p in provider_defs.PROVIDERS}

        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        state = _state(home)
        server = SimpleNamespace(state=state, lock=threading.Lock())
        state['setup'] = {'nonce': 'n' * 16, 'expires': NOW + 900,
                          'provider': 'openrouter'}
        # No state file on disk: the rewrite cannot succeed.
        self.assertFalse(setup.open_key_window(server, home, 'acme',
                                               _opener=lambda url: True,
                                               _prompt=lambda url, **kw: True))
        self.assertEqual(key_store.window_provider(state), 'openrouter')


class StoreKeyTests(unittest.TestCase):
    """The key-claim decision matrix (Plan 131 move to the shared writer)."""

    def _key_path(self, home):
        spec = provider_defs.get(provider_defs.DEFAULT_EXTERNAL)
        return Path(home) / spec.key.file

    def test_store_key_refuses_a_live_stored_key_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            key_store.store_key(tmp, 'sk-old')
            path = self._key_path(tmp)
            with self.assertRaises(key_store.KeyExists):
                key_store.store_key(tmp, 'sk-new')
            self.assertEqual(path.read_text(), 'sk-old\n')

    def test_store_key_replaces_a_key_proven_dead(self):
        with tempfile.TemporaryDirectory() as tmp:
            key_store.store_key(tmp, 'sk-old')
            path = self._key_path(tmp)
            key_store.store_key(tmp, 'sk-new', _check_live=lambda stored: False)
            self.assertEqual(path.read_text(), 'sk-new\n')
            assert_owner_only(self, path)
