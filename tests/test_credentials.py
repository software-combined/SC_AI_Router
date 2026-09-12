import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from ai_router.credentials import Credentials, ENV_VAR

needs_posix = unittest.skipIf(os.name == 'nt', 'POSIX permission bits only')


class CredentialLookupTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(self.home), True)
        self.state = {'port': 0, 'token': 't', 'openai_models': []}

    def _key_file(self, text, mode=0o600):
        path = self.home / 'openrouter.key'
        path.write_text(text)
        os.chmod(path, mode)
        return path

    def _auth(self, payload):
        """The client's own auth file under a temp HOME: (path, env)."""
        env_home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(env_home), True)
        auth = env_home / '.local' / 'share' / 'opencode' / 'auth.json'
        auth.parent.mkdir(parents=True)
        auth.write_text(payload if isinstance(payload, str) else json.dumps(payload))
        return str(auth), {'HOME': str(env_home)}

    def creds(self, env=None):
        return Credentials(self.state, self.home, env if env is not None else {})

    def test_env_var_wins(self):
        self._key_file('k-file\n')
        self.assertEqual(self.creds({ENV_VAR: 'k-env'}).key_for(), 'k-env')

    def test_key_file_600_is_read(self):
        self._key_file('k-file\n')
        self.assertEqual(self.creds().key_for(), 'k-file')

    @needs_posix
    def test_key_file_group_readable_is_refused(self):
        self._key_file('k-file\n', 0o640)
        with self.assertRaises(PermissionError):
            self.creds().key_for()

    def test_windows_widened_acl_is_refused(self):
        # The read path keeps the POSIX PermissionError contract so the
        # request handler maps it to 401 CREDENTIAL_PERMISSION.
        import ai_router.credentials as cred_mod
        import ai_router.winacl as winacl_mod
        self._key_file('k-file\n')
        with mock.patch.object(cred_mod, '_ON_WINDOWS', True), \
                mock.patch.object(winacl_mod, 'check',
                                   side_effect=SystemExit('readable by X')):
            with self.assertRaisesRegex(PermissionError, 'readable by X'):
                self.creds().key_for()

    def test_empty_key_file_is_lookup_error(self):
        self._key_file('\n')
        with self.assertRaises(LookupError):
            self.creds().key_for()

    def test_opencode_fallback(self):
        auth, env = self._auth({'openrouter': {'type': 'api', 'key': 'k-oc'}})
        self.assertEqual(Credentials({**self.state, 'opencode_auth': auth},
                                     self.home, env).key_for(), 'k-oc')

    def test_opencode_non_api_type_is_value_error(self):
        auth, env = self._auth({'openrouter': {'type': 'oauth', 'key': 'k'}})
        with self.assertRaises(ValueError):
            Credentials({**self.state, 'opencode_auth': auth},
                        self.home, env).key_for()

    def test_opencode_auth_outside_the_client_path_is_refused(self):
        other = self.home / 'auth.json'
        other.write_text(json.dumps({'openrouter': {'type': 'api', 'key': 'k'}}))
        creds = Credentials({**self.state, 'opencode_auth': str(other)},
                            self.home, {'HOME': str(self.home)})
        with self.assertRaisesRegex(LookupError, 'opencode_auth must name'):
            creds.key_for()

    def test_an_xdg_data_home_path_is_not_the_client_path(self):
        # The installed service has no XDG_DATA_HOME, so both readers resolve
        # from HOME; an XDG path is refused rather than followed.
        xdg = self.home / 'data' / 'opencode' / 'auth.json'
        xdg.parent.mkdir(parents=True)
        xdg.write_text(json.dumps({'openrouter': {'type': 'api', 'key': 'k'}}))
        creds = Credentials({**self.state, 'opencode_auth': str(xdg)},
                            self.home, {'HOME': str(self.home),
                                        'XDG_DATA_HOME': str(self.home / 'data')})
        with self.assertRaisesRegex(LookupError, 'opencode_auth must name'):
            creds.key_for()

    def test_nothing_configured_is_lookup_error_naming_all_sources(self):
        with self.assertRaises(LookupError) as ctx:
            self.creds().key_for()
        for named in (ENV_VAR, 'openrouter.key', 'opencode_auth'):
            self.assertIn(named, str(ctx.exception))

    def test_repr_never_contains_key(self):
        self._key_file('k-file\n')
        self.assertNotIn('k-file', repr(self.creds()))

    def test_check_probes_without_returning_value(self):
        self._key_file('k-file\n')
        self.assertTrue(self.creds().check())

    def test_default_home_follows_env_at_call_time(self):
        import ai_router.credentials as cred_mod
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {'ROUTER_HOME': tmp}):
                self.assertEqual(cred_mod.default_home(), Path(tmp))
            self.assertNotEqual(cred_mod.default_home(), Path(tmp))


if __name__ == '__main__':
    unittest.main()
