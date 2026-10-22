"""Wording for the restart dialog, and the models it names.

Split from `notice.py` so the sentence, the client-aware action and the
bounded loopback calls to the router's pending models share one owner that
the installer surface can load on Python 3.9 without importing the
runtime. Every call here is best effort: a router that is down, slow or
answers anything unexpected names no model, and no named model means no
dialog, so the dialog never blocks or fails an update.
"""
import json
import urllib.parse
import urllib.request
from pathlib import Path

STATE_FILE = 'mixed-router-state.json'
# Keep the dialog short enough to scan.
DIALOG_NAMES = 3
# The installer waits on this path: a short read, and a short deadline.
PENDING_TIMEOUT_S = 1.0
PENDING_LIMIT = 1 << 18

# Which client(s) this install serves: the wording names them instead of
# always talking about Codex. 'none' is a service-only install.
CLIENTS = ('codex', 'claude', 'both', 'none')


def clients(value):
    """One known attachment set, defaulting to a Codex-only install."""
    return value if value in CLIENTS else 'codex'


def message(version, clients='codex', names=(), attachment=False):
    """Restart instruction for the clients this install actually serves.

    `names` are the models the update added, as the picker labels them.
    Without them the sentence keeps its version-only shape.
    """
    if clients == 'claude':
        action = 'Restart Claude Code'
    elif clients == 'both':
        action = 'Quit and reopen Codex and restart Claude Code'
    elif clients == 'none':
        action = 'Restart your AI client'
    else:
        action = 'Quit and reopen Codex'
    if attachment:
        listed = '\nNew models:\n' + '\n'.join('- %s' % name for name in names) if names else ''
        return 'SCG Router was reconnected.%s\n%s to load the changes.' % (listed, action)
    if names:
        listed = '\n'.join('- %s' % name for name in names)
        return ('SCG Router was updated to %s.\nNew models:\n%s\n%s to use them.'
                % (version, listed, action))
    return ('SCG Router was updated to %s. %s to use the new models.'
            % (version, action))


def _read(home, _urlopen):
    """(prompt URL, opener, reply) from the running router; raises if unusable.

    The running router answers `/model-prompt` with the policy-filtered rows
    it would announce, so a row outside the machine's policy never reaches a
    dialog. The port and path token come from the state file the caller
    already owns; the token stays on the loopback and is never printed.
    """
    state = json.loads((Path(home) / STATE_FILE).read_text())
    port, token = state.get('port'), state.get('token')
    if not isinstance(port, int) or not 0 < port < 65536:
        raise ValueError('no usable router port')
    if not isinstance(token, str) or not token:
        raise ValueError('no usable router token')
    # No proxy handling: the path token must never travel off loopback.
    opener = _urlopen or urllib.request.build_opener(
        urllib.request.ProxyHandler({})).open
    url = 'http://127.0.0.1:%d/%s/model-prompt' % (port, token)
    with opener(url, timeout=PENDING_TIMEOUT_S) as response:
        reply = json.loads(response.read(PENDING_LIMIT).decode())
    if not isinstance(reply, dict) or not isinstance(reply.get('pending'), list):
        raise ValueError('no pending rows in the reply')
    return url, opener, reply


def dialog_names(rows):
    """What a dialog lists: the first picker labels and a count of the rest.

    Every caller that names a dialog's models uses this, so `acknowledge`
    compares against exactly what was shown.
    """
    names = [row.get('name') or row.get('slug')
             for row in rows[:DIALOG_NAMES] if isinstance(row, dict)]
    if len(rows) > DIALOG_NAMES:
        names.append('+%d more' % (len(rows) - DIALOG_NAMES))
    return names


def pending_names(home, _urlopen=None):
    """Picker labels of the added models, or [] when the router cannot say."""
    try:
        return dialog_names(_read(home, _urlopen)[2]['pending'])
    except Exception:
        return []


def acknowledge(home, names, _urlopen=None):
    """Mark the router's pending models seen once a dialog has listed them.

    The dialog names three models and counts the rest, so it covers every
    pending row, as the old approval page did. Nothing is marked unless the
    rows still read as exactly `names`: a model that arrived after the
    dialog stays pending for the next one. The post goes only to this
    install's own page link, through the router's Later action.
    """
    try:
        url, opener, reply = _read(home, _urlopen)
        rows, link = reply['pending'], reply.get('url')
        if (not rows or dialog_names(rows) != names or not isinstance(link, str)
                or not link.startswith(url + '/')):
            return
        form = [('action', 'later')] + [('m', row['slug']) for row in rows]
        opener(urllib.request.Request(link, urllib.parse.urlencode(form).encode()),
               timeout=PENDING_TIMEOUT_S).close()
    except Exception:
        pass
