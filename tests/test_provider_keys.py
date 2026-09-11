"""Plan 141: the installer-surface key walk agrees with the router.

`packaging/provider_keys.py` is the one owner of "does this provider have a
key" for the installer and diagnostics, and it must agree with the router's
own `Credentials.key_for`. A status surface that reports usable while the
router refuses to boot is the failure this pins. No network, no real install.
"""
import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from ai_router import provider_defs
from ai_router.credentials import Credentials
from tests._platform import requires_posix_perms

ROOT = Path(__file__).resolve().parents[1]


def _load():
    """Spec-load the module the way packaging/install.py and diagnostics do."""
    spec = importlib.util.spec_from_file_location(
        'provider_keys_under_test', ROOT / 'packaging' / 'provider_keys.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.bind(provider_defs)
    return module


class KeyStateParityTests(unittest.TestCase):
    def setUp(self):
        self.keys = _load()
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(self.home), True)
        self.defn = provider_defs.OPENROUTER
        self.state = {'port': 0, 'token': 't', 'openai_models': []}

    def _router_resolves(self, env, state=None):
        """True when the router's own lookup resolves this provider."""
        return Credentials(state or self.state, self.home, env).key_missing(
            self.defn.id) is None

    def _key_file(self, text, mode=0o600):
        path = self.home / self.defn.key.file
        path.write_text(text)
        os.chmod(path, mode)
        return path

    def _with_auth(self, entry):
        path = self.home / 'opencode-auth.json'
        path.write_text(json.dumps({'openrouter': entry}))
        return {**self.state, 'opencode_auth': str(path)}

    def _private(self, path):
        return not (path.stat().st_mode & 0o077)

    def test_env_key_is_usable_and_the_router_agrees(self):
        env = {self.defn.key.env: 'sk-env'}
        self.assertTrue(self.keys.key_state(self.home, self.state, env, self.defn)[1])
        self.assertTrue(self._router_resolves(env))

    def test_absent_key_is_not_usable_and_the_router_agrees(self):
        self.assertEqual(
            self.keys.key_state(self.home, self.state, {}, self.defn), (False, False))
        self.assertFalse(self._router_resolves({}))

    @requires_posix_perms
    def test_owner_only_file_is_usable_and_a_widened_one_is_not(self):
        self._key_file('sk-file\n')
        self.assertEqual(
            self.keys.key_state(self.home, self.state, {}, self.defn, self._private),
            (True, True))
        self.assertTrue(self._router_resolves({}))
        self._key_file('sk-wide\n', 0o644)
        self.assertFalse(
            self.keys.key_state(self.home, self.state, {}, self.defn, self._private)[1])
        self.assertFalse(self._router_resolves({}))

    def test_the_empty_placeholder_file_is_not_usable_and_the_router_agrees(self):
        # The installer's own empty placeholder must not read as ready: the
        # router treats an existing-but-empty key file as terminal.
        self._key_file('\n')
        self.assertEqual(
            self.keys.key_state(self.home, self.state, {}, self.defn), (False, False))
        self.assertFalse(self._router_resolves({}))

    def test_third_party_credential_is_counted_and_the_router_agrees(self):
        state = self._with_auth({'type': 'api', 'key': 'sk-oc'})
        self.assertEqual(
            self.keys.key_state(self.home, state, {}, self.defn), (True, True))
        self.assertTrue(self._router_resolves({}, state))

    def test_non_api_third_party_credential_is_refused_and_the_router_agrees(self):
        state = self._with_auth({'type': 'oauth', 'key': 'sk-oc'})
        self.assertEqual(
            self.keys.key_state(self.home, state, {}, self.defn), (False, False))
        self.assertFalse(self._router_resolves({}, state))

    def test_ensure_creates_one_owner_only_placeholder_then_stops(self):
        protected = []
        with self.assertRaises(SystemExit) as ctx:
            self.keys.ensure(self.home, self.state, {}, protected.append)
        self.assertEqual(ctx.exception.code, 3)
        key_file = self.home / self.defn.key.file
        self.assertEqual(protected, [key_file])
        self.assertEqual(key_file.read_text(), '')

    def test_ensure_leaves_an_existing_blank_placeholder_to_the_setup_window(self):
        # The installer's own first run creates the blank placeholder and
        # hands over to the setup window; the scheduled updater calls
        # ensure() through the same path, so a blank file must not stop it.
        self._key_file('\n')
        protected = []
        self.keys.ensure(self.home, self.state, {}, protected.append)
        self.assertEqual(protected, [])

    def test_a_failed_protection_removes_the_placeholder(self):
        def refuse(_path):
            raise SystemExit('cannot protect')

        with self.assertRaisesRegex(SystemExit, 'cannot protect'):
            self.keys.ensure(self.home, self.state, {}, refuse)
        self.assertFalse((self.home / self.defn.key.file).exists())


if __name__ == '__main__':
    unittest.main()
