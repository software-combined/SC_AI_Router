"""Entra public-client PKCE and bounded HTTPS transport; Python 3.9+ stdlib."""
import base64
import hashlib
import hmac
import http.server
import json
from pathlib import Path
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

CALLBACK_PATH = '/scg-router/signin'
MAX_RESPONSE = 65536
MESSAGES = {
    'configuration_required': 'Staff download sign-in has not been configured.',
    'configuration_invalid': 'Staff download sign-in settings need IT attention.',
    'signin_required': 'Sign in with your work account to download updates.',
    'signin_failed': 'Work account sign-in did not finish. Try again.',
    'access_denied': 'This work account does not have download access.',
    'download_unavailable': 'Download access is temporarily unavailable. Try again later.',
    'session_invalid': 'Saved download sign-in needs IT attention.',
}


class SignInRequired(RuntimeError):
    """Only fixed messages and reason codes may reach UI or diagnostic logs."""
    def __init__(self, code='signin_required', status=None):
        self.code = code if code in MESSAGES else 'signin_required'
        self.status = status
        super().__init__(MESSAGES[self.code])


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SignInRequired('download_unavailable')


def post(url, data, headers):
    """Never relay a token, authorization code or refresh token on redirects."""
    request = urllib.request.Request(url, data=data, headers=headers, method='POST')
    try:
        opener = urllib.request.build_opener(_NoRedirects())
        with opener.open(request, timeout=20) as response:
            raw = response.read(MAX_RESPONSE + 1)
            if response.status != 200 or len(raw) > MAX_RESPONSE:
                raise SignInRequired('download_unavailable')
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError('invalid shape')
            return result
    except urllib.error.HTTPError as exc:
        # Do not retain, print or parse upstream error bodies containing tokens.
        code = ('access_denied' if exc.code == 403 else 'signin_required'
                if exc.code in (400, 401) else 'download_unavailable')
        exc.close()
        raise SignInRequired(code, status=exc.code) from None
    except (OSError, ValueError):
        raise SignInRequired('download_unavailable') from None


def _token(config, fields):
    fields.update(client_id=config['client_id'], scope=config['scope'] + ' offline_access')
    url = ('https://login.microsoftonline.com/' + config['tenant_id']
           + '/oauth2/v2.0/token')
    result = post(url, urllib.parse.urlencode(fields).encode('ascii'),
                  {'Content-Type': 'application/x-www-form-urlencoded'})
    access = result.get('access_token')
    expiry = result.get('expires_in')
    refresh = result.get('refresh_token')
    token_type = result.get('token_type')
    if (not isinstance(token_type, str) or token_type.lower() != 'bearer'
            or not isinstance(access, str) or not access or len(access) > 32768
            or any(ord(char) < 33 or ord(char) > 126 for char in access)
            or type(expiry) is not int or not 30 < expiry <= 86400
            or (refresh is not None and (not isinstance(refresh, str)
                                        or not refresh or len(refresh) > 32768))):
        raise SignInRequired('signin_failed')
    return {'access_token': access, 'refresh_token': refresh,
            'expires_at': time.time() + expiry}


def refresh(config, refresh_token):
    return _token(config, {'grant_type': 'refresh_token', 'refresh_token': refresh_token})


def callback_code(query, expected_state):
    """Reject duplicate parameters and validate state before consuming a code."""
    try:
        fields = urllib.parse.parse_qs(query, keep_blank_values=True,
                                      strict_parsing=True, max_num_fields=12)
        state = fields.get('state', [])
        if len(state) != 1 or not hmac.compare_digest(state[0], expected_state):
            raise ValueError('state')
        code = fields.get('code', [])
        if ('error' in fields or len(code) != 1 or not code[0]
                or len(code[0]) > 8192):
            raise ValueError('code')
        return code[0]
    except (TypeError, ValueError):
        raise SignInRequired('signin_failed') from None


class _Callback(http.server.BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(3)
        super().setup()

    def log_message(self, *_args):
        pass  # The request target contains the authorization code.

    def do_GET(self):
        try:
            target = urllib.parse.urlsplit(self.path)
        except ValueError:
            self._reply(400, 'This sign-in request could not be accepted.')
            return
        if (target.path != CALLBACK_PATH or target.scheme or target.netloc
                or len(self.path) > 16384
                or self.headers.get('Host') != self.server.expected_host):
            self._reply(400, 'This sign-in request could not be accepted.')
            return
        try:
            self.server.result = callback_code(target.query, self.server.state)
        except SignInRequired:
            self.server.result = False
            self._reply(400, 'Sign-in did not finish. You can close this tab and try again.')
            return
        self._reply(200, "You're signed in. You can close this tab.")

    def _reply(self, status, message):
        body = message.encode('utf-8')
        content_type = 'text/plain; charset=utf-8'
        policy = "default-src 'none'; frame-ancestors 'none'"
        if status == 200:
            assets = Path(__file__).with_name('assets')
            nonce = secrets.token_urlsafe(24)
            page = (assets / 'signin.html').read_text(encoding='utf-8').replace('__NONCE__', nonce)
            for marker, name in (('__LOGO__', 'router-icon.png'),
                                 ('__INTER__', 'inter-400.woff2'),
                                 ('__DISPLAY__', 'space-grotesk-400.woff2')):
                page = page.replace(marker, base64.b64encode((assets / name).read_bytes()).decode('ascii'))
            body = page.encode('utf-8')
            content_type = 'text/html; charset=utf-8'
            policy += ("; img-src data:; font-src data:; style-src 'nonce-" + nonce
                       + "'; script-src 'nonce-" + nonce + "'; base-uri 'none'; form-action 'none'")
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', policy)
        self.end_headers()
        self.wfile.write(body)


def authorize(config):
    """Bind before opening the system browser; one bounded loopback callback."""
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    state = secrets.token_urlsafe(32)
    try:
        with http.server.HTTPServer(('127.0.0.1', 0), _Callback) as server:
            server.timeout = 1
            server.state, server.result = state, None
            server.expected_host = 'localhost:' + str(server.server_port)
            redirect_uri = 'http://' + server.expected_host + CALLBACK_PATH
            fields = {'client_id': config['client_id'], 'response_type': 'code',
                      'redirect_uri': redirect_uri, 'response_mode': 'query',
                      'scope': config['scope'] + ' offline_access', 'state': state,
                      'code_challenge': challenge, 'code_challenge_method': 'S256'}
            url = ('https://login.microsoftonline.com/' + config['tenant_id']
                   + '/oauth2/v2.0/authorize?' + urllib.parse.urlencode(fields))
            if not webbrowser.open(url, new=1, autoraise=True):
                raise SignInRequired('signin_failed')
            deadline = time.monotonic() + 180
            while server.result is None and time.monotonic() < deadline:
                server.handle_request()
            if not server.result:
                raise SignInRequired('signin_failed')
            code = server.result
    except (OSError, webbrowser.Error):
        raise SignInRequired('signin_failed') from None
    return _token(config, {'grant_type': 'authorization_code', 'code': code,
                          'redirect_uri': redirect_uri, 'code_verifier': verifier})
