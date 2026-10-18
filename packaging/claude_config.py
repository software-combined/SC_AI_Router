"""Claude Code activation adapter (Plan 112). Python 3.9-safe helper.

Owns three public `env` settings merged into the user's settings.json, conflict
refusal on hand-edited owned values and on the tool-search hard switch, and
activation receipt handling. Loaded through the installer's explicit
file-import pattern and shipped in the release bundle. No runtime/protocol
import here.
"""
import json
import os
import subprocess
import time
import importlib.util as _ilu
from pathlib import Path

_spec = _ilu.spec_from_file_location(
    'router_runtime_atomic_write',
    Path(__file__).resolve().parents[1] / 'ai_router' / 'atomic_write.py')
atomic_write = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(atomic_write)
_spec = _ilu.spec_from_file_location('router_claude_removal', Path(__file__).with_name('client_removal.py'))
_removal = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_removal)

BASE_URL_KEY = 'ANTHROPIC_BASE_URL'
DISCOVERY_KEY = 'CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY'
# Public tool-search setting; never tell Claude this gateway is first-party.
TOOL_SEARCH_KEY = 'ENABLE_TOOL_SEARCH'
# Retained only to remove a receipt-proven legacy setting and restore old
# receipts on detach. It is never added to a new attachment.
FIRST_PARTY_KEY = '_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL'
# Not owned: this one is a hard off switch for the whole feature and no value
# can override it, so an attach refuses while it is set anywhere in reach.
DISABLE_KEY = 'CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS'
OWNED_KEYS = (BASE_URL_KEY, DISCOVERY_KEY, TOOL_SEARCH_KEY)
LEGACY_KEYS = (BASE_URL_KEY, DISCOVERY_KEY, FIRST_PARTY_KEY)


def settings_path(env=None):
    """User settings.json, honoring CLAUDE_CONFIG_DIR when set."""
    env = os.environ if env is None else env
    base = env.get('CLAUDE_CONFIG_DIR')
    if base:
        return Path(base).expanduser() / 'settings.json'
    return Path.home() / '.claude' / 'settings.json'


def desired_env(home, state):
    return {BASE_URL_KEY: 'http://127.0.0.1:%s/%s' % (state['port'], state['token']),
            DISCOVERY_KEY: 'true',
            TOOL_SEARCH_KEY: 'true'}


def _truthy(value):
    """Claude Code reads the switch as a string; empty and 0 mean unset."""
    return (isinstance(value, str)
            and value.strip().lower() not in ('', '0', 'false', 'no'))


def switch_sources(doc, env=None):
    """Where the tool-search hard switch is set, or an empty list.

    Claude Code forces tool search off whenever `CLAUDE_CODE_DISABLE_
    EXPERIMENTAL_BETAS` is truthy, and `ENABLE_TOOL_SEARCH` cannot override
    it, so a client attached while it is set would silently send every MCP
    tool on every turn.
    """
    sources = []
    block = doc.get('env') if isinstance(doc, dict) else None
    if isinstance(block, dict) and _truthy(block.get(DISABLE_KEY)):
        sources.append('the settings env block')
    env = os.environ if env is None else env
    if _truthy(env.get(DISABLE_KEY)):
        sources.append('the environment')
    return sources


def switch_sources_at(path, env=None):
    """switch_sources for one settings file; nothing readable reads as none."""
    try:
        doc = read_settings(path)
    except (OSError, ValueError, SystemExit, TypeError):
        # A receipt without a config_path reaches Path(None): the doctor must
        # report a row, never a traceback.
        return []
    return switch_sources(doc, env)


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


def merge_env(home, state, path=None, env=None, legacy_snapshot=None):
    """Merge public keys; migrate only a receipt-proven private flag.

    Returns (doc, changed, previous_owned) where previous_owned maps each
    owned key to its prior value (or None when absent) for the receipt.
    Conflicting effective overrides block activation with a redacted
    explanation: only values this installer wrote before may be replaced. A
    set tool-search hard switch blocks for the same reason and names its
    source.
    """
    path = Path(path) if path is not None else settings_path(env)
    doc = read_settings(path)
    owned = doc.get('env', {})
    if not isinstance(owned, dict):
        raise SystemExit('Claude settings env is not an object: %s' % path)
    blocked = switch_sources(doc, env)
    if blocked:
        raise SystemExit(
            'Claude setting %s is set by %s; it forces deferred tool loading '
            'off and no value overrides it. Remove it, then re-run.'
            % (DISABLE_KEY, ' and '.join(blocked)))
    doc['env'] = owned
    want = desired_env(home, state)
    previous = {key: owned.get(key) for key in OWNED_KEYS}
    legacy = owned.get(FIRST_PARTY_KEY)
    if legacy is not None and not (
            legacy == '1' and legacy_snapshot is not None
            and FIRST_PARTY_KEY in legacy_snapshot
            and legacy_snapshot[FIRST_PARTY_KEY] is None
            and previous[BASE_URL_KEY] == want[BASE_URL_KEY]):
        raise SystemExit('Claude setting env.%s is managed outside this installer; '
                         'review and remove it by hand, then re-run.' % FIRST_PARTY_KEY)
    effective = os.environ if env is None else env
    if _truthy(effective.get(FIRST_PARTY_KEY)):
        raise SystemExit('Claude setting %s is managed outside this installer in '
                         'the environment; remove it, then re-run.' % FIRST_PARTY_KEY)
    for key in OWNED_KEYS:
        if previous[key] is not None and previous[key] != want[key]:
            raise SystemExit(
                'Claude setting env.%s is managed outside this installer; '
                'remove or correct it by hand, then re-run.' % key)
    changed = legacy is not None or any(previous[key] != want[key] for key in OWNED_KEYS)
    owned.update(want)
    owned.pop(FIRST_PARTY_KEY, None)
    return doc, changed, previous


def write_settings(path, doc):
    """Atomically replace settings.json with owner-only permissions."""
    path = Path(path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.router.tmp')
    try:
        atomic_write.replace_json(path, doc, tmp_name=tmp.name)
    except atomic_write.StaleTmp:
        # A crash between create and replace leaves the deterministic tmp
        # behind; the writer clears it once and retries, and only a lost
        # race to the retry lands here.
        raise SystemExit('stale settings temp file: delete %s and re-run' % tmp)


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
    for key in OWNED_KEYS + ((FIRST_PARTY_KEY,) if FIRST_PARTY_KEY in previous else ()):
        old = previous.get(key)
        if old is None:
            env.pop(key, None)
        else:
            env[key] = old
    write_settings(path, doc)


def _listing_snapshot(listing):
    """The served rows the client was told about, or None when unknown.

    Stored inside the claude attachment entry (not a second receipt): the
    doctor compares it with the live GET /v1/models answer to report drift
    after a registry or client change.
    """
    rows = listing.get('data') if isinstance(listing, dict) else None
    if not isinstance(rows, list):
        return None
    models = [{'id': row['id'],
               'display_name': row.get('display_name', ''),
               'anthropic_family_tier': row.get('anthropic_family_tier')}
              for row in rows
              if isinstance(row, dict) and isinstance(row.get('id'), str)]
    return {'served_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'models': models}


def release_listing(release, python, runner):
    """The served Claude listing from an installed release, or None.

    Best-effort: a repair or an unusual home must never fail an attach over
    a diagnostic snapshot. The release's own python renders the same rows
    GET /v1/models serves, and the doctor compares them later.
    """
    if release is None or python is None:
        return None
    try:
        result = runner([python, '-m', 'ai_router.claude', '--listing'],
                        cwd=str(release), capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    try:
        doc = json.loads(result.stdout or '')
    except ValueError:
        return None
    return doc if isinstance(doc, dict) else None


def attach(home, state, receipts, settings_path_override=None, env=None,
           listing=None):
    """Attach Claude Code without touching Codex settings or native login.

    Merges three public keys and migrates an owned legacy flag; conflicts
    refuse with a redacted message. Records the claude attachment in the
    versioned receipt. Returns the settings path written.
    """
    if settings_path_override is not None:
        path = Path(settings_path_override)
    else:
        path = settings_path(env)
    path = path.expanduser().resolve()
    existing = receipts.read_receipt(home).get('clients', {}).get('claude', {})
    owned_path = existing.get('config_path') if isinstance(existing, dict) else None
    if existing and (not owned_path or os.path.normcase(str(Path(owned_path).resolve()))
                     != os.path.normcase(str(path))):
        raise SystemExit('Claude settings path changed; detach the existing Claude '
                         'attachment first, then connect the new profile.')
    snapshot = (_removal.saved_values(existing, OWNED_KEYS, LEGACY_KEYS)
                if isinstance(existing, dict) and owned_path
                and 'inserted_block' in existing else None)
    doc, changed, previous = merge_env(home, state, path, env, snapshot)
    write_settings(path, doc)
    if snapshot is not None and (not changed or
            previous[BASE_URL_KEY] == desired_env(home, state)[BASE_URL_KEY]):
        # Re-attach with identical values: keep the original pre-attach
        # snapshot so a later detach restores it instead of our own URL.
        previous = dict(previous, **snapshot)
    entry = {'config_path': str(path),
             'inserted_block': json.dumps(previous, sort_keys=True),
             'written': desired_env(home, state),
             'claude_mode': state.get('claude_mode', 'subscription')}
    snapshot = _listing_snapshot(listing)
    if snapshot is not None:
        entry['listing'] = snapshot
    elif isinstance(existing, dict) and 'listing' in existing:
        # A re-attach whose listing fetch failed must not erase the snapshot:
        # the doctor's drift signal would otherwise be lost until a manual
        # re-install that may fail the same way.
        entry['listing'] = existing['listing']
    receipts.write_client_receipt(home, 'claude', entry)
    return path


def detach(home, receipts, settings_path_override=None, env=None):
    """Only restore receipt-proven keys; path overrides grant no ownership."""
    del settings_path_override, env
    try:
        _removal.detach_json(home, 'claude', receipts)
    except _removal._json.Conflict as exc:
        raise SystemExit('Claude Code removal conflict: ' + str(exc)) from None


def refresh_snapshot(home, state, receipts, listing_source):
    """Best-effort snapshot refresh for an existing Claude attachment.

    Used by the installer's --setup repair on a current release, where a
    plain re-run returns "up to date" before the client stage. Both the
    receipt read and the attach are guarded: a corrupt receipt or a refused
    settings merge must never turn the repair into a traceback.
    """
    try:
        attached = receipts.read_receipt(home).get('clients', {}).get('claude')
    except (OSError, ValueError):
        return False
    if not attached:
        return False
    try:
        listing = listing_source()
    except (OSError, SystemExit):
        listing = None
    try:
        attach(home, state, receipts, listing=listing)
    except (OSError, SystemExit) as exc:
        print(f'Claude snapshot refresh skipped: {exc}')
        return False
    return True
