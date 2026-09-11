"""First-run key window over the loopback router (Plan 047 G, stdlib only).

The installer normally opens a native popup (`ai_router.key_prompt`) and the
running router spawns one when a request arrives keyless. Both submit here,
through the same single-use nonce route the HTML page uses, so validation,
owner-only storage, the starter and nonce closure stay in one place. The URL
carries a short-lived nonce distinct from the long-lived path token. Browsers
POST with an Origin header, so the route enforces same-origin itself; the
generic DNS-rebinding rejection stays closed for everything else.
"""
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import parse_qsl

from . import key_prompt, setup_page

_ON_WINDOWS = os.name == 'nt'

SETUP_TTL_S = 15 * 60
FORM_LIMIT = 4096
KEY_URL = 'https://openrouter.ai/api/v1/auth/key'


def setup_pending(state, now=None):
    """True while a fresh unexpired setup nonce is installed."""
    cfg = state.get('setup') if isinstance(state, dict) else None
    if not isinstance(cfg, dict):
        return False
    if not isinstance(cfg.get('nonce'), str) or not cfg['nonce']:
        return False
    if not isinstance(cfg.get('expires'), (int, float)) or isinstance(cfg.get('expires'), bool):
        return False
    return cfg['expires'] > (time.time() if now is None else now)


def valid_nonce(state, nonce, now=None):
    """Constant-time nonce check that also honors expiry (single-use on success)."""
    if not isinstance(nonce, str) or not nonce:
        return False
    cfg = state.get('setup') if isinstance(state, dict) else None
    expected = cfg.get('nonce') if isinstance(cfg, dict) else None
    if not isinstance(expected, str) or not expected:
        return False
    if not hmac.compare_digest(nonce, expected):
        return False
    return setup_pending(state, now)


def same_origin(origin, port):
    return origin is None or origin == f'http://127.0.0.1:{port}'


class KeyRejected(ValueError):
    """check_key refusal carrying the HTTP status; 401/403 means a dead key."""
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def check_key(key, _urlopen=urllib.request.urlopen):
    """(label, limit, usage) for a live key; KeyRejected when refused, OSError when down."""
    req = urllib.request.Request(KEY_URL, headers={'Authorization': 'Bearer ' + key})
    try:
        with _urlopen(req, timeout=20) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        raise KeyRejected('OpenRouter rejected the key', status=exc.code)
    data = payload.get('data') if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise KeyRejected('OpenRouter returned an unexpected key response')
    return (data.get('label') or 'key', data.get('limit'), data.get('usage'))


class KeyExists(OSError):
    """The key file holds a live key; rotation needs explicit deletion."""


def _claim_truncated(key_path):
    """Open an existing key file for overwrite, keeping owner-only mode."""
    fd = os.open(key_path, os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
    except OSError:
        pass
    return fd


def store_key(home, key, _check_live=None):
    """Write an OpenRouter key through the one shared writer."""
    key_path = Path(home) / 'openrouter.key'
    try:
        return os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    try:
        stored = key_path.read_bytes().strip()
    except OSError:
        raise OSError('could not store the key')
    if not stored:
        return _claim_truncated(key_path)
    if _check_live is not None and _check_live(stored.decode('utf-8', 'replace')) is False:
        return _claim_truncated(key_path)
    raise KeyExists('a key file already exists; delete it to rotate keys')


def handle_setup(state, home, nonce, is_post, form, _urlopen=None, _now=None):
    """(status, html body) for an already-routed setup request."""
    if not valid_nonce(state, nonce, _now):
        return 404, setup_page.not_found()
    if not is_post:
        return 200, setup_page.form(nonce)
    status, result = _submit(state, home, form, _urlopen)
    if result.get('ok'):
        return status, setup_page.done(result.get('label'), result.get('limit'),
                                       result.get('usage'),
                                       result.get('mode') or state.get('openai_mode', ''),
                                       result.get('starter', ''),
                                       state.get('clients', 'codex'))
    return status, setup_page.form(nonce, result.get('error'))


def handle_setup_json(state, home, nonce, form, _urlopen=None, _now=None):
    """(status, payload) for a popup POST; the same checks as the page."""
    if not valid_nonce(state, nonce, _now):
        return 404, {'ok': False, 'error': 'unknown or expired setup link; '
                                           're-run the installer'}
    return _submit(state, home, form, _urlopen)


def _submit(state, home, form, _urlopen):
    """(status, result) for a setup POST: one writer, both renderers."""
    _fetch = _urlopen or urllib.request.urlopen
    fields = dict(parse_qsl(form.decode('utf-8', 'replace'), keep_blank_values=True))
    key = fields.get('key', '').strip()
    # The native popup only sends the choices it actually asked; the HTML
    # page always sends both. A claude-only setup therefore leaves Codex
    # settings (openai_mode, agents_profile, starter) untouched.
    mode = fields.get('mode')
    profile = fields.get('profile')
    claude_mode = fields.get('claude_mode')
    if not key:
        return 422, {'ok': False, 'error': 'paste a key before saving'}
    if mode is not None and mode not in ('subscription', 'none'):
        return 422, {'ok': False, 'error': 'unknown choice; resubmit the form'}
    if profile is not None and profile not in ('general', 'dev'):
        return 422, {'ok': False, 'error': 'unknown choice; resubmit the form'}
    if claude_mode is not None and claude_mode not in ('subscription', 'none'):
        return 422, {'ok': False, 'error': 'unknown choice; resubmit the form'}
    try:
        label, limit, usage = check_key(key, _fetch)
    except ValueError as exc:
        return 422, {'ok': False, 'error': str(exc)}
    except OSError:
        return 502, {'ok': False, 'error': 'could not reach OpenRouter; retry shortly'}
    key_path = Path(home) / 'openrouter.key'
    try:
        fd = store_key(home, key, _check_live=lambda stored: _stored_key_live(stored, _fetch))
    except KeyExists as exc:
        return 409, {'ok': False, 'error': str(exc)}
    except OSError:
        return 500, {'ok': False, 'error': 'could not store the key'}
    with os.fdopen(fd, 'w') as stream:
        stream.write(key + '\n')
    if _ON_WINDOWS:
        # A Windows setup window never leaves an exposed key: refuse instead.
        from . import winacl
        try:
            winacl.check(key_path)
            protected = True
        except SystemExit:
            protected = False
        if not protected:
            try:
                key_path.unlink()
            except OSError:
                return 500, {'ok': False, 'error':
                             'could not protect %s; delete it and resubmit this page'
                             % key_path}
            return 500, {'ok': False, 'error': 'could not protect the key file'}
    from . import agents as _agents  # starter lives under ~/.codex
    starter = 'skipped'
    if profile is not None:
        try:
            starter = _agents.install(profile)
        except Exception:
            starter = 'skipped'
    if not _finish_setup(state, home, mode, profile, claude_mode):
        if profile is not None:
            _agents.revert(starter)
        return 500, {'ok': False, 'error':
                     'key stored but setup could not be closed; '
                     'delete the key file and run the installer again'}
    line = _agents.describe(starter)
    return 200, {'ok': True, 'label': label, 'limit': limit, 'usage': usage,
                 'mode': mode, 'claude_mode': claude_mode or '', 'starter': line}


def _stored_key_live(stored, _fetch):
    """True when the stored key still validates; False only on 401/403.

    Any other outcome (network down, rate limit, unparseable body) refuses
    the carve-out: truncating there could destroy the only copy of a live
    provisioned secret.
    """
    try:
        check_key(stored, _fetch)
    except KeyRejected as exc:
        return exc.status not in (401, 403)
    except (ValueError, OSError):
        return True
    return True


def open_key_window(server, home, _opener=None, _prompt=None):
    """Mint one setup nonce and open the key window; True when opened.

    Plan 055 Stage 3: at most one window per live nonce. When
    `setup_pending` already holds, the existing page is the window and no
    new nonce is minted. The nonce persists atomically (temp file plus
    `os.replace`), never through a truncating rewrite.

    Plan 139: the native popup is the primary window and runs on its own
    worker thread (it submits back to this server). The URL carries the
    per-install path token: it is printed only on a TTY and otherwise
    recorded as a token-free event.
    """
    import secrets as _secrets
    import webbrowser as _webbrowser
    opener = _opener or _webbrowser.open
    prompt = _prompt or key_prompt.open_window
    state = server.state
    with server.lock:
        if setup_pending(state):
            return True
        nonce = _secrets.token_urlsafe(32)
        expires = int(time.time()) + SETUP_TTL_S
        path = Path(home) / 'mixed-router-state.json'
        try:
            doc = json.loads(path.read_text())
            if not isinstance(doc, dict):
                return False
            doc['setup'] = {'nonce': nonce, 'expires': expires}
            _atomic_replace(path, doc)
        except (OSError, ValueError):
            return False
        if isinstance(state, dict):
            state['setup'] = {'nonce': nonce, 'expires': expires}
        url = ('http://127.0.0.1:%s/%s/setup/%s'
               % (state.get('port'), state.get('token'), nonce))
    try:
        opened = prompt(url, thread=True, opener=opener,
                        clients=state.get('clients', 'codex')) is not False
    except (OSError, ValueError):
        try:
            opened = opener(url) is not False
        except OSError:
            opened = False
    if sys.stdout.isatty():
        print('open %s to connect your OpenRouter key' % url)
    else:
        from .runtime import log_event as _log_event
        _log_event('setup_window_opened' if opened else 'setup_window_pending',
                   port=state.get('port'), path='/setup/')
    return opened


def _atomic_replace(path, doc):
    """Write doc atomically via tmp plus os.replace; retry past a stale tmp.

    A crash between O_EXCL create and replace leaves the deterministic tmp
    behind; without the retry every later nonce mint or close fails closed
    forever until someone unlinks it by hand.
    """
    tmp = path.with_name(path.name + '.setup.tmp')
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        try:
            tmp.unlink()
        except OSError:
            raise OSError('could not replace %s' % path)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(json.dumps(doc, indent=2) + '\n')
    os.replace(tmp, path)


def _finish_setup(state, home, mode=None, profile=None, claude_mode=None):
    """Drop the nonce and persist mode, profile and Claude's choice."""
    path = Path(home) / 'mixed-router-state.json'
    try:
        from . import catalogue
        doc = json.loads(path.read_text())
        if not isinstance(doc, dict):
            return False
        doc.pop('setup', None)
        if mode in ('subscription', 'none'):
            doc['openai_mode'] = mode
        if profile in ('general', 'dev'):
            doc['agents_profile'] = profile
        if claude_mode in ('subscription', 'none'):
            doc['claude_mode'] = claude_mode
            doc['anthropic_mode'] = claude_mode
        catalogue.merge_file(Path(home) / 'mixed-models.json',
                             openai_mode=mode or doc.get('openai_mode', 'subscription'))
        _atomic_replace(path, doc)
    except (OSError, ValueError):
        return False
    if isinstance(state, dict):
        state.pop('setup', None)
        if mode in ('subscription', 'none'):
            state['openai_mode'] = mode
        if profile in ('general', 'dev'):
            state['agents_profile'] = profile
        if claude_mode in ('subscription', 'none'):
            state['claude_mode'] = claude_mode
            state['anthropic_mode'] = claude_mode
    return True


def _reject(handler, status):
    """Empty rejection that always closes the connection."""
    handler.send_response(status)
    handler.send_header('Content-Length', '0')
    handler.end_headers()
    handler.close_connection = True
    return True


def serve(handler, nonce, is_post):
    """Answer a routed setup request from the handler; always returns True."""
    state = handler.server.state
    home = handler.server.credentials.home
    if is_post:
        try:
            length = int(handler.headers.get('Content-Length', '-1'))
        except ValueError:
            length = -1
        if length < 0 or length > FORM_LIMIT:
            return _reject(handler, 413)
        form = handler.rfile.read(length)
        # The bound socket, not server_port: socket-activated production boots
        # skip server_bind, which is the only place stdlib sets server_port.
        if not same_origin(handler.headers.get('Origin'),
                                handler.server.socket.getsockname()[1]):
            return _reject(handler, 403)
    else:
        form = None
    # The native popup asks for JSON; browsers keep the page unchanged.
    if is_post and 'application/json' in (handler.headers.get('Accept') or ''):
        status, payload = handle_setup_json(state, home, nonce, form)
        body = json.dumps(payload).encode()
        content_type = 'application/json; charset=utf-8'
    else:
        status, body = handle_setup(state, home, nonce, is_post, form)
        content_type = 'text/html; charset=utf-8'
    handler.send_response(status)
    handler.send_header('Content-Type', content_type)
    handler.send_header('Content-Length', str(len(body)))
    handler.send_header('Connection', 'close')
    handler.end_headers()
    handler.wfile.write(body)
    handler.close_connection = True
    return True
