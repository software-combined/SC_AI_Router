"""PKCE binds one browser callback and never redirects credential requests."""
import base64
import hashlib
import http.client
import io
import re
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest import mock
from tests.test_download_auth import CONFIG, auth, token_response

oauth = auth._oauth


class OAuthTests(unittest.TestCase):
    def test_callback_shows_branded_confirmation_without_exposing_the_code(self):
        with oauth.http.server.HTTPServer(('127.0.0.1', 0), oauth._Callback) as server:
            server.state, server.result = 'right', None
            server.expected_host = 'localhost:' + str(server.server_port)
            worker = threading.Thread(target=server.handle_request, daemon=True)
            worker.start()
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            try:
                connection.request('GET', '/scg-router/signin?state=right&code=synthetic-private-code',
                                   headers={'Host': server.expected_host})
                response = connection.getresponse()
                body = response.read().decode()
                policy = response.getheader('Content-Security-Policy')
                self.assertEqual(response.status, 200)
                self.assertEqual(response.getheader('Content-Type'), 'text/html; charset=utf-8')
                self.assertEqual(response.getheader('Cache-Control'), 'no-store')
                self.assertEqual(response.getheader('Referrer-Policy'), 'no-referrer')
            finally:
                connection.close()
                worker.join(timeout=5)
        self.assertEqual(server.result, 'synthetic-private-code')
        self.assertIn("You're signed in", body)
        self.assertIn('You can close this tab.', body)
        self.assertIn('alt="Software Combined"', body)
        self.assertIn('data:image/png;base64,', body)
        self.assertEqual(body.count('data:font/woff2;base64,'), 2)
        self.assertNotIn('synthetic-private-code', body)
        self.assertNotIn('return to', body.lower())
        self.assertNotIn('__NONCE__', body)
        self.assertIn('history.replaceState(null,"","/complete")', body)
        nonce = re.search(r'<script nonce="([A-Za-z0-9_-]+)">', body)[1]
        self.assertIn("script-src 'nonce-" + nonce + "'", policy)
        self.assertIn("style-src 'nonce-" + nonce + "'", policy)
        self.assertIn("default-src 'none'", policy)

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
