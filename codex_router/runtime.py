"""Router home, state validation and structured logging."""
import json
import logging
import logging.handlers
import os
from datetime import datetime, timezone
from pathlib import Path
from .setup import setup_pending
from .credentials import Credentials, default_home

ROUTER_HOME = default_home()
STATE = ROUTER_HOME / 'mixed-router-state.json'
REQUIRED_STATE = {'port': int, 'token': str, 'openai_models': list}
MAX_BODY = 16 * 1024 * 1024

LOG = logging.getLogger('codex_router')

def _release_version():
    # Installed releases report the full build version from the bundle
    # manifest so /health matches what the updater installed; source
    # checkouts fall back to MAJOR.MINOR from packaging/VERSION.
    root = Path(__file__).resolve().parents[1]
    try:
        return json.loads((root / 'MANIFEST.json').read_text())['version']
    except (OSError, ValueError, KeyError):
        pass
    try:
        return (root / 'packaging' / 'VERSION').read_text().strip()
    except OSError:
        return 'unknown'


VERSION = _release_version()


def load_state(path=STATE):
    """Fail closed with a precise message; never echo the token."""
    try:
        state = json.loads(path.read_text())
    except FileNotFoundError:
        raise SystemExit(f'Router state file missing: {path}')
    except ValueError as exc:
        raise SystemExit(f'Router state file is not valid JSON: {path} ({exc.__class__.__name__})')
    missing = [k for k, t in REQUIRED_STATE.items() if not isinstance(state.get(k), t)]
    if missing:
        raise SystemExit('Router state file is missing or mistyped keys: ' + ', '.join(missing))
    if 'opencode_auth' in state and not isinstance(state['opencode_auth'], str):
        raise SystemExit('Router state file is missing or mistyped keys: opencode_auth')
    if 'openai_mode' in state and state['openai_mode'] not in ('subscription', 'none'):
        raise SystemExit('openai_mode must be subscription or none')
    try:
        Credentials(state, ROUTER_HOME).check()
    except (LookupError, PermissionError, ValueError, OSError) as exc:
        # A fresh unexpired setup nonce lets the router boot keyless so the
        # first-run window can collect the key; everything billable still
        # fails closed per request until one resolves.
        if not setup_pending(state):
            raise SystemExit(f'OpenRouter credential problem: {exc}')
    return state


def configure_logging(home=ROUTER_HOME):
    (home / 'logs').mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(home / 'logs' / 'router.jsonl',
                                                   maxBytes=5 * 1024 * 1024, backupCount=3)
    handler.setFormatter(logging.Formatter('%(message)s'))
    LOG.addHandler(handler)
    LOG.setLevel(logging.DEBUG if os.environ.get('ROUTER_DEBUG') else logging.INFO)


def log_event(event, **fields):
    LOG.info(json.dumps({'ts': datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
                         'event': event, **fields}))
