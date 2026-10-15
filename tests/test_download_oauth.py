"""PKCE binds one browser callback and never redirects credential requests."""
import base64
import hashlib
import io
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest import mock
from tests.test_download_auth import CONFIG, auth, token_response

oauth = auth._oauth


class OAuthTests(unittest.TestCase):
    def test_state_mismatch_duplicate_or_missing_state_never_yields_code(self):
        for query in ('state=wrong&code=secret', 'code=secret',
                      'state=right&state=right&code=secret',
                      'state=right&code=first&code=second',
                      'state=right&error=denied&error_description=secret'):
            with self.subTest(query=query), self.assertRaises(oauth.SignInRequired) as caught:
                oauth.callback_code(query, 'right')
            self.assertNotIn('secret', str(caught.exception))
        self.assertEqual(oauth.callback_code('state=right&code=approved', 'right'), 'approved')

    def test_browser_flow_binds_random_port_verifier_and_resource_tenant(self):
        server = mock.MagicMock(server_port=54321, result=None)
        server.__enter__.return_value = server
        server.handle_request.side_effect = lambda: setattr(server, 'result', 'synthetic-code')
        with mock.patch.object(oauth.http.server, 'HTTPServer', return_value=server) as bind, \
                mock.patch.object(oauth.webbrowser, 'open', return_value=True) as browser, \
                mock.patch.object(oauth, 'post', return_value=token_response()) as post:
            result = oauth.authorize(CONFIG)
        bind.assert_called_once_with(('127.0.0.1', 0), oauth._Callback)
        authorization = urllib.parse.urlsplit(browser.call_args.args[0])
        self.assertEqual(authorization.netloc, 'login.microsoftonline.com')
        self.assertEqual(authorization.path, '/' + CONFIG['tenant_id'] + '/oauth2/v2.0/authorize')
        query = urllib.parse.parse_qs(authorization.query)
        form = urllib.parse.parse_qs(post.call_args.args[1].decode())
        expected = base64.urlsafe_b64encode(hashlib.sha256(form['code_verifier'][0].encode()).digest()).rstrip(b'=').decode()
        self.assertEqual(query['code_challenge'], [expected])
        self.assertEqual(query['code_challenge_method'], ['S256'])
        self.assertEqual(query['state'], [server.state])
        self.assertEqual(query['redirect_uri'], ['http://localhost:54321/scg-router/signin'])
        self.assertEqual(query['redirect_uri'], form['redirect_uri'])
        self.assertIn('offline_access', form['scope'][0])
        self.assertEqual(result['access_token'], 'synthetic-access')
        self.assertNotIn('client_secret', form)

    def test_wrong_host_and_absolute_target_do_not_capture_callback(self):
        for target, host in (('/scg-router/signin?state=right&code=secret', 'attacker.invalid'),
                             ('http://attacker.invalid/scg-router/signin?state=right&code=secret', 'localhost:54321'),
                             ('http://[invalid', 'localhost:54321')):
            handler = object.__new__(oauth._Callback)
            handler.path, handler.headers = target, {'Host': host}
            handler.server = mock.Mock(expected_host='localhost:54321', result=None, state='right')
            handler._reply = mock.Mock()
            handler.do_GET()
            self.assertIsNone(handler.server.result)
            self.assertEqual(handler._reply.call_args.args[0], 400)

    def test_expired_or_malformed_token_response_is_rejected(self):
        for response in (token_response(expires_in=0), token_response(expires_in='3600'),
                         token_response(token_type=1), token_response(access_token='secret\r\nInjected: yes')):
            with mock.patch.object(oauth, 'post', return_value=response), self.assertRaises(oauth.SignInRequired):
                oauth.refresh(CONFIG, 'synthetic-refresh')

    def test_transport_refuses_every_redirect_and_redacts_upstream_errors(self):
        request = urllib.request.Request(CONFIG['exchange_url'], data=b'{}',
                                         headers={'Authorization': 'Bearer synthetic-secret'})
        with self.assertRaises(oauth.SignInRequired) as caught:
            oauth._NoRedirects().redirect_request(request, None, 307, 'secret', {},
                                                  'https://attacker.invalid')
        self.assertNotIn('secret', str(caught.exception))
        error = urllib.error.HTTPError(CONFIG['exchange_url'], 403, 'synthetic-secret', {}, io.BytesIO(b'secret'))
        opener = mock.Mock()
        opener.open.side_effect = error
        with mock.patch.object(oauth.urllib.request, 'build_opener', return_value=opener), \
                self.assertRaises(oauth.SignInRequired) as caught:
            oauth.post(CONFIG['exchange_url'], b'{}', {})
        self.assertEqual(caught.exception.code, 'access_denied')
        self.assertNotIn('secret', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
