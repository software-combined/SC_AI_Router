"""Router home, state validation and the boot composition root (Plan 165)."""
import json
import string
from pathlib import Path
from . import provider_defs, registry, state as state_mod
from .credentials import Credentials
from .events import LOG, configure_logging, log_event  # noqa: F401 (re-exported)
from .state import default_home, setup_pending

ROUTER_HOME = default_home()
STATE = state_mod.path(ROUTER_HOME)
REQUIRED_STATE = {'port': int, 'token': str, 'openai_models': list}
MAX_BODY = 16 * 1024 * 1024
# zstd may expand this far so prepare can slim tool_search schemas;
# the prepared upstream body is still refused above MAX_BODY.
MAX_DECODE_FACTOR = 4
TOKEN_MIN_LENGTH = 32
TOKEN_ALPHABET = frozenset(string.ascii_letters + string.digits + '_-')

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
        state = state_mod.read_strict(path)
    except state_mod.StateUnreadable as exc:
        if exc.reason == 'missing':
            raise SystemExit(f'Router state file missing: {path}')
        if exc.reason == 'unreadable':
            raise SystemExit(
                f'Router state file could not be read: {path} ({exc.detail})')
        raise SystemExit(
            f'Router state file is not valid JSON: {path} ({exc.detail})')
    missing = state_mod.required_keys(state, REQUIRED_STATE)
    if missing:
        raise SystemExit('Router state file is missing or mistyped keys: ' + ', '.join(missing))
    token = state['token']
    if len(token) < TOKEN_MIN_LENGTH or not set(token) <= TOKEN_ALPHABET:
        raise SystemExit(
            'Router state token is too weak: it must be at least '
            f'{TOKEN_MIN_LENGTH} characters of [A-Za-z0-9_-]; '
            'reinstall to mint a new token.')
    if 'opencode_auth' in state and not isinstance(state['opencode_auth'], str):
        raise SystemExit('Router state file is missing or mistyped keys: opencode_auth')
    if 'openai_mode' in state and state['openai_mode'] not in ('subscription', 'none'):
        raise SystemExit('openai_mode must be subscription or none')
    if 'anthropic_mode' in state and state['anthropic_mode'] not in ('subscription', 'none'):
        raise SystemExit('anthropic_mode must be subscription or none')
    if 'openai_helper_fallback' in state and not isinstance(state['openai_helper_fallback'], bool):
        raise SystemExit('openai_helper_fallback must be true or false')
    if 'policy_enforced' in state and not isinstance(state['policy_enforced'], bool):
        raise SystemExit('policy_enforced must be true or false')
    if 'openrouter_region' in state and not provider_defs.valid_region(state['openrouter_region']):
        raise SystemExit("openrouter_region must be one of 'global', 'us' or 'eu'")
    # Every external provider the registry routes to needs its own key, but
    # the router boots as soon as one resolves: a provider without a key
    # fails its own requests closed instead of taking the service down. A
    # fresh unexpired setup nonce still lets it boot keyless so the
    # first-run window can collect one.
    external = sorted({m.provider for m in registry.MODELS
                       if provider_defs.is_external(m.provider)})
    credentials = Credentials(state, ROUTER_HOME)
    missing = [(pid, credentials.key_missing(pid)) for pid in external]
    missing = [(pid, exc) for pid, exc in missing if exc is not None]
    if external and len(missing) == len(external) and not setup_pending(state):
        detail = '; '.join(f'{provider_defs.label_for(pid)}: {exc}'
                           for pid, exc in missing)
        raise SystemExit(f'{provider_defs.label_for(missing[0][0])} '
                         f'credential problem: {detail}')
    # Plan 068: resolved portco allowlist rides alongside the roster. No
    # policy fetch may block startup: absent file means no policy (None) on a
    # personal install, while a managed one (`policy_enforced`) denies rather
    # than grants (Plan 176), and the loader fails closed to empty on
    # malformed input.
    from .model_policy import load as _load_policy
    home = path.parent if path != STATE else ROUTER_HOME
    _, _, allowed = _load_policy(home)
    if allowed is not None:
        state['allowed_models'] = list(allowed)
    return state
