"""ChatGPT usage-limit episodes seen on Codex desktop requests.

Codex desktop 26.917.51856 and later disables Send for every model once the
ChatGPT allowance runs out. The router notes when that happens so the Express
job can offer Switch Codex once per episode, and the way back once it ends.
This module only records; it offers nothing.

The signal is the one Codex itself reads (`codex-rs/codex-api/src/
api_bridge.rs` at `rust-v0.158.0-alpha.2.1`, the CLI that Codex desktop
26.924.22138 bundles): a 429 whose body names `error.type`
`usage_limit_reached` becomes Codex's usage-limit error, with
`error.resets_at` in Unix seconds when upstream names the reset. Any other
429 is a plain rate limit to Codex, so a short transient refusal never opens
an episode here.

Codex desktop is told apart by the suffix its app-server adds to the
User-Agent from the desktop's `initialize` client info, `(Codex Desktop;
26.924.22138)`. The CLI names itself `codex-tui` there and is never recorded.

One episode is one limit period: it ends at `resets_at`, or `WINDOW_S` after
`seen_at` when upstream named no reset. A refusal inside it may only refine
`resets_at`; one after it starts a new episode. The file holds those three
fields and nothing from the request, and a failed write never fails a turn.
"""
import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from . import provider_defs
from .atomic_write import replace_json
from .events import log_event
from .upstream import parse_payload

NAME = 'codex-usage-limit.json'
LIMIT_TYPE = 'usage_limit_reached'
# Codex's shortest ChatGPT limit window is five hours (300 minutes).
WINDOW_S = 5 * 60 * 60
# A named reset in the past or further out than this is no limit period.
MAX_RESET_S = 31 * 24 * 60 * 60
_VERSION = r'\d{1,9}(?:\.\d{1,9}){0,5}'
_DESKTOP = re.compile(r'\(Codex Desktop; (' + _VERSION + ')?')
_LOCK = threading.Lock()


def path(home):
    """The episode file under one router home."""
    return Path(home) / NAME


def _stamp(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec='seconds')


def _seconds(value):
    """Unix seconds of an ISO-8601 time that names its UTC offset, else None."""
    try:
        moment = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return moment.timestamp() if moment.tzinfo is not None else None


def current(home):
    """The last recorded episode, ended or not; None when missing or corrupt."""
    try:
        doc = json.loads(path(home).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict):
        return None
    seen, resets, version = (doc.get(key) for key in ('seen_at', 'resets_at', 'client_version'))
    if (_seconds(seen) is None or (resets is not None and _seconds(resets) is None)
            or (version is not None and not (isinstance(version, str)
                                             and re.fullmatch(_VERSION, version)))):
        return None
    return {'seen_at': seen, 'resets_at': resets, 'client_version': version}


def _end(episode):
    """When an episode's limit period ends, in Unix seconds."""
    if episode['resets_at'] is not None:
        return _seconds(episode['resets_at'])
    return _seconds(episode['seen_at']) + WINDOW_S


def record(handler, prepared, body, now=None):
    """Note one ChatGPT subscription refusal of a Codex desktop request; never raises."""
    try:
        error = (parse_payload(body) or {}).get('error')
        if (prepared.provider != provider_defs.OPENAI.id or not isinstance(error, dict)
                or error.get('type') != LIMIT_TYPE):
            return
        agent = next((value for key, value in prepared.headers.items()
                      if key.lower() == 'user-agent'), None)
        desktop = _DESKTOP.search(agent) if isinstance(agent, str) else None
        # The handler tests' credential stubs carry no router home.
        home = getattr(handler.server.credentials, 'home', None)
        if desktop is None or home is None:
            return
        now = time.time() if now is None else now
        reset = error.get('resets_at')
        reset = (_stamp(reset) if isinstance(reset, (int, float)) and not isinstance(reset, bool)
                 and now < reset <= now + MAX_RESET_S else None)
        with _LOCK:
            episode = current(home)
            if episode is not None and now < _end(episode):
                if reset is None or reset == episode['resets_at']:
                    return
                episode['resets_at'] = reset
            else:
                episode = {'seen_at': _stamp(now), 'resets_at': reset,
                           'client_version': desktop.group(1)}
            replace_json(path(home), episode)
    except Exception as exc:  # noqa: BLE001 - the record never fails or delays a turn
        log_event('usage_episode_failed', reason=type(exc).__name__)
