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
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import parse_qsl

_ON_WINDOWS = os.name == 'nt'

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


# Executive light theme lifted from SC_360 tokens (packages/ui/src/tokens.css): slate-50
# canvas, white card, blue-600 primary, slate-200 hairlines, 0.75rem radius, 2.75rem
# controls. Inline only: a loopback first-run page fetches no external asset or font.
_STYLE = '''*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:2.5rem 1rem;background:hsl(210,40%,98%);color:hsl(222,47%,11%);font:1rem/1.55 Inter,"Helvetica Neue",Arial,sans-serif;-webkit-font-smoothing:antialiased}
main{width:100%;max-width:32rem;background:#fff;border:1px solid hsl(214,32%,91%);border-radius:.75rem;overflow:hidden;box-shadow:0 1px 2px rgba(15,23,42,.05),0 10px 24px -12px rgba(15,23,42,.15)}
h1{margin:0;padding:1.125rem 1.5rem;border-bottom:1px solid hsl(214,32%,91%);letter-spacing:-.025em;font:500 1.0625rem/1.4 "Space Grotesk",Inter,Arial,sans-serif}
.b{padding:1.5rem}
p{margin:0 0 1.5rem;color:hsl(215,16%,45%);font-size:.9375rem}
label.f{display:block;margin-bottom:.5rem;font-size:.8125rem;font-weight:500}
input[type=password]{width:100%;min-height:2.75rem;padding:0 .75rem;background:#fff;border:1px solid hsl(214,32%,91%);border-radius:.5rem;color:inherit;font:inherit}
fieldset{margin:1.25rem 0 0;padding:0;border:0}
legend{padding:0 0 .5rem;font-size:.8125rem;font-weight:500}
.o{display:flex;gap:.625rem;align-items:flex-start;margin-bottom:.5rem;padding:.75rem;border:1px solid hsl(214,32%,91%);border-radius:.5rem;font-size:.9375rem;cursor:pointer}
.o:hover{background:hsl(214,100%,97%);border-color:hsl(221,83%,53%)}
.o em{display:block;margin-top:.125rem;color:hsl(215,16%,45%);font-size:.8125rem;font-style:normal}
input[type=radio]{margin:.2rem 0 0;accent-color:hsl(221,83%,53%)}
button{margin-top:1.5rem;width:100%;min-height:2.75rem;padding:0 1rem;border:0;border-radius:.5rem;background:hsl(221,83%,53%);color:#fff;cursor:pointer;font:500 .9375rem/1 Inter,Arial,sans-serif}
button:hover{background:hsl(221,83%,47%)}
:focus-visible{outline:2px solid hsl(221,83%,53%);outline-offset:2px}
.e{margin:0 0 1.25rem;padding:.75rem 1rem;border:1px solid hsl(0,72%,85%);border-radius:.5rem;background:hsl(0,86%,97%);color:hsl(0,72%,41%);font-size:.875rem}
dl{display:grid;grid-template-columns:auto 1fr;gap:.5rem 1rem;margin:0 0 1.5rem;font-size:.9375rem}
dt{color:hsl(215,16%,45%)}
dd{margin:0;font-weight:500;word-break:break-word}'''


def _page(title, body):
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{html.escape(title)}</title><style>{_STYLE}</style>'
            f'</head><body><main><h1>{html.escape(title)}</h1>'
            f'<div class="b">{body}</div></main></body></html>').encode()


def _form(nonce, error=None):
    complaint = f'<p class="e"><strong>Error:</strong> {html.escape(error)}</p>' if error else ''
    return _page('Connect OpenRouter', complaint + f'''<p>Paste an OpenRouter key. It is validated
before anything is stored, and kept in an owner-only file the router reads at request time.</p>
<form method="post" action="./{html.escape(nonce, quote=True)}">
<label class="f" for="key">OpenRouter key</label>
<input id="key" type="password" name="key" autocomplete="off" placeholder="sk-or-v1-...">
<fieldset><legend>ChatGPT subscription</legend>
<label class="o"><input type="radio" name="mode" value="subscription" checked><span>I have one
<em>Route OpenAI models on the subscription</em></span></label>
<label class="o"><input type="radio" name="mode" value="none"><span>No subscription
<em>OpenRouter models only</em></span></label>
</fieldset>
<fieldset><legend>Starter instructions</legend>
<label class="o"><input type="radio" name="profile" value="general" checked><span>General
<em>Everyday help: careful, brief, plain language</em></span></label>
<label class="o"><input type="radio" name="profile" value="dev"><span>Development
<em>Coding help: read first, small verified changes, tests</em></span></label>
</fieldset>
<p style="margin:1rem 0 0">The starter is installed only when no global
instructions file exists yet. An existing file is never overwritten.</p>
<button type="submit">Save and connect</button></form>''')


def _done(label, limit, usage, mode, starter):
    try:
        remaining = 'unlimited' if limit is None else str(limit - (usage or 0))
    except TypeError:
        remaining = 'unknown'
    return _page('Connected', f'''<p>Your key is validated and stored.</p>
<dl><dt>Key</dt><dd>{html.escape(str(label))}</dd>
<dt>Remaining credit</dt><dd>{html.escape(remaining)}</dd>
<dt>Mode</dt><dd>{html.escape(mode)}</dd>
<dt>Starter</dt><dd>{html.escape(starter)}</dd></dl>
<p>You can close this window and restart Codex.</p>''')


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
    profile = fields.get('profile', 'general')
    if not key:
        return 422, _form(nonce, 'paste a key before saving')
    if mode not in ('subscription', 'none') or profile not in ('general', 'dev'):
        return 422, _form(nonce, 'unknown choice; resubmit the form')
    try:
        label, limit, usage = check_key(key, _fetch)
    except ValueError as exc:
        return 422, _form(nonce, str(exc))
    except OSError:
        return 502, _form(nonce, 'could not reach OpenRouter; retry shortly')
    key_path = Path(home) / 'openrouter.key'
    try:
        fd = store_key(home, key, _check_live=lambda stored: _stored_key_live(stored, _fetch))
    except KeyExists as exc:
        return 409, _form(nonce, str(exc))
    except OSError:
        return 500, _form(nonce, 'could not store the key')
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
                return 500, _form(
                    nonce, 'could not protect %s; delete it and resubmit this page'
                    % key_path)
            return 500, _form(nonce, 'could not protect the key file')
    from . import agents as _agents  # starter lives under ~/.codex
    try:
        starter = _agents.install(profile)
    except Exception:
        starter = 'skipped'
    if not _finish_setup(state, home, mode, profile):
        _agents.revert(starter)
        return 500, _form(nonce, 'key stored but setup could not be closed; '
                                 'delete the key file and resubmit this page')
    line = _agents.describe(starter)
    return 200, _done(label, limit, usage, mode, line)


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


def open_key_window(server, home, _opener=None):
    """Mint one setup nonce and open the loopback key page; True when opened.

    Plan 055 Stage 3: at most one window per live nonce. When
    `setup_pending` already holds, the existing page is the window and no
    new nonce is minted. The nonce persists atomically (temp file plus
    `os.replace`), never through a truncating rewrite. The URL carries the
    per-install path token: it is opened in the browser, printed only on a
    TTY, and otherwise recorded as a token-free lifecycle event.
    """
    import secrets as _secrets
    import webbrowser as _webbrowser
    opener = _opener or _webbrowser.open
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


def _finish_setup(state, home, mode, profile='general'):
    """Drop the nonce and persist mode plus profile; False on IO failure."""
    path = Path(home) / 'mixed-router-state.json'
    try:
        from . import catalogue
        doc = json.loads(path.read_text())
        if not isinstance(doc, dict):
            return False
        doc.pop('setup', None)
        doc['openai_mode'] = mode
        doc['agents_profile'] = profile if profile in ('general', 'dev') else 'general'
        catalogue.merge_file(Path(home) / 'mixed-models.json', openai_mode=mode)
        _atomic_replace(path, doc)
    except (OSError, ValueError):
        return False
    if isinstance(state, dict):
        state.pop('setup', None)
        state['openai_mode'] = mode
        state['agents_profile'] = profile if profile in ('general', 'dev') else 'general'
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
