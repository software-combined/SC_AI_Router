"""First-run key window over the loopback router (Plan 047 G, stdlib only).

The daemon is already an authenticated HTTP server, so setup is one route on
it instead of a native dialog: the installer opens the setup URL in a browser
and the operator pastes one OpenRouter key. The URL carries a single-use
short-lived nonce distinct from the long-lived path token. Browsers POST with
an Origin header, so the route enforces same-origin itself; the generic
DNS-rebinding rejection stays closed for everything else.
"""
import hmac
import html
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import parse_qsl

SETUP_PREFIX = '/setup/'
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


def check_key(key, _urlopen=urllib.request.urlopen):
    """(label, limit, usage) for a live key; ValueError when rejected, OSError when down."""
    req = urllib.request.Request(KEY_URL, headers={'Authorization': 'Bearer ' + key})
    try:
        with _urlopen(req, timeout=20) as response:
            payload = json.load(response)
    except urllib.error.HTTPError:
        raise ValueError('OpenRouter rejected the key')
    data = payload.get('data') if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise ValueError('OpenRouter returned an unexpected key response')
    return (data.get('label') or 'key', data.get('limit'), data.get('usage'))


def _page(title, body):
    return ('<!doctype html><html><head><meta charset="utf-8">'
            f'<title>{html.escape(title)}</title></head><body>'
            f'<h1>{html.escape(title)}</h1>{body}</body></html>').encode()


def _form(nonce, error=None):
    complaint = f'<p><strong>Error:</strong> {html.escape(error)}</p>' if error else ''
    return _page('Connect OpenRouter', complaint + f'''<p>Paste an OpenRouter key. It is validated
before anything is stored, and kept in an owner-only file the router reads at request time.</p>
<form method="post" action="./{html.escape(nonce, quote=True)}">
<label>OpenRouter key <input type="password" name="key" autocomplete="off"></label>
<fieldset><legend>ChatGPT subscription</legend>
<label><input type="radio" name="mode" value="subscription" checked> I have one; route OpenAI models on it</label>
<label><input type="radio" name="mode" value="none"> No subscription; OpenRouter models only</label>
</fieldset><button type="submit">Save and connect</button></form>''')


def _done(label, limit, usage, mode):
    try:
        remaining = 'unlimited' if limit is None else str(limit - (usage or 0))
    except TypeError:
        remaining = 'unknown'
    return _page('Connected', f'<p>Key <strong>{html.escape(str(label))}</strong> validated. '
                              f'Remaining credit: <strong>{html.escape(remaining)}</strong>. '
                              f'Mode: <strong>{html.escape(mode)}</strong>. '
                              'You can close this window and restart Codex.</p>')


def handle_setup(state, home, nonce, is_post, form, _urlopen=None, _now=None):
    """(status, html body) for an already-routed setup request."""
    _fetch = _urlopen or urllib.request.urlopen
    if not valid_nonce(state, nonce, _now):
        return 404, _page('Not found', '<p>Unknown or expired setup link.</p>')
    if not is_post:
        return 200, _form(nonce)
    fields = dict(parse_qsl(form.decode('utf-8', 'replace'), keep_blank_values=True))
    key = fields.get('key', '').strip()
    mode = fields.get('mode', 'subscription')
    if not key:
        return 422, _form(nonce, 'paste a key before saving')
    if mode not in ('subscription', 'none'):
        return 422, _form(nonce, 'unknown subscription choice')
    try:
        label, limit, usage = check_key(key, _fetch)
    except ValueError as exc:
        return 422, _form(nonce, str(exc))
    except OSError:
        return 502, _form(nonce, 'could not reach OpenRouter; retry shortly')
    key_path = Path(home) / 'openrouter.key'
    try:
        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return 409, _form(nonce, 'a key file already exists; delete it to rotate keys')
    except OSError:
        return 500, _form(nonce, 'could not store the key')
    with os.fdopen(fd, 'w') as stream:
        stream.write(key + '\n')
    if not _finish_setup(state, home, mode):
        return 500, _form(nonce, 'key stored but setup could not be closed; '
                                 'delete the key file and resubmit this page')
    return 200, _done(label, limit, usage, mode)


def _finish_setup(state, home, mode):
    """Drop the single-use nonce and persist the chosen mode; False on IO failure."""
    path = Path(home) / 'mixed-router-state.json'
    try:
        doc = json.loads(path.read_text())
        if not isinstance(doc, dict):
            return False
        doc.pop('setup', None)
        doc['openai_mode'] = mode
        tmp = path.with_name(path.name + '.setup.tmp')
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(json.dumps(doc, indent=2) + '\n')
        os.replace(tmp, path)
    except (OSError, ValueError):
        return False
    if isinstance(state, dict):
        state.pop('setup', None)
        state['openai_mode'] = mode
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
    status, body = handle_setup(state, home, nonce, is_post, form)
    handler.send_response(status)
    handler.send_header('Content-Type', 'text/html; charset=utf-8')
    handler.send_header('Content-Length', str(len(body)))
    handler.send_header('Connection', 'close')
    handler.end_headers()
    handler.wfile.write(body)
    handler.close_connection = True
    return True
