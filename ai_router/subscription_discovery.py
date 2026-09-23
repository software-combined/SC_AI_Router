"""Fetch and serve Codex's native ChatGPT subscription model catalogue."""
import hashlib
import json
import time
import urllib.parse
import urllib.request

from . import availability, catalogue, errors, provider_defs, subscription_catalogue
from .transport import HOP_HEADERS

MAX_BYTES = 4 * 1024 * 1024
TIMEOUT_S = 4
STALE_S = 24 * 60 * 60


def _headers(source, router_token):
    forwarded = {}
    bearer = 'Bearer ' + router_token if router_token else None
    for key, value in source.items():
        name = key.lower()
        if name in HOP_HEADERS or (name == 'authorization' and value == bearer):
            continue
        forwarded[key] = value
    return forwarded


def fetch_native(headers, client_version='', router_token=None,
                 _urlopen=urllib.request.urlopen):
    """Fetch and validate one native catalogue response."""
    url = provider_defs.OPENAI.catalogue_url
    if client_version:
        url += '?' + urllib.parse.urlencode({'client_version': client_version})
    request = urllib.request.Request(url, headers=_headers(headers, router_token))
    with _urlopen(request, timeout=TIMEOUT_S) as response:
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError('subscription catalogue is too large')
    return subscription_catalogue.validate(json.loads(body))


def _identity(headers):
    auth = headers.get('Authorization') or headers.get('authorization') or ''
    return hashlib.sha256(auth.encode('utf-8')).hexdigest()[:16]


def _snapshot(server):
    return getattr(server, '_subscription_snapshot', None)


def _publish(server, rows, roster, identity):
    server._subscription_snapshot = {
        'rows': rows, 'roster': roster, 'identity': identity,
        'fetched_at': time.time(),
    }


def serve(handler, query=''):
    """Answer Codex's `/models` request with subscription plus external rows."""
    server = handler.server
    params = urllib.parse.parse_qs(query)
    client_version = (params.get('client_version') or [''])[0][:80]
    identity = _identity(handler.headers)
    snapshot = _snapshot(server)
    try:
        rows = fetch_native(handler.headers, client_version,
                            server.state.get('token'))
    except Exception:
        if (snapshot is None or snapshot.get('identity') != identity
                or time.time() - snapshot.get('fetched_at', 0) > STALE_S):
            return handler.error(errors.upstream_unavailable(
                'The model list is temporarily unavailable. Try again shortly.'))
        rows, roster = snapshot['rows'], snapshot['roster']
    else:
        roster = subscription_catalogue.effective_roster(
            server.state.get('openai_models', ()),
            [row['slug'] for row in rows])
        _publish(server, rows, roster, identity)
    server.state['openai_models'] = list(roster)
    snapshot = availability.current()
    merged = catalogue.merge(
        {'models': []}, roster=roster, subscription_rows=rows,
        allowed=server.state.get('allowed_models'),
        include_twins=server.state.get('openai_mode', 'subscription') == 'none',
        available=None if snapshot is None else snapshot.get('models'))
    return handler.send_json(200, {'models': merged['models']})
