"""Cookie exchange trusts verified gateway claims and explicit staff entitlement."""
import base64
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from http.cookies import SimpleCookie
from unittest import mock
from tests.test_download_auth import CONFIG, load

exchange = load('download_exchange_under_test', 'infra/downloads/handler.py')
NOW = 1800000000
SETTINGS = {'TENANT_ID': CONFIG['tenant_id'], 'NATIVE_CLIENT_ID': CONFIG['client_id'],
            'API_CLIENT_ID': '33333333-3333-4333-8333-333333333333',
            'SIGNING_KEY_ARN': 'synthetic-kms-key-arn',
            'PUBLIC_KEY_ID': 'KPUBLICEXAMPLE'}


def event(**changes):
    claims = {'tid': SETTINGS['TENANT_ID'], 'aud': SETTINGS['API_CLIENT_ID'],
              'iss': 'https://login.microsoftonline.com/' + SETTINGS['TENANT_ID'] + '/v2.0',
              'azp': SETTINGS['NATIVE_CLIENT_ID'], 'ver': '2.0', 'scp': 'Download.Read',
              'roles': ['Download'], 'oid': '66666666-6666-4666-8666-666666666666',
              'exp': str(NOW + 3600), 'nbf': str(NOW - 10), 'iat': str(NOW - 10),
              **changes}
    return {'routeKey': 'POST /download-access', 'requestContext': {
        'http': {'method': 'POST'}, 'authorizer': {'jwt': {'claims': claims,
                                                       'scopes': ['Download.Read']}}}}


def decode(value):
    return base64.b64decode(value.translate(str.maketrans('-_~', '+=/')))


class ExchangeTests(unittest.TestCase):
    def setUp(self):
        self.environ = mock.patch.dict(exchange.os.environ, SETTINGS, clear=True)
        self.environ.start()
        self.addCleanup(self.environ.stop)
        self.clock = mock.patch.object(exchange.time, 'time', return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.kms = mock.Mock()
        self.kms.sign.return_value = {'Signature': b'\x30synthetic-der-signature'}
        self.client = mock.patch.object(exchange, '_client', return_value=self.kms)
        self.client.start()
        self.addCleanup(self.client.stop)

    def test_member_and_explicitly_assigned_resource_tenant_guest_receive_scoped_cookies(self):
        for claims in ({}, {'acct': '1', 'idp': 'https://sts.windows.net/guest-home-tenant/',
                           'email': 'approved@portfolio.example'}):
            with self.subTest(claims=claims):
                response = exchange.handler(event(**claims), None)
                self.assertEqual(response['statusCode'], 200)
                payload = json.loads(response['body'])
                self.assertEqual(payload['expires_at'], NOW + 600)
                policy = json.loads(decode(payload['cookies']['CloudFront-Policy']))
                self.assertEqual(policy, {'Statement': [{'Resource': 'https://dist.softwarecombined.com/*',
                                  'Condition': {'DateLessThan': {'AWS:EpochTime': NOW + 600}}}]})
                self.assertEqual(payload['cookies']['CloudFront-Hash-Algorithm'], 'SHA256')
                self.assertEqual(self.kms.sign.call_args.kwargs['SigningAlgorithm'], 'ECDSA_SHA_256')
                self.assertEqual(self.kms.sign.call_args.kwargs['MessageType'], 'RAW')
                self.assertEqual(json.loads(self.kms.sign.call_args.kwargs['Message']), policy)
                self.assertEqual(response['headers']['Cache-Control'], 'no-store')

    def test_no_anonymous_or_user_supplied_claims_bypass(self):
        for value in ({}, {'body': json.dumps(event())}, {'headers': {'Authorization': 'synthetic-jwt'}},
                      {'requestContext': {'http': {'method': 'POST'}}, 'claims': event()}):
            with self.subTest(value=value):
                self.assertEqual(exchange.handler(value, None)['statusCode'], 403)
        self.kms.sign.assert_not_called()

    def test_each_tenant_client_scope_role_and_lifetime_boundary_is_required(self):
        invalid = [('tid', 'other-tenant'), ('iss', 'https://login.microsoftonline.com/common/v2.0'),
                   ('aud', SETTINGS['NATIVE_CLIENT_ID']), ('azp', 'unapproved-client'),
                   ('scp', ''), ('scp', 'OtherDownload.Read'), ('roles', []),
                   ('roles', ['NotDownload']), ('roles', 'NotDownload'),
                   ('oid', ''), ('exp', str(NOW)), ('nbf', str(NOW + 1)),
                   ('iat', str(NOW + 1)), ('ver', '1.0')]
        for key, value in invalid:
            with self.subTest(key=key, value=value):
                response = exchange.handler(event(**{key: value}), None)
                self.assertEqual(response['statusCode'], 403)
                self.assertNotIn('cookies', json.loads(response['body']))
        self.kms.sign.assert_not_called()

    def test_email_domain_or_guest_membership_without_role_never_grants_access(self):
        for claims in ({'email': 'person@softwarecombined.com', 'roles': []},
                       {'acct': '1', 'idp': 'guest-home-tenant', 'roles': []}):
            self.assertEqual(exchange.handler(event(**claims), None)['statusCode'], 403)
        self.kms.sign.assert_not_called()

    def test_single_and_json_encoded_role_claims_match_exactly(self):
        for roles in ('Download', '["Download"]', ['Download', 'Other']):
            self.assertEqual(exchange.handler(event(roles=roles), None)['statusCode'], 200)
        self.assertEqual(exchange.handler(event(roles='["DownloadExtra"]'), None)['statusCode'], 403)

    def test_cookie_expiry_never_outlives_authorized_access_token(self):
        response = exchange.handler(event(exp=str(NOW + 120)), None)
        self.assertEqual(json.loads(response['body'])['expires_at'], NOW + 120)
        self.assertTrue(all('Max-Age=120' in header for header in response['cookies']))

    def test_browser_cookies_are_host_only_httponly_and_short_lived(self):
        response = exchange.handler(event(), None)
        values = json.loads(response['body'])['cookies']
        self.assertEqual(len(response['cookies']), 4)
        for header in response['cookies']:
            parsed = SimpleCookie(header)
            self.assertEqual(len(parsed), 1)
            name, morsel = next(iter(parsed.items()))
            self.assertEqual(morsel.value, values[name])
            self.assertTrue(morsel['secure'])
            self.assertTrue(morsel['httponly'])
            self.assertEqual(morsel['samesite'], 'Lax')
            self.assertEqual(morsel['path'], '/')
            self.assertEqual(morsel['domain'], '')
            self.assertEqual(int(morsel['max-age']), 600)

    def test_browser_cookie_lifetime_accounts_for_signing_delay(self):
        with mock.patch.object(exchange.time, 'time', side_effect=[NOW, NOW + 9]):
            response = exchange.handler(event(exp=str(NOW + 120)), None)
        self.assertTrue(all('Max-Age=111' in header for header in response['cookies']))

    def test_expiry_or_denial_never_sets_browser_cookies(self):
        with mock.patch.object(exchange.time, 'time', side_effect=[NOW, NOW + 700]):
            response = exchange.handler(event(), None)
        self.assertEqual(response['statusCode'], 403)
        self.assertNotIn('cookies', response)
        self.assertNotIn('cookies', exchange.handler(event(roles=[]), None))

    def test_signing_failure_and_denial_do_not_log_or_return_personal_claims(self):
        self.kms.sign.side_effect = RuntimeError('private-debug-payload')
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            response = exchange.handler(event(email='private-person@example.test'), None)
        self.assertEqual(response['statusCode'], 503)
        self.assertNotIn('cookies', response)
        self.assertEqual(output.getvalue(), '')
        self.assertNotIn('private', response['body'])


if __name__ == '__main__':
    unittest.main()
