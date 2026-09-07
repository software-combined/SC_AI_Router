"""Router home, state validation and structured logging."""
import json
import logging
import logging.handlers
import os
from datetime import datetime, timezone
from pathlib import Path
from .credentials import Credentials

ROUTER_HOME = Path(os.environ.get('ROUTER_HOME', Path.home() / '.codex' / 'mixed-model-router'))
STATE = ROUTER_HOME / 'mixed-router-state.json'
REQUIRED_STATE = {'port': int, 'token': str, 'openai_models': list}
MAX_BODY = 16 * 1024 * 1024

LOG = logging.getLogger('codex_router')

try:
    VERSION = (Path(__file__).resolve().parents[1] / 'packaging' / 'VERSION').read_text().strip()
except OSError:
    VERSION = 'unknown'


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
    try:
        Credentials(state, ROUTER_HOME).check()
    except (LookupError, PermissionError, ValueError, OSError) as exc:
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
