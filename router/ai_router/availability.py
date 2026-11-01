"""Per-provider, per-key external-model availability (Plan 145).

The shared registry stays authoritative for approved rows; this module
tracks which of those rows each installed provider key may currently use.
A snapshot is one validated model-list id set plus the provider, key and
region it was fetched with:

- fetched with the provider's ordinary inference key, never a management key;
- one snapshot per (provider, key fingerprint, region value);
- retained across temporary failures for the same provider and key;
- cleared on authentication rejection, never reused across credentials;
- request routing is fail-open before a provider's first snapshot lands
  (a fresh key may route briefly); the picker merge path hides rows of a
  keyed provider until that provider's snapshot lands.

Live list ids are upstream ids: they map to registry slugs through the
rows owned by that provider, so availability never adds rows. Visibility
is approved roster intersect available ids intersect local policy
intersect client rules. Malformed payloads fail closed and keep the last
good snapshot. The registry is never pruned from availability data;
unavailable rows simply hide.
"""
import hashlib
import json
import logging
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import provider_defs, registry, routed_models, snapshot_store

LOG = logging.getLogger('codex_router')
REFRESH_INTERVAL_S = 300

_LOCK = threading.Lock()
_SNAPSHOTS = {}
# Providers that have held a snapshot in this process. Once one has, a
# cleared snapshot means "show nothing of that provider", not "no gate".
_HAD_SNAPSHOT = set()


def key_fingerprint(key):
    """Stable non-secret identity for one credential value."""
    return hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]


def validate(payload):
    """Upstream-id set from one model-list document; ValueError when malformed."""
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


def _slugs_for(provider_id, upstream_ids):
    """Registry slugs one provider's live upstream ids name.

    Availability never adds rows: an id with no row owned by that
    provider is ignored, and a row is named by its upstream id,
    falling back to its slug.
    """
    wanted = set(upstream_ids)
    return frozenset(row.slug for row in registry.MODELS
                     if row.provider == provider_id
                     and registry.upstream_id_for(row) in wanted)


def fetch(provider_id, host, key, _urlopen=urllib.request.urlopen):
    """(status, document, auth_rejected) for one provider's model-list call.

    The request target comes from the provider definition, so no caller
    outside it names an availability path. A provider with no list path
    is never fetched.
    """
    defn = provider_defs.get(provider_id)
    if defn is None or not defn.availability_path or not host:
        raise ValueError('provider has no availability list')
    req = urllib.request.Request(
        'https://' + host + defn.availability_path,
        headers={'Authorization': 'Bearer ' + key})
    try:
        with _urlopen(req, timeout=30) as response:
            return response.status, json.load(response), False
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return exc.code, None, True
        raise


def current(provider_id=None):
    """In-memory snapshot for one provider, or None; default external provider when omitted."""
    provider_id = provider_id or provider_defs.DEFAULT_EXTERNAL
    with _LOCK:
        snap = _SNAPSHOTS.get(provider_id)
        return dict(snap) if snap is not None else None


def permitted(slug, snapshot=None, provider_id=None):
    """True when one slug survives its provider's snapshot gate.

    With no provider argument the row is resolved from the registry, so
    existing single-provider callers keep their meaning. None snapshot
    for that provider means no gate yet.
    """
    if snapshot is not None:
        return slug in (snapshot.get('models') or frozenset())
    if provider_id is None:
        row = registry.by_slug(slug)
        provider_id = row.provider if row is not None else provider_defs.DEFAULT_EXTERNAL
    snap = current(provider_id)
    return snap is None or slug in (snap.get('models') or frozenset())


def combined_ids():
    """Combined picker gate across external providers, or None.

    None only when no provider with registry rows has a snapshot yet.
    Once any keyed provider has spoken, every provider with rows must
    have a snapshot for its rows to show: a cleared or never-fetched
    provider contributes nothing, so its rows hide. Routing still gates
    each provider on its own snapshot alone.
    """
    with _LOCK:
        snaps = {pid: dict(s) for pid, s in _SNAPSHOTS.items()}
        had_any = bool(_HAD_SNAPSHOT)
    rowed = {row.provider for row in registry.MODELS
             if provider_defs.is_external(row.provider)}
    if not had_any and not any(pid in snaps for pid in rowed):
        return None
    ids = set()
    for snap in snaps.values():
        ids |= (snap.get('models') or frozenset())
    return frozenset(ids)


def refresh(provider_id, host, key, home, region='global', _urlopen=urllib.request.urlopen):
    """One availability pass for one provider; never raises.

    Returns that provider's snapshot (or None). Temporary failures keep
    the last good snapshot for the same provider and key; an
    authentication rejection clears only this provider. A snapshot
    fetched for another key or region is never served for this pair.
    """
    fingerprint = key_fingerprint(key)
    try:
        _status, doc, rejected = fetch(provider_id, host, key, _urlopen)
    except Exception as exc:  # noqa: BLE001 - any fetch failure keeps current
        LOG.info(json.dumps({'event': 'models_availability_failed',
                             'provider': provider_id,
                             'reason': exc.__class__.__name__}))
        # A rotated key must never ride the old key's snapshot through a
        # transient failure: drop a snapshot fetched for another key and
        # serve nothing until this key succeeds. Same-key retention stays.
        # The store write and catalogue sync run outside _LOCK: both can
        # call back into this module's readers.
        dropped = False
        with _LOCK:
            snap = _SNAPSHOTS.get(provider_id)
            if snap is not None and snap.get('key') != fingerprint:
                _SNAPSHOTS.pop(provider_id, None)
                _HAD_SNAPSHOT.add(provider_id)
                dropped = True
        if dropped:
            snapshot_store.clear(home, provider_id)
            sync_catalogue(home)
        return current(provider_id)
    if rejected:
        with _LOCK:
            _SNAPSHOTS.pop(provider_id, None)
            # A rejected key has spoken: its rows hide, they do not
            # return to the ungated "no snapshot yet" behaviour.
            _HAD_SNAPSHOT.add(provider_id)
        snapshot_store.clear(home, provider_id)
        sync_catalogue(home)
        LOG.info(json.dumps({'event': 'models_availability_cleared',
                             'provider': provider_id, 'reason': 'auth_rejected'}))
        return None
    try:
        ids = _slugs_for(provider_id, validate(doc))
    except (ValueError, AttributeError) as exc:
        LOG.info(json.dumps({'event': 'models_availability_failed',
                             'provider': provider_id,
                             'reason': exc.__class__.__name__}))
        return current(provider_id)
    snap = {'provider': provider_id, 'key': fingerprint, 'region': region,
            'models': ids, 'fetched_at': time.time()}
    with _LOCK:
        _SNAPSHOTS[provider_id] = dict(snap)
        _HAD_SNAPSHOT.add(provider_id)
    snapshot_store.write(home, provider_id, fingerprint, region, ids)
    sync_catalogue(home)
    return dict(snap)


def sync_catalogue(home):
    """Re-merge the picker catalogues against the combined provider gate.

    The combined set is the union of provider snapshots; None preserves
    today's files. Never raises: a catalogue write failure must not
    break a refresh loop.
    """
    try:
        from . import catalogue as _catalogue
        from . import model_policy as _policy
        available = combined_ids()
        _portco, _department, _allowed = _policy.load(home)
        _catalogue.merge_file(Path(home) / 'mixed-models.json',
                              allowed=_allowed, available=available)
        routed_models.sync(home, available, _allowed)  # Switch Codex's picker file
    except Exception:  # noqa: BLE001 - picker sync must never break refresh
        LOG.info(json.dumps({'event': 'models_catalogue_sync_failed'}))


def restore(home, provider_id, key, region='global'):
    """Serve the persisted snapshot only for this provider, key and region.

    Returns the snapshot, or None when absent, malformed, or fetched for
    another credential or region. Called at startup so a restart keeps
    the last good visibility until the first live refresh lands.
    """
    fingerprint = key_fingerprint(key)
    doc = snapshot_store.read(home, provider_id)
    if (doc is None or doc.get('key') != fingerprint
            or doc.get('region') != region):
        return None
    snap = {'provider': provider_id, 'key': fingerprint, 'region': region,
            'models': frozenset(doc['models']), 'fetched_at': doc['fetched_at']}
    with _LOCK:
        _SNAPSHOTS[provider_id] = dict(snap)
        _HAD_SNAPSHOT.add(provider_id)
    return dict(snap)


def effective_ids(home, key=None, region='global', provider_id=None):
    # Id set the prompt, Switch Codex readiness and catalogue merges
    # announce. Scoped to one provider when named; otherwise the union
    # across providers, each read live-first then persisted for the
    # installed key. None only when no provider can answer yet.
    if provider_id is None:
        # The caller supplied one key/region pair; it belongs to the
        # default provider. Other providers add their own persisted set
        # only when their key resolves from this home's credentials.
        sets = []
        scoped = effective_ids(home, key, region,
                               provider_defs.DEFAULT_EXTERNAL)
        if scoped is not None:
            sets.append(scoped)
        for defn in provider_defs.external_defs():
            if defn.id == provider_defs.DEFAULT_EXTERNAL:
                continue
            if not any(r.provider == defn.id for r in registry.MODELS):
                continue
            other_key = current_key(home, defn.id)
            if other_key is None:
                continue
            other_region = (current_bedrock_region(home)
                            if defn.regional else current_region(home))
            ids = effective_ids(home, other_key, other_region, defn.id)
            if ids is not None:
                sets.append(ids)
        if not sets:
            return None
        merged = set()
        for ids in sets:
            merged |= ids
        return frozenset(merged)
    snap = current(provider_id)
    if snap is not None:
        return snap.get('models')
    # A provider that held a snapshot in this process and lost it has
    # spoken only for this process: its live gate is empty here, while
    # another process still reads the persisted snapshot below.
    with _LOCK:
        had = provider_id in _HAD_SNAPSHOT
    if had and snapshot_store.read(home, provider_id) is None:
        return frozenset()
    persisted = snapshot_store.read(home, provider_id)
    if persisted is None or key is None:
        return None
    if (persisted.get('key') == key_fingerprint(key)
            and persisted.get('region') == region):
        return persisted.get('models')
    return None


def current_key(home, provider_id=None):
    # Local imports: callers already import this module, so the
    # credential helpers resolve lazily like the rest of the tree.
    from . import credentials, state as state_mod
    # Installed inference key for one provider, or None while keyless.
    state = state_mod.read(state_mod.path(home))
    if state is None:
        return None
    try:
        return credentials.Credentials(state, home).key_for(
            provider_id or provider_defs.DEFAULT_EXTERNAL)
    except (LookupError, PermissionError, ValueError, OSError):
        return None


def current_region(home):
    from . import provider_defs, state as state_mod
    # OpenRouter region profile for one home; unknown names fail to global.
    state = state_mod.read(state_mod.path(home))
    region = state.get('openrouter_region') if state is not None else None
    return region if provider_defs.valid_region(region) else 'global'


def current_bedrock_region(home):
    from . import state as state_mod
    # AWS region for one home; invalid or absent means the default.
    state = state_mod.read(state_mod.path(home))
    region = state.get('bedrock_region') if state is not None else None
    return region if provider_defs.valid_bedrock_region(region) else 'us-east-1'


def start(provider_id, host_fn, key_fn, home, region_fn=None, _urlopen=urllib.request.urlopen):
    """Refresh one provider every five minutes in a daemon thread.

    `host_fn` names the regional host used for inference, `key_fn`
    resolves that provider's installed key (None while keyless), and
    `region_fn` names its region value (default `global`). The loop polls
    for keys and region changes, including a first key saved after startup.
    No network in tests: fetch is injectable through `_urlopen`.
    """
    try:
        key = key_fn()
    except (LookupError, PermissionError, ValueError, OSError):
        key = None
    if key and host_fn():
        region = region_fn() if region_fn is not None else 'global'
        restore(home, provider_id, key, region)

    def loop():
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
            if not live_host:
                continue
            refresh(provider_id, live_host, live_key, home, live_region, _urlopen)

    thread = threading.Thread(target=loop, daemon=True,
                              name='model-availability-' + provider_id)
    thread.start()
    return thread
