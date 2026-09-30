"""Offer Switch Codex when the ChatGPT allowance runs out, and the way back.

Codex desktop 26.917.51856 and later disables Send for every model once the
ChatGPT allowance runs out. The router records each such episode in
`codex-usage-limit.json` (docs/runtime-files.md). Every updater pass, the
minute Express job included, reads it here and offers each of these at most
once per episode:

- Switch Codex, while the episode lasts and Codex still uses the ChatGPT
  subscription, when the episode came from a build from `AFFECTED_FROM` up to
  `FIXED_IN` and the installed ChatGPT app is not yet at `FIXED_IN`;
- the way back, while Codex is switched, once the episode has ended or the
  installed ChatGPT app is at or above `FIXED_IN`.

The dialog is only the offer: its action opens the Switch Codex app, which
asks before it changes anything. macOS only, and only for a Codex install in
subscription mode that has the app. An offer is recorded before its dialog
appears, so a home that cannot be written shows nothing rather than the same
offer every minute. A missing dialog tool, or a dialog that cannot be drawn,
leaves the offer pending for a later pass.

Python 3.9-safe, stdlib only and inert on import: the updater loads it by
path, and Switch Codex's installer reuses `APP`.
"""
import importlib.util
import json
import os
import plistlib
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from shutil import which

APP = Path.home() / 'Applications' / 'Switch Codex.app'
CHATGPT_APP = Path('/Applications/ChatGPT.app')
AFFECTED_FROM = '26.917.51856'
# The first ChatGPT app (Codex) build that keeps Send working once the
# allowance runs out; None until OpenAI ships the fix.
FIXED_IN = None
# The router's file and its rule for an episode with no named reset
# (ai_router/usage_episodes.NAME and WINDOW_S; a test pins both).
EPISODE_FILE = 'codex-usage-limit.json'
WINDOW_S = 5 * 60 * 60
OFFERS_FILE = 'codex-switch-offers.json'
SWITCH, BACK = 'switch', 'back'
OPEN = 'Open Switch Codex'
MESSAGES = {
    SWITCH: ('Your ChatGPT subscription has reached its usage limit, so the '
             'ChatGPT app (Codex) cannot send messages. Switch it to OpenRouter '
             'models until the limit resets?'),
    BACK: ('The ChatGPT app (Codex) can use your ChatGPT subscription again. '
           'Switch it back from OpenRouter models?'),
}
_VERSION = re.compile(r'\d{1,9}(?:\.\d{1,9}){0,5}')


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_HERE = Path(__file__).resolve().parent
_notice = _load('router_offer_notice', _HERE / 'notice.py')
_codex = _load('router_offer_codex_config', _HERE / 'codex_config.py')
_switch = _load('router_offer_switch_config', _HERE / 'codex_switch_config.py')
_atomic = _load('router_offer_atomic_write', _HERE / 'atomic_write.py')


def _version(text):
    """A dotted version as a tuple of ints, or None."""
    if not isinstance(text, str) or not _VERSION.fullmatch(text):
        return None
    return tuple(int(part) for part in text.split('.'))


def _seconds(text):
    """Unix seconds of an ISO-8601 time that names its UTC offset, else None."""
    try:
        moment = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    return moment.timestamp() if moment.tzinfo is not None else None


def episode(home):
    """The router's last episode with its `end`, or None when missing or corrupt.

    The fields and checks of `ai_router/usage_episodes.current`; the episode
    ends at `resets_at`, or `WINDOW_S` after `seen_at` when none was named.
    """
    try:
        doc = json.loads((Path(home) / EPISODE_FILE).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict):
        return None
    seen, resets, version = (doc.get(key) for key in ('seen_at', 'resets_at', 'client_version'))
    start = _seconds(seen)
    parsed = _version(version)
    if start is None or (version is not None and parsed is None):
        return None
    end = start + WINDOW_S if resets is None else _seconds(resets)
    if end is None:
        return None
    return {'seen_at': seen, 'end': end, 'version': parsed}


def installed():
    """The installed ChatGPT app's version as a tuple, or None."""
    try:
        info = plistlib.loads((CHATGPT_APP / 'Contents' / 'Info.plist').read_bytes())
    except (OSError, ValueError):
        return None
    return _version(info.get('CFBundleShortVersionString')) if isinstance(info, dict) else None


def _offered(home, seen_at):
    """The offers already made for the episode that started at `seen_at`."""
    try:
        doc = json.loads((Path(home) / OFFERS_FILE).read_text())
    except (OSError, ValueError):
        return []
    if (not isinstance(doc, dict) or doc.get('seen_at') != seen_at
            or not isinstance(doc.get('offered'), list)):
        return []
    return [kind for kind in doc['offered'] if kind in (SWITCH, BACK)]


def due(home, now=None, platform_name=None):
    """(kind, episode) for the offer this pass should make, else None."""
    if (platform_name or sys.platform) != 'darwin' or not APP.exists():
        return None
    entry = _codex.codex_attachment(home)
    current = episode(home)
    if not entry.get('inserted_block') or entry.get('openai_mode') == 'none' or current is None:
        return None
    now = time.time() if now is None else now
    fixed = _version(FIXED_IN)
    on_fixed = fixed is not None and (installed() or ()) >= fixed
    if _switch.recorded(entry) != _switch.SWITCHED:
        version = current['version']
        affected = (version is not None and version >= _version(AFFECTED_FROM)
                    and (fixed is None or version < fixed))
        kind = SWITCH if affected and not on_fixed and now < current['end'] else None
    else:
        kind = BACK if on_fixed or now >= current['end'] else None
    if kind is None or kind in _offered(home, current['seen_at']):
        return None
    return kind, current


def command(kind, icon):
    """osascript argv for one offer, or None when the dialog tool is missing."""
    tool = which('osascript')
    if tool is None:
        return None
    quote = lambda text: json.dumps(text, ensure_ascii=False)  # noqa: E731
    icon_clause = ' with icon (POSIX file %s)' % quote(icon) if icon else ' with icon note'
    return [tool, '-e', '\n'.join([
        'set answer to button returned of (display dialog %s with title %s '
        'buttons {%s, %s} default button %s cancel button %s%s)'
        % (quote(MESSAGES[kind]), quote(_notice.TITLE), quote(_notice.DISMISS),
           quote(OPEN), quote(OPEN), quote(_notice.DISMISS), icon_clause),
        'if answer is %s then do shell script "/usr/bin/open " & quoted form of %s'
        % (quote(OPEN), quote(str(APP)))])]


def _remember(home, seen_at, offered):
    _atomic.replace_json(Path(home) / OFFERS_FILE, {'seen_at': seen_at, 'offered': offered})


def offer(home, now=None, platform_name=None):
    """Make the offer due this pass; the kind shown, else None. Never raises."""
    try:
        if os.environ.get('ROUTER_NO_NOTICE') == '1':
            return None
        found = due(home, now, platform_name)
        if found is None:
            return None
        kind, current = found
        cmd = command(kind, _notice._home_icon(home) or str(_notice.ICON))
        if cmd is None:
            return None  # no dialog tool: the offer stays pending
        before = _offered(home, current['seen_at'])
        # Recorded first: a failed write raises here, before any dialog.
        _remember(home, current['seen_at'], before + [kind])
        try:
            shown = _notice._dialog_up(_notice._spawn(cmd), _notice._pid_alive)
        except (OSError, ValueError):
            shown = False
        if not shown:
            _remember(home, current['seen_at'], before)  # never drawn: still pending
            return None
        return kind
    except (Exception, SystemExit):  # an unknown receipt variant raises SystemExit
        return None
