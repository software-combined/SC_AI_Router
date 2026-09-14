"""Per-key external-model availability behind `/models/user` (Plan 145).

The shared registry stays authoritative for approved rows; this module
tracks which of those rows the installed key may currently use. A
snapshot is one validated `/models/user` id set plus the key and region
it was fetched with:

- fetched with the ordinary inference key, never a management key;
- one snapshot per (key fingerprint, region profile);
- retained across temporary failures for the same key and region;
- cleared on authentication rejection, never reused across credentials;
- request routing is fail-open before the first snapshot lands (a fresh
  key may route briefly); the picker merge path hides rows until then.

Snapshots never add rows: visibility is approved roster intersect
available ids intersect local policy intersect client rules. Malformed
payloads fail closed and keep the last good snapshot. The registry is
never pruned from availability data; unavailable rows simply hide.
"""
import hashlib
import json
import logging
import threading
import time
import urllib.error
import urllib.request

from . import snapshot_store

LOG = logging.getLogger('codex_router')
REFRESH_INTERVAL_S = 300

_LOCK = threading.Lock()
_SNAPSHOT = None


def key_fingerprint(key):
    """Stable non-secret identity for one credential value."""
    return hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]


def validate(payload):
    """Id set from one `/models/user` document; ValueError when malformed."""
    if not isinstance(payload, dict):
        raise ValueError('availability payload must be an object')
    rows = payload.get('data')
    if not isinstance(rows, list):
        raise ValueError('availability payload needs a data list')
    ids = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str):
            raise ValueError('availability row needs a string id')
        slug = row['id'].strip()
        if slug:
            ids.add(slug)
    return frozenset(ids)


def fetch(host, key, _urlopen=urllib.request.urlopen):
    """(status, document, auth_rejected) for one `/models/user` call."""
    req = urllib.request.Request(
        'https://' + host + '/api/v1/models/user',
        headers={'Authorization': 'Bearer ' + key})
    try:
        with _urlopen(req, timeout=30) as response:
            return response.status, json.load(response), False
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return exc.code, None, True
        raise


def current():
    """In-memory snapshot, or None when never refreshed in this process."""
    with _LOCK:
        return dict(_SNAPSHOT) if _SNAPSHOT is not None else None


def permitted(slug, snapshot=None):
    """True when one slug survives the snapshot gate (None: no gate yet)."""
    if snapshot is None:
        snapshot = current()
    return snapshot is None or slug in (snapshot.get('models') or frozenset())


def refresh(host, key, home, region='global', _urlopen=urllib.request.urlopen):
    """One availability pass for this key and region; never raises.

    Returns the in-memory snapshot (or None). Temporary failures keep the
    last good snapshot for the same key and region; an authentication
    rejection clears it. A snapshot fetched for another key or region is
    never served: it is replaced only by a fresh success for this pair.
    """
    global _SNAPSHOT
    fingerprint = key_fingerprint(key)
    try:
        _status, doc, rejected = fetch(host, key, _urlopen)
    except Exception as exc:  # noqa: BLE001 - any fetch failure keeps current
        LOG.info(json.dumps({'event': 'models_availability_failed',
                             'reason': exc.__class__.__name__}))
        # A rotated key must never ride the old key's snapshot through a
        # transient failure: drop a snapshot fetched for another key and
        # serve nothing until this key succeeds. Same-key retention stays.
        with _LOCK:
            if _SNAPSHOT is not None and _SNAPSHOT.get('key') != fingerprint:
                _SNAPSHOT = None
                snapshot_store.clear(home)
        return current()
    if rejected:
        with _LOCK:
            _SNAPSHOT = None
        snapshot_store.clear(home)
        LOG.info(json.dumps({'event': 'models_availability_cleared',
                             'reason': 'auth_rejected'}))
        return None
    try:
        ids = validate(doc)
    except (ValueError, AttributeError) as exc:
        LOG.info(json.dumps({'event': 'models_availability_failed',
                             'reason': exc.__class__.__name__}))
        return current()
    snap = {'key': fingerprint, 'region': region, 'models': ids,
            'fetched_at': time.time()}
    with _LOCK:
        _SNAPSHOT = dict(snap)
    snapshot_store.write(home, fingerprint, region, ids)
    return dict(snap)


def restore(home, key, region='global'):
    """Serve the persisted snapshot only for this key and region.

    Returns the snapshot, or None when absent, malformed, or fetched for
    another credential or region. Called at startup so a restart keeps the
    last good visibility until the first live refresh lands.
    """
    global _SNAPSHOT
    fingerprint = key_fingerprint(key)
    doc = snapshot_store.read(home)
    if (doc is None or doc.get('key') != fingerprint
            or doc.get('region') != region):
        return None
    snap = {'key': fingerprint, 'region': region,
            'models': frozenset(doc['models']), 'fetched_at': doc['fetched_at']}
    with _LOCK:
        _SNAPSHOT = dict(snap)
    return dict(snap)


def effective_ids(home, key=None, region='global'):
    # Id set the prompt and catalogue merges announce: the live snapshot
    # when present, else the persisted one only for the same key/region.
    snap = current()
    if snap is not None:
        return snap.get('models')
    persisted = snapshot_store.read(home)
    if persisted is None or key is None:
        return None
    if (persisted.get('key') == key_fingerprint(key)
            and persisted.get('region') == region):
        return persisted.get('models')
    return None


def current_key(home):
    # Local imports: callers already import this module, so the
    # credential helpers resolve lazily like the rest of the tree.
    from . import credentials, state as state_mod
    # Installed inference key, or None while keyless/unreadable.
    state = state_mod.read(state_mod.path(home))
    if state is None:
        return None
    try:
        return credentials.Credentials(state, home).key_for()
    except (LookupError, PermissionError, ValueError, OSError):
        return None


def current_region(home):
    from . import provider_defs, state as state_mod
    # Region profile for one home; unknown names fail back to global.
    state = state_mod.read(state_mod.path(home))
    region = state.get('openrouter_region') if state is not None else None
    return region if provider_defs.valid_region(region) else 'global'


def start(host_fn, key_fn, home, region_fn=None, _urlopen=urllib.request.urlopen):
    """Refresh every five minutes in a daemon thread; None when keyless.

    `host_fn` names the regional host used for inference, `key_fn`
    resolves the installed inference key (None while keyless), and
    `region_fn` names the region profile (default `global`). A key or
    region change refreshes at once; the loop then polls on the cadence.
    No network in tests: fetch is injectable through `_urlopen`.
    """
    try:
        key = key_fn()
    except (LookupError, PermissionError, ValueError, OSError):
        return None
    if not key:
        return None
    host = host_fn()
    region = region_fn() if region_fn is not None else 'global'
    restore(home, key, region)

    def loop():
        last_key, last_region = key_fingerprint(key), region
        while True:
            time.sleep(REFRESH_INTERVAL_S)
            try:
                live_key = key_fn()
            except (LookupError, PermissionError, ValueError, OSError):
                continue
            if not live_key:
                continue
            live_host, live_region = host_fn(), (
                region_fn() if region_fn is not None else 'global')
            if (key_fingerprint(live_key) != last_key
                    or live_region != last_region):
                last_key, last_region = key_fingerprint(live_key), live_region
                refresh(live_host, live_key, home, live_region, _urlopen)
                continue
            refresh(live_host, live_key, home, live_region, _urlopen)

    thread = threading.Thread(target=loop, daemon=True, name='model-availability')
    thread.start()
    return thread
