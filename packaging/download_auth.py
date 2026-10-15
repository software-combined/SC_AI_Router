"""Staff download access, independent of the rollback-selected router release.

Public deployment settings come from home/download-auth.json. No configured
tenant or session grants anonymous access. The caller scopes the returned
Cookie header to DISTRIBUTION_ORIGIN and must reject credential redirects.
"""
import base64
import hashlib
import importlib.util
import json
import re
import time
import urllib.parse
import uuid
from pathlib import Path


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_oauth = _load('router_download_oauth', 'download_oauth.py')
_session = _load('router_download_session', 'download_session.py')
SignInRequired = _oauth.SignInRequired
DISTRIBUTION_ORIGIN = 'https://dist.softwarecombined.com'
CONFIG_FILE = 'download-auth.json'
COOKIE_NAMES = ('CloudFront-Policy', 'CloudFront-Signature',
                'CloudFront-Key-Pair-Id', 'CloudFront-Hash-Algorithm')


def configure(home):
    """Read required public settings supplied by the signed installer/controller."""
    path = Path(home) / CONFIG_FILE
    try:
        if path.is_symlink():
            raise ValueError('symlink')
        with path.open('rb') as stream:
            raw = stream.read(8193)
        if len(raw) > 8192:
            raise ValueError('size')
        config = json.loads(raw)
        if (not isinstance(config, dict) or type(config.get('version')) is not int
                or config['version'] != 1
                or config.get('distribution_origin') != DISTRIBUTION_ORIGIN):
            raise ValueError('schema')
        for name in ('tenant_id', 'client_id'):
            value = config[name]
            if not isinstance(value, str) or str(uuid.UUID(value)) != value:
                raise ValueError('identifier')
        if not re.fullmatch(r'api://[0-9a-f-]{36}/Download\.Read', config['scope']):
            raise ValueError('scope')
        uuid.UUID(config['scope'].split('/')[2])
        endpoint = urllib.parse.urlsplit(config['exchange_url'])
        if (endpoint.scheme != 'https' or endpoint.username or endpoint.password
                or endpoint.port not in (None, 443) or endpoint.query or endpoint.fragment
                or endpoint.path != '/download-access'
                or not re.fullmatch(r'[a-z0-9]+\.execute-api\.[a-z0-9-]+\.amazonaws\.com',
                                    endpoint.hostname or '')):
            raise ValueError('endpoint')
        return {name: config[name] for name in ('version', 'distribution_origin',
                'tenant_id', 'client_id', 'scope', 'exchange_url')}
    except FileNotFoundError:
        raise SignInRequired('configuration_required') from None
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise SignInRequired('configuration_invalid') from None


def _config_id(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


def _read(home, config):
    try:
        session = _session.read(home)
        return session if session.get('config_id') == _config_id(config) else {}
    except (OSError, ValueError):
        raise SignInRequired('session_invalid') from None


def _write(home, session):
    try:
        _session.write(home, session)
    except (OSError, ValueError):
        raise SignInRequired('session_invalid') from None


def _cookie_header(receipt):
    """Validate expiry, fixed resource scope and safe header characters."""
    try:
        expiry, cookies = receipt['expires_at'], receipt['cookies']
        if (type(expiry) is not int or not isinstance(cookies, dict)
                or not time.time() + 30 < expiry <= time.time() + 900
                or set(cookies) != set(COOKIE_NAMES)
                or cookies['CloudFront-Hash-Algorithm'] != 'SHA256'):
            raise ValueError('receipt')
        if any(not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_~\-]{1,4096}', value)
               for value in cookies.values()):
            raise ValueError('cookie')
        encoded = cookies['CloudFront-Policy'].translate(str.maketrans('-_~', '+=/'))
        policy = json.loads(base64.b64decode(encoded, validate=True))
        expected = {'Statement': [{'Resource': DISTRIBUTION_ORIGIN + '/*',
                    'Condition': {'DateLessThan': {'AWS:EpochTime': expiry}}}]}
        if policy != expected:
            raise ValueError('policy scope')
        return '; '.join(name + '=' + cookies[name] for name in COOKIE_NAMES)
    except (KeyError, TypeError, ValueError):
        raise SignInRequired('signin_required') from None


def _exchange(home, config, session, token):
    if token.get('expires_at', 0) <= time.time() + 30:
        raise SignInRequired('signin_required')
    refresh_token = token.get('refresh_token') or session.get('refresh_token')
    if not isinstance(refresh_token, str) or not refresh_token or len(refresh_token) > 32768:
        raise SignInRequired('signin_required')
    # Preserve rotation even if the exchange fails. Never persist an access token.
    session = {'config_id': _config_id(config), 'refresh_token': refresh_token}
    _write(home, session)
    receipt = _oauth.post(config['exchange_url'], b'{}',
                          {'Authorization': 'Bearer ' + token['access_token'],
                           'Content-Type': 'application/json'})
    header = _cookie_header(receipt)
    session['receipt'] = {'cookies': receipt['cookies'], 'expires_at': receipt['expires_at']}
    _write(home, session)
    return header


def ensure_access(home, interactive=False):
    """Return a short-lived Cookie header; background callers never open a browser."""
    config = configure(home)
    session = _read(home, config)
    try:
        return _cookie_header(session.get('receipt', {}))
    except SignInRequired:
        pass
    refresh_token = session.get('refresh_token')
    if isinstance(refresh_token, str) and 0 < len(refresh_token) <= 32768:
        try:
            return _exchange(home, config, session, _oauth.refresh(config, refresh_token))
        except SignInRequired as exc:
            if not interactive or exc.code != 'signin_required':
                raise
    if interactive:
        return _exchange(home, config, {}, _oauth.authorize(config))
    raise SignInRequired()


def signin(home):
    """Explicit user action: always run work-account sign-in in the system browser."""
    config = configure(home)
    return _exchange(home, config, {}, _oauth.authorize(config))


def status(home):
    """Local redacted readiness only; cached state is not current entitlement proof."""
    result = {'configured': False, 'signed_in': False, 'access_ready': False}
    try:
        config = configure(home)
        result['configured'] = True
        session = _read(home, config)
        refresh_token = session.get('refresh_token')
        result['signed_in'] = isinstance(refresh_token, str) and 0 < len(refresh_token) <= 32768
        _cookie_header(session.get('receipt', {}))
        result.update(access_ready=True, expires_at=session['receipt']['expires_at'])
    except SignInRequired as exc:
        result['reason'] = exc.code
    return result
