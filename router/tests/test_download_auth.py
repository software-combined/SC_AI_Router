"""Staff downloads fail closed without altering the running installation."""
import importlib.util
import base64
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock
from tests._platform import assert_owner_only, unix_only


ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


auth = load('download_auth_under_test', 'packaging/download_auth.py')
CONFIG = {'version': 1, 'distribution_origin': auth.DISTRIBUTION_ORIGIN,
          'tenant_id': '11111111-1111-4111-8111-111111111111',
          'client_id': '22222222-2222-4222-8222-222222222222',
          'scope': 'api://33333333-3333-4333-8333-333333333333/Download.Read',
          'exchange_url': 'https://abc123.execute-api.ap-southeast-2.amazonaws.com/download-access'}


def receipt(expiry=None, resource=None):
    expiry = expiry or int(time.time()) + 300
    policy = {'Statement': [{'Resource': resource or auth.DISTRIBUTION_ORIGIN + '/*',
               'Condition': {'DateLessThan': {'AWS:EpochTime': expiry}}}]}
    encoded = base64.b64encode(json.dumps(policy).encode()).decode().translate(str.maketrans('+=/', '-_~'))
    return {'expires_at': expiry, 'cookies': {'CloudFront-Policy': encoded,
            'CloudFront-Signature': 'synthetic-signature', 'CloudFront-Key-Pair-Id': 'synthetic-key',
            'CloudFront-Hash-Algorithm': 'SHA256'}}


def token_response(**changes):
    return {'access_token': 'synthetic-access', 'refresh_token': 'synthetic-rotated-refresh',
            'expires_in': 3600, 'token_type': 'Bearer', **changes}


class StaffDownloadTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)
        (self.home / auth.CONFIG_FILE).write_text(json.dumps(CONFIG))

    def save_session(self, **changes):
        auth._session.write(self.home, {'config_id': auth._config_id(CONFIG),
                            'refresh_token': 'synthetic-old-refresh', **changes})

    def test_missing_deployment_configuration_never_grants_anonymous_access(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(auth.SignInRequired) as caught:
                auth.ensure_access(Path(directory))
            self.assertEqual(caught.exception.code, 'configuration_required')
            self.assertFalse(auth.status(Path(directory))['access_ready'])

    def test_exact_tenant_and_gateway_configuration_are_required(self):
        for key, value in (('tenant_id', 'common'), ('tenant_id', 'organizations'),
                ('client_id', ''), ('version', True), ('scope', 'https://graph.microsoft.com/User.Read'),
                ('distribution_origin', 'https://dist.softwarecombined.com.attacker.invalid'),
                ('exchange_url', 'http://abc123.execute-api.ap-southeast-2.amazonaws.com/download-access'),
                ('exchange_url', 'https://attacker.invalid/download-access')):
            with self.subTest(key=key, value=value):
                (self.home / auth.CONFIG_FILE).write_text(json.dumps({**CONFIG, key: value}))
                with self.assertRaises(auth.SignInRequired) as caught:
                    auth.ensure_access(self.home)
                self.assertEqual(caught.exception.code, 'configuration_invalid')

    def test_background_refresh_and_exchange_protect_and_rotate_session(self):
        self.save_session(receipt=receipt(int(time.time()) - 1))
        with mock.patch.object(auth._oauth, 'post', side_effect=[token_response(), receipt()]) as post, \
                mock.patch.object(auth._oauth, 'authorize') as browser:
            header = auth.ensure_access(self.home)
        self.assertIn('CloudFront-Hash-Algorithm=SHA256', header)
        self.assertEqual(post.call_args_list[0].args[0],
                         'https://login.microsoftonline.com/' + CONFIG['tenant_id'] + '/oauth2/v2.0/token')
        self.assertNotIn('Authorization', post.call_args_list[0].args[2])
        self.assertEqual(post.call_args_list[1].args[0], CONFIG['exchange_url'])
        self.assertEqual(post.call_args_list[1].args[2]['Authorization'], 'Bearer synthetic-access')
        browser.assert_not_called()
        saved = (self.home / auth._session.SESSION_FILE).read_text()
        self.assertNotIn('synthetic-access', saved)
        self.assertNotIn('synthetic-old-refresh', saved)
        self.assertIn('synthetic-rotated-refresh', saved)
        assert_owner_only(self, self.home / auth._session.SESSION_FILE)

    def test_cached_cookie_needs_no_network_and_status_redacts_session(self):
        self.save_session(receipt=receipt())
        with mock.patch.object(auth._oauth, 'post') as post:
            auth.ensure_access(self.home)
            status = auth.status(self.home)
        post.assert_not_called()
        self.assertTrue(status['access_ready'])
        self.assertTrue(status['signed_in'])
        self.assertNotIn('synthetic', json.dumps(status))
        self.assertNotIn('cookies', status)

    def test_changed_tenant_binding_never_reuses_existing_refresh_token(self):
        self.save_session(receipt=receipt())
        changed = {**CONFIG, 'tenant_id': '44444444-4444-4444-8444-444444444444'}
        (self.home / auth.CONFIG_FILE).write_text(json.dumps(changed))
        with mock.patch.object(auth._oauth, 'post') as post, self.assertRaises(auth.SignInRequired):
            auth.ensure_access(self.home)
        post.assert_not_called()

    def test_revoked_refresh_never_opens_browser_in_background(self):
        self.save_session()
        with mock.patch.object(auth._oauth, 'post', side_effect=auth.SignInRequired()), \
                mock.patch.object(auth._oauth, 'authorize') as browser, self.assertRaises(auth.SignInRequired):
            auth.ensure_access(self.home)
        browser.assert_not_called()

    def test_exchange_denial_preserves_new_refresh_without_old_access(self):
        self.save_session(receipt=receipt(int(time.time()) - 1))
        with mock.patch.object(auth._oauth, 'post', side_effect=[token_response(),
                auth.SignInRequired('access_denied')]), self.assertRaises(auth.SignInRequired):
            auth.ensure_access(self.home)
        saved = auth._session.read(self.home)
        self.assertEqual(saved['refresh_token'], 'synthetic-rotated-refresh')
        self.assertNotIn('receipt', saved)

    def test_cookie_scope_expiry_and_header_injection_are_rejected(self):
        bad = [receipt(resource='https://*'), receipt(resource='https://attacker.invalid/*'),
               receipt(int(time.time()) - 1), receipt(int(time.time()) + 1000)]
        injected = receipt()
        injected['cookies']['CloudFront-Signature'] = 'x; injected=1'
        bad.append(injected)
        missing = receipt()
        del missing['cookies']['CloudFront-Hash-Algorithm']
        bad.append(missing)
        for value in bad:
            with self.subTest(value=value), self.assertRaises(auth.SignInRequired):
                auth._cookie_header(value)

    def test_expired_access_token_never_reaches_exchange(self):
        with mock.patch.object(auth._oauth, 'authorize', return_value={
                'access_token': 'expired-secret', 'expires_at': time.time() - 1}), \
                mock.patch.object(auth._oauth, 'post') as post, self.assertRaises(auth.SignInRequired):
            auth.signin(self.home)
        post.assert_not_called()

    @unix_only
    def test_widened_or_linked_session_is_refused_without_disclosing_data(self):
        self.save_session()
        path = self.home / auth._session.SESSION_FILE
        path.chmod(0o644)
        with self.assertRaises(auth.SignInRequired) as caught:
            auth.ensure_access(self.home)
        self.assertEqual(caught.exception.code, 'session_invalid')
        self.assertNotIn('synthetic', str(caught.exception))
        path.chmod(0o600)
        other = self.home / 'other.json'
        path.rename(other)
        path.symlink_to(other)
        with self.assertRaises(auth.SignInRequired):
            auth.ensure_access(self.home)


if __name__ == '__main__':
    unittest.main()
