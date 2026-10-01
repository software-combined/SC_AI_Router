"""Fetch and serve Codex's native ChatGPT subscription model catalogue."""
import hashlib
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import availability, catalogue, errors, provider_defs, subscription_catalogue
from .key_store import _open_without_redirects
from .transport import HOP_HEADERS

MAX_BYTES = 4 * 1024 * 1024
TIMEOUT_S = 4
STALE_S = 24 * 60 * 60
MAX_SNAPSHOTS = 32
_LOCK = threading.RLock()
_GENERATIONS = {}
ROUTING_IDENTITY_HEADERS = frozenset({
    'chatgpt-account-id', 'chatgpt-workspace-id',
    'openai-organization', 'openai-project'})
IDENTITY_HEADERS = ROUTING_IDENTITY_HEADERS | {'authorization'}


def _headers(source, router_token):
    forwarded = {}
    bearer = 'Bearer ' + router_token if router_token else None
    for key, value in source.items():
        name = key.lower()
        if (name in HOP_HEADERS or name in ('content-length', 'content-encoding', 'content-type')
                or (name == 'authorization' and value == bearer)):
            continue
        forwarded[key] = value
    return forwarded


def fetch_native(headers, client_version='', router_token=None,
                 _urlopen=None):
    """Fetch and validate one native catalogue response."""
    if _urlopen is None:
        _urlopen = _open_without_redirects
    url = provider_defs.OPENAI.catalogue_url
    if client_version:
        url += '?' + urllib.parse.urlencode({'client_version': client_version})
    request = urllib.request.Request(url, headers=_headers(headers, router_token))
    with _urlopen(request, timeout=TIMEOUT_S) as response:
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError('subscription catalogue is too large')
    return subscription_catalogue.validate(json.loads(body))


def _identity(headers, client_version=''):
    values = {key.lower(): value for key, value in headers.items()
              if key.lower() in IDENTITY_HEADERS}
    values['client_version'] = client_version
    encoded = json.dumps(values, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:16]


def _routing_identity(headers):
    values = {key.lower(): value for key, value in headers.items()
              if key.lower() in ROUTING_IDENTITY_HEADERS}
    encoded = json.dumps(values, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:16]


def _auth_identity(headers):
    auth = headers.get('Authorization') or headers.get('authorization') or ''
    return hashlib.sha256(auth.encode('utf-8')).hexdigest()[:16] if auth else ''


def _client_version(query, headers=None):
    params = urllib.parse.parse_qs(query)
    return ((params.get('client_version') or [''])[0] or next(
        (value for key, value in (headers or {}).items() if key.lower() == 'version'), ''))[:80]


def _snapshots(server):
    with _LOCK:
        snapshots = getattr(server, '_subscription_snapshots', None)
        if snapshots is None:
            snapshots = {}
            server._subscription_snapshots = snapshots
        return snapshots


def _snapshot(server, identity):
    with _LOCK:
        return _snapshots(server).get(identity)


def _drop(server, identity):
    with _LOCK:
        _snapshots(server).pop(identity, None)


def _scope(headers):
    has_routing = any(key.lower() in ROUTING_IDENTITY_HEADERS for key in headers)
    return (('routing' if has_routing else 'auth'),
            (_routing_identity(headers) if has_routing else _auth_identity(headers)))


def _scope_generation(headers):
    scope = _scope(headers)
    with _LOCK:
        return scope, _GENERATIONS.get(scope, 0)


def _drop_scope(server, headers):
    scope = _scope(headers)
    with _LOCK:
        _GENERATIONS[scope] = _GENERATIONS.get(scope, 0) + 1
        snapshots = _snapshots(server)
        for key, entry in list(snapshots.items()):
            if entry.get(scope[0]) == scope[1]:
                snapshots.pop(key, None)


def _publish(server, rows, roster, identity, routing, auth, client_version,
             scope=None, generation=None):
    now = time.time()
    with _LOCK:
        if scope is not None and _GENERATIONS.get(scope, 0) != generation:
            return False
        snapshots = _snapshots(server)
        snapshots[identity] = {
            'rows': rows, 'roster': roster, 'identity': identity,
            'routing': routing, 'auth': auth, 'client_version': client_version,
            'fetched_at': now,
        }
        for key, entry in list(snapshots.items()):
            if now - entry.get('fetched_at', 0) > STALE_S:
                snapshots.pop(key, None)
        while len(snapshots) > MAX_SNAPSHOTS:
            snapshots.pop(min(snapshots, key=lambda key: snapshots[key].get('fetched_at', 0)))
        return True


def _fallback_snapshot(server, identity):
    with _LOCK:
        entry = _snapshots(server).get(identity)
        if (entry is None or entry.get('identity') != identity
                or time.time() - entry.get('fetched_at', 0) > STALE_S):
            return None
        return entry['rows'], tuple(entry['roster'])


def request_models(server, headers, query=''):
    """Live subscription membership for one request identity."""
    version = _client_version(query, headers)
    identity = _identity(headers, version)
    routing = _routing_identity(headers)
    auth = _auth_identity(headers)
    has_routing = any(key.lower() in ROUTING_IDENTITY_HEADERS for key in headers)
    now = time.time()
    with _LOCK:
        snapshots = _snapshots(server)
        candidates = []
        for entry in snapshots.values():
            if now - entry.get('fetched_at', 0) > STALE_S:
                continue
            if entry.get('identity') == identity:
                candidates = [entry]
                break
            if has_routing and entry.get('routing') == routing:
                candidates.append(entry)
            elif not has_routing and auth and entry.get('auth') == auth:
                candidates.append(entry)
        if version:
            candidates = [entry for entry in candidates
                          if entry.get('client_version') == version]
        elif len({entry.get('client_version') for entry in candidates}) > 1:
            candidates = []
        if not has_routing and len({entry.get('routing') for entry in candidates}) > 1:
            candidates = []
        if candidates:
            snapshot = max(candidates, key=lambda entry: entry.get('fetched_at', 0))
            return tuple(snapshot['roster'])
    preferences = server.state.get('openai_model_preferences')
    if preferences is None:
        preferences = server.state.get('openai_models', ())
    return subscription_catalogue.preferred_roster(preferences)


def serve(handler, query=''):
    """Answer Codex's `/models` request with subscription plus external rows."""
    server = handler.server
    client_version = _client_version(query)
    identity = _identity(handler.headers, client_version)
    scope, generation = _scope_generation(handler.headers)
    fresh = False
    preferences = None
    try:
        rows = fetch_native(handler.headers, client_version,
                            server.state.get('token'))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            _drop_scope(server, handler.headers)
            return handler.error(errors.subscription_auth_rejected())
        fallback = _fallback_snapshot(server, identity)
        if fallback is None:
            return handler.error(errors.upstream_unavailable(
                'The model list is temporarily unavailable. Try again shortly.'))
        rows, roster = fallback
    except Exception:
        fallback = _fallback_snapshot(server, identity)
        if fallback is None:
            return handler.error(errors.upstream_unavailable(
                'The model list is temporarily unavailable. Try again shortly.'))
        rows, roster = fallback
    else:
        fresh = True
        preferences = server.state.get('openai_model_preferences')
        if preferences is None:
            preferences = server.state.get('openai_models', ())
        roster = subscription_catalogue.effective_roster(
            preferences,
            [row['slug'] for row in rows])
    availability_snapshot = availability.current()
    try:
        merged = catalogue.merge(
            {'models': []}, roster=roster, subscription_rows=rows,
            allowed=server.state.get('allowed_models'),
            include_twins=server.state.get('openai_mode', 'subscription') == 'none',
            available=(None if availability_snapshot is None
                       else availability_snapshot.get('models')))
    except (AttributeError, KeyError, TypeError, ValueError):
        if not fresh:
            _drop(server, identity)
        return handler.error(errors.upstream_unavailable(
            'The model list is temporarily unavailable. Try again shortly.'))
    if fresh:
        if not _publish(server, rows, roster, identity,
                        _routing_identity(handler.headers),
                        _auth_identity(handler.headers), client_version,
                        scope=scope, generation=generation):
            return handler.error(errors.subscription_auth_rejected())
        server.state['openai_model_preferences'] = list(
            subscription_catalogue.preferred_roster(preferences))
    with _LOCK:
        if _GENERATIONS.get(scope, 0) != generation:
            return handler.error(errors.subscription_auth_rejected())
        server.state['openai_models'] = list(roster)
        return handler.send_json(200, {'models': merged['models']})
