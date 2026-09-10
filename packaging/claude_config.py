"""Claude Code activation adapter (Plan 049). Python 3.9-safe helper.

Owns the two owned `env` settings merged into the user's settings.json,
conflict refusal on hand-edited owned values, and activation receipt
handling. Loaded through the installer's explicit file-import pattern
and shipped in the release bundle. No runtime/protocol import here.
"""
import json
import os
from pathlib import Path

BASE_URL_KEY = 'ANTHROPIC_BASE_URL'
DISCOVERY_KEY = 'CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY'
OWNED_KEYS = (BASE_URL_KEY, DISCOVERY_KEY)


def settings_path(env=None):
    """User settings.json, honoring CLAUDE_CONFIG_DIR when set."""
    env = os.environ if env is None else env
    base = env.get('CLAUDE_CONFIG_DIR')
    if base:
        return Path(base).expanduser() / 'settings.json'
    return Path.home() / '.claude' / 'settings.json'


def desired_env(home, state):
    return {BASE_URL_KEY: 'http://127.0.0.1:%s/%s' % (state['port'], state['token']),
            DISCOVERY_KEY: 'true'}


def read_settings(path):
    path = Path(path)
    if not path.exists():
        return {}
    try:
        doc = json.loads(path.read_text())
    except ValueError:
        raise SystemExit('Claude settings are not valid JSON: %s' % path)
    if not isinstance(doc, dict):
        raise SystemExit('Claude settings are not a JSON object: %s' % path)
    return doc


def merge_env(home, state, path=None, env=None):
    """Merge the two owned env keys; refuse conflicting hand-edited values.

    Returns (doc, changed, previous_owned) where previous_owned maps each
    owned key to its prior value (or None when absent) for the receipt.
    Conflicting effective overrides block activation with a redacted
    explanation: only values this installer wrote before may be replaced.
    """
    path = Path(path) if path is not None else settings_path(env)
    doc = read_settings(path)
    owned = doc.get('env', {})
    if not isinstance(owned, dict):
        raise SystemExit('Claude settings env is not an object: %s' % path)
    doc['env'] = owned
    want = desired_env(home, state)
    previous = {key: owned.get(key) for key in OWNED_KEYS}
    for key in OWNED_KEYS:
        if previous[key] is not None and previous[key] != want[key]:
            raise SystemExit(
                'Claude setting env.%s is managed outside this installer; '
                'remove or correct it by hand, then re-run.' % key)
    changed = any(previous[key] != want[key] for key in OWNED_KEYS)
    owned.update(want)
    return doc, changed, previous


def write_settings(path, doc):
    """Atomically replace settings.json with owner-only permissions."""
    path = Path(path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.router.tmp')
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        # A crash between create and replace leaves the deterministic tmp
        # behind; unlink and retry once rather than blocking activation.
        try:
            tmp.unlink()
        except OSError:
            raise SystemExit('stale settings temp file: delete %s and re-run' % tmp)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(json.dumps(doc, indent=2) + '\n')
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def restore_settings(path, previous):
    """Restore owned keys to their pre-attach values; drop those added."""
    path = Path(path)
    doc = read_settings(path)
    env = doc.get('env')
    if not isinstance(env, dict):
        # Detach must converge even when the user removed the env block by
        # hand: treat it as empty so owned keys vanish and the claim drops.
        env = {}
        doc['env'] = env
    for key in OWNED_KEYS:
        old = previous.get(key)
        if old is None:
            env.pop(key, None)
        else:
            env[key] = old
    write_settings(path, doc)


def attach(home, state, receipts, settings_path_override=None, env=None):
    """Attach Claude Code without touching Codex settings or native login.

    Merges only the two owned env keys; conflicting effective overrides
    refuse with a redacted message. Records the claude attachment in the
    versioned receipt. Returns the settings path written.
    """
    if settings_path_override is not None:
        path = Path(settings_path_override)
    else:
        path = settings_path(env)
    doc, changed, previous = merge_env(home, state, path, env)
    write_settings(path, doc)
    existing = receipts.read_receipt(home).get('clients', {}).get('claude', {})
    if not changed and isinstance(existing, dict) and 'inserted_block' in existing:
        # Re-attach with identical values: keep the original pre-attach
        # snapshot so a later detach restores it instead of our own URL.
        previous = receipts.parse_snapshot(existing['inserted_block'])
    entry = {'config_path': str(path),
             'inserted_block': json.dumps(previous, sort_keys=True),
             'claude_mode': state.get('claude_mode', 'subscription')}
    receipts.write_client_receipt(home, 'claude', entry)
    return path


def detach(home, receipts, settings_path_override=None, env=None):
    """Restore Claude settings to pre-attach values; forget the attachment."""
    receipt = receipts.read_receipt(home)
    entry = receipt.get('clients', {}).get('claude', {})
    if settings_path_override is None and env is None and not entry:
        return  # never attached: never touch hand-managed settings
    if settings_path_override is not None:
        path = Path(settings_path_override)
    elif isinstance(entry, dict) and entry.get('config_path'):
        path = Path(entry['config_path'])
    else:
        path = settings_path(env)
    previous = receipts.parse_snapshot(entry.get('inserted_block', '{}'))
    restore_settings(path, previous)
    receipts.drop_client(home, 'claude')
