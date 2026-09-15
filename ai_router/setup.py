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

from . import key_prompt, key_store, provider_defs, setup_page, state as state_mod
from .atomic_write import StaleTmp, replace_json

_ON_WINDOWS = os.name == 'nt'

SETUP_TTL_S = 15 * 60
FORM_LIMIT = 4096


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
    # Byte compares (Plan 136): compare_digest rejects non-ASCII str with
    # TypeError, which would drop a live setup-window request.
    if not hmac.compare_digest(nonce.encode('iso-8859-1'), expected.encode('iso-8859-1')):
        return False
    return setup_pending(state, now)


def same_origin(origin, port):
    return origin is None or origin == f'http://127.0.0.1:{port}'


def handle_setup(state, home, nonce, is_post, form, _urlopen=None, _now=None):
    """(status, html body) for an already-routed setup request."""
    provider_id = key_store.window_provider(state)
    if not valid_nonce(state, nonce, _now):
        return 404, setup_page.not_found()
    if not is_post:
        return 200, setup_page.form(nonce, provider_id)
    status, result = _submit(state, home, form, _urlopen)
    if result.get('ok'):
        return status, setup_page.done(result.get('label'), result.get('limit'),
                                       result.get('usage'),
                                       result.get('mode') or state.get('openai_mode', ''),
                                       result.get('starter', ''),
                                       state.get('clients', 'codex'))
    return status, setup_page.form(nonce, provider_id, result.get('error'))


def handle_setup_json(state, home, nonce, form, _urlopen=None, _now=None):
    """(status, payload) for a popup POST; the same checks as the page."""
    if not valid_nonce(state, nonce, _now):
        return 404, {'ok': False, 'error': 'unknown or expired setup link; '
                                           're-run the installer'}
    return _submit(state, home, form, _urlopen)


def _submit(state, home, form, _urlopen):
    """(status, result) for a setup POST: one writer, both renderers."""
    _fetch = _urlopen or urllib.request.urlopen
    provider_id = key_store.window_provider(state)
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
        label, limit, usage = key_store.check_key(provider_id, key, _fetch)
    except ValueError as exc:
        return 422, {'ok': False, 'error': str(exc)}
    except OSError:
        return 502, {'ok': False, 'error': 'could not reach %s; retry shortly'
                                        % provider_defs.label_for(provider_id)}
    try:
        key_path = key_store.store_key(
            home, key, provider_id,
            _check_live=lambda stored: key_store._stored_key_live(provider_id, stored, _fetch))
    except key_store.KeyExists as exc:
        return 409, {'ok': False, 'error': str(exc)}
    except OSError:
        return 500, {'ok': False, 'error': 'could not store the key'}
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


def open_key_window(server, home, provider_id=None, _opener=None, _prompt=None):
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
    if not provider_defs.is_external(provider_id):
        provider_id = provider_defs.DEFAULT_EXTERNAL
    with server.lock:
        if setup_pending(state):
            return _repoint_window(state, home, provider_id)
        nonce = _secrets.token_urlsafe(32)
        expires = int(time.time()) + SETUP_TTL_S
        path = state_mod.path(home)
        try:
            doc = state_mod.read(path)
            if doc is None:
                return False
            doc['setup'] = {'nonce': nonce, 'expires': expires,
                            'provider': provider_id}
            _atomic_replace(path, doc)
        except (OSError, ValueError):
            return False
        if isinstance(state, dict):
            state['setup'] = {'nonce': nonce, 'expires': expires,
                              'provider': provider_id}
        url = ('http://127.0.0.1:%s/%s/setup/%s'
               % (state.get('port'), state.get('token'), nonce))
    try:
        opened = prompt(url, thread=True, opener=opener,
                        clients=state.get('clients', 'codex'),
                        provider_id=provider_id) is not False
    except (OSError, ValueError):
        try:
            opened = opener(url) is not False
        except OSError:
            opened = False
    if sys.stdout.isatty():
        print('open %s to connect your %s key'
              % (url, provider_defs.label_for(provider_id)))
    else:
        from .runtime import log_event as _log_event
        _log_event('setup_window_opened' if opened else 'setup_window_pending',
                   port=state.get('port'), path='/setup/')
    return opened



def _repoint_window(state, home, provider_id):
    """Point an already-open window at the provider this request needs.

    One nonce slot: a second provider's request must not leave the open page
    collecting for a different provider. False when the state cannot be
    rewritten, so the caller reports the failure instead of pretending a
    window is ready.
    """
    if key_store.window_provider(state) == provider_id:
        return True
    try:
        path = state_mod.path(home)
        doc = state_mod.read(path)
        if doc is None or not isinstance(doc.get('setup'), dict):
            return False
        doc['setup']['provider'] = provider_id
        _atomic_replace(path, doc)
    except (OSError, ValueError):
        return False
    # Only after the rewrite succeeded: a failed re-point must not leave the
    # running server collecting for one provider while the state file and the
    # caller's answer disagree.
    if isinstance(state, dict) and isinstance(state.get('setup'), dict):
        state['setup']['provider'] = provider_id
    return True


def _atomic_replace(path, doc):
    # A crash between create and replace leaves the deterministic tmp behind;
    # the writer's default policy clears it once and retries, so a later nonce
    # mint or close cannot fail closed forever until someone unlinks it by hand.
    try:
        replace_json(path, doc, mode=None, tmp_name=path.name + '.setup.tmp')
    except StaleTmp:
        # Only a leftover we could not clear is remapped; every other OSError
        # keeps its own reason for the caller.
        raise OSError('could not replace %s' % path)


def _finish_setup(state, home, mode=None, profile=None, claude_mode=None):
    """Drop the nonce and persist mode, profile and Claude's choice."""
    path = state_mod.path(home)
    try:
        from . import catalogue
        doc = state_mod.read(path)
        if doc is None:
            return False
        doc.pop('setup', None)
        if mode in ('subscription', 'none'):
            doc['openai_mode'] = mode
        if profile in ('general', 'dev'):
            doc['agents_profile'] = profile
        if claude_mode in ('subscription', 'none'):
            doc['claude_mode'] = claude_mode
            doc['anthropic_mode'] = claude_mode
        from . import availability as _availability
        from . import provider_defs as _defs
        region = _availability.current_region(home)
        host = _defs.region_host(_defs.DEFAULT_EXTERNAL, region)
        # A fresh key changes what `/models/user` allows: refresh now so
        # the seeded catalogue matches the key at once.
        _avail, _key = None, _availability.current_key(home)
        if _key and host:
            snap = _availability.refresh(host, _key, home, region)
            _avail = None if snap is None else snap.get('models')
        catalogue.merge_file(Path(home) / 'mixed-models.json',
                             openai_mode=mode or doc.get('openai_mode', 'subscription'),
                             available=_avail)
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
