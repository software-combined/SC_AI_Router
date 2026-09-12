"""Approval page for the new-model prompt (Plan 135).

Served over loopback with the single-use nonce `model_prompt.notice` mints.
The page lists the pending models and offers Restart Codex or Later; the
restart command runs only from the nonce-authenticated POST click. Inline
style only: a loopback page must not fetch anything.
"""
import html
import subprocess
import sys
from urllib.parse import parse_qs

from . import model_prompt
from .setup import same_origin

FORM_LIMIT = 4096
LIST_LIMIT = 12

_STYLE = (
    '*{box-sizing:border-box}'
    'body{margin:0;min-height:100vh;display:flex;align-items:center;'
    'justify-content:center;padding:2.5rem 1rem;background:hsl(210,40%,98%);'
    'color:hsl(222,47%,11%);font:1rem/1.55 Inter,"Helvetica Neue",Arial,sans-serif}'
    'main{width:100%;max-width:32rem;background:#fff;'
    'border:1px solid hsl(214,32%,91%);border-radius:.75rem;overflow:hidden;'
    'box-shadow:0 1px 2px rgba(15,23,42,.05),0 10px 24px -12px rgba(15,23,42,.15)}'
    'h1{margin:0;padding:1.125rem 1.5rem;border-bottom:1px solid hsl(214,32%,91%);'
    'font:500 1.0625rem/1.4 "Space Grotesk",Inter,Arial,sans-serif}'
    '.b{padding:1.5rem}'
    'p{margin:0 0 1.25rem;color:hsl(215,16%,45%);font-size:.9375rem}'
    'ul{margin:0 0 1.5rem;padding-left:1.25rem;font-size:.9375rem}'
    'li{margin-bottom:.375rem}'
    'li span{color:hsl(215,16%,45%)}'
    'form{display:flex;gap:.625rem}'
    'button{flex:1;min-height:2.75rem;padding:0 1rem;border:0;border-radius:.5rem;'
    'cursor:pointer;font:500 .9375rem/1 Inter,Arial,sans-serif}'
    '.p{background:hsl(221,83%,53%);color:#fff}'
    '.s{background:#fff;border:1px solid hsl(214,32%,91%);color:inherit}'
    ':focus-visible{outline:2px solid hsl(221,83%,53%);outline-offset:2px}')


def _page(title, body):
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{html.escape(title)}</title><style>{_STYLE}</style>'
            f'</head><body><main><h1>{html.escape(title)}</h1>'
            f'<div class="b">{body}</div></main></body></html>').encode()


def nothing_to_do():
    return _page('Nothing to do', '<p>No new models are waiting.</p>')


def not_found():
    return _page('Link expired',
                 '<p>This link is no longer valid. Open the newest one.</p>')


def pending(rows):
    """The offer page: the visible names plus both actions."""
    names = ''.join(f'<li>{html.escape(name)} <span>{html.escape(slug)}</span></li>'
                    for slug, name in rows[:LIST_LIMIT])
    if len(rows) > LIST_LIMIT:
        names += f'<li>and {len(rows) - LIST_LIMIT} more</li>'
    fields = ''.join(f'<input type="hidden" name="m" value="{html.escape(slug)}">'
                     for slug, _ in rows)
    return _page('New models available', (
        '<p>These models are ready; restart Codex to use them.</p>'
        f'<ul>{names}</ul>'
        f'<form method="post">{fields}'
        '<button class="p" name="action" value="restart" type="submit">Restart Codex</button>'
        '<button class="s" name="action" value="later" type="submit">Later</button>'
        '</form>'))


def restarted(ok):
    if ok:
        return _page('Restarting Codex',
                     '<p>Codex is quitting and will reopen with the new models.</p>')
    return _page('Restart Codex yourself',
                 '<p>Automatic restart is not available here. Quit and reopen '
                 'Codex to load the new models.</p>')


def later():
    return _page('Later',
                 '<p>No problem. Restart Codex whenever you like; the new '
                 'models will appear then.</p>')


def restart_codex(run=None, platform=None):
    """Quit and reopen the Codex app; True when both commands succeed.

    macOS only: the app is addressed by name, never by process pattern, and
    nothing runs unless the POST click reached this module. A refused quit
    (missing Automation consent, app busy) reports failure: `open` would
    only raise the running app and the client would keep its old catalogue.
    """
    if (platform or sys.platform) != 'darwin':
        return False
    runner = run or subprocess.run
    try:
        quit_result = runner(['osascript', '-e', 'quit app "Codex"'],
                             check=False, capture_output=True)
        if getattr(quit_result, 'returncode', 1) != 0:
            return False
        opened = runner(['open', '-a', 'Codex'],
                        check=False, capture_output=True)
    except OSError:
        return False
    return getattr(opened, 'returncode', 1) == 0


def _send(handler, status, body):
    handler.send_response(status)
    handler.send_header('Content-Type', 'text/html; charset=utf-8')
    handler.send_header('Content-Length', str(len(body)))
    handler.send_header('Connection', 'close')
    handler.end_headers()
    handler.wfile.write(body)
    handler.close_connection = True
    return True


def _reject(handler, status):
    handler.send_response(status)
    handler.send_header('Content-Length', '0')
    handler.end_headers()
    handler.close_connection = True
    return True


def _fields(handler):
    """(parsed form, rejection status) for a same-origin POST body."""
    try:
        length = int(handler.headers.get('Content-Length', '-1'))
    except ValueError:
        length = -1
    if length < 0 or length > FORM_LIMIT:
        return None, 413
    port = handler.server.socket.getsockname()[1]
    if not same_origin(handler.headers.get('Origin'), port):
        return None, 403
    body = handler.rfile.read(length)
    return parse_qs(body.decode('utf-8', 'replace'), keep_blank_values=True), None


def handle_page(handler, nonce, is_post):
    """Answer a routed /model-prompt/<nonce> request; always returns True."""
    home = handler.server.credentials.home
    if is_post:
        fields, status = _fields(handler)
        if status is not None:
            return _reject(handler, status)
        action = (fields.get('action') or [''])[0]
        displayed = fields.get('m') or None
    else:
        action, displayed = None, None
    rows = model_prompt.check_notice(home, 'codex', nonce)
    if rows is None:
        return _send(handler, 404, not_found())
    if not rows:
        # Nothing is pending: never restart, and never consume the link.
        return _send(handler, 200, nothing_to_do())
    if not is_post:
        return _send(handler, 200, pending(rows))
    if action not in ('restart', 'later'):
        return _send(handler, 200, pending(rows))
    model_prompt.acknowledge(home, 'codex', displayed=displayed)
    if action == 'restart':
        return _send(handler, 200, restarted(restart_codex()))
    return _send(handler, 200, later())
