"""Recover native membership when an existing chat outlives its router cache."""
import threading
import urllib.error

from . import errors, subscription_catalogue, subscription_roster
from . import subscription_discovery as discovery

_LOCK = threading.Lock()


def request_models(handler, model, path, catalogue):
    """Discover an unregistered native model once for this request identity."""
    server, headers = handler.server, dict(handler.headers)
    query = handler.path.partition('?')[2]
    roster = discovery.request_models(server, headers, query)
    if (server.state.get('openai_mode', 'subscription') == 'none'
            or path not in ('/responses', '/responses/compact')
            or model in roster or model in subscription_roster.HELPER_SLUGS
            or catalogue.get(model) is not None
            or not any(key.lower() in discovery.IDENTITY_HEADERS for key in headers)):
        return roster
    # Concurrent resumptions reuse one discovery result, including an empty list.
    with _LOCK:
        version = discovery._client_version(query, headers)
        identity = discovery._identity(headers, version)
        roster = discovery.request_models(server, headers, query)
        if model in roster or discovery._fallback_snapshot(server, identity) is not None:
            return roster
        scope, generation = discovery._scope_generation(headers)
        try:
            rows = discovery.fetch_native(headers, version, server.state.get('token'))
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                discovery._drop_scope(server, headers)
                raise errors.subscription_auth_rejected() from None
            raise errors.upstream_unavailable(
                'The model list is temporarily unavailable. Try again shortly.') from None
        except Exception:
            raise errors.upstream_unavailable(
                'The model list is temporarily unavailable. Try again shortly.') from None
        preferences = server.state.get('openai_model_preferences',
                                       server.state.get('openai_models', ()))
        roster = subscription_catalogue.effective_roster(
            preferences, [row['slug'] for row in rows])
        if not discovery._publish(server, rows, roster, identity,
                                  discovery._routing_identity(headers),
                                  discovery._auth_identity(headers), version,
                                  scope=scope, generation=generation):
            raise errors.subscription_auth_rejected()
        return roster
