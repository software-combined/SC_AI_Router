"""Explicit wire-protocol dispatch (Plan 062).

One small table maps method+path to a protocol policy. The HTTP handler
reads/auths a request, asks for the protocol, invokes it, and relays; it no
longer branches on client-specific provider tables. Each policy supplies its
provider selector plus the retry/header callbacks the relay path needs.

The path rows are built from their owners (Plan 125): `providers` owns the
native service paths and `claude` owns the Messages paths, so a path added
there is routable here without a second edit.
"""
from .. import claude, image_provider, provider_defs, providers
from . import images, messages, responses

POST = 'POST'
GET = 'GET'

TABLE = (
    {'methods': (POST,), 'paths': image_provider.IMAGE_POST_PATHS,
     'policy': images.POLICY},
    # Responses family: Codex turns, compaction, native service paths.
    {'methods': (POST,), 'paths': frozenset({'/responses', '/responses/compact'}),
     'policy': responses.POLICY},
    {'methods': (POST,), 'paths': frozenset(providers.NATIVE_SERVICE_PATHS),
     'native': provider_defs.native_service_path,
     'policy': responses.POLICY},
    # Messages family: Claude Code ingress.
    {'methods': (POST,), 'paths': claude.CLAUDE_POST_PATHS,
     'policy': messages.POLICY},
    # Claude discovery: the Messages family's Anthropic-shaped listing. One
    # row owns the path, so the handler asks the table instead of carrying a
    # second branch (Plan 155, F10).
    {'methods': (GET,), 'paths': frozenset({'/v1/models'}),
     'policy': messages.POLICY},
    {'methods': (GET,), 'paths': frozenset({'/models'}),
     'policy': responses.POLICY},
)


def owned_paths():
    """Every path any protocol row owns, for either method."""
    paths = set()
    for row in TABLE:
        paths |= row['paths']
    return frozenset(paths)


def listing(method, path, allowed=None):
    """Discovery payload for a GET row this table owns, else None.

    The owning policy supplies the shape; the allowlist rides along so a
    managed install's listing cannot announce a model its routing refuses.
    """
    policy = select(method, path)
    if policy is None or policy.listing is None:
        return None
    return policy.listing(allowed)


def select(method, path):
    """Protocol policy for this request, or None when no protocol owns it."""
    for row in TABLE:
        if method in row['methods'] and path in row['paths']:
            return row['policy']
    for row in TABLE:
        native = row.get('native')
        if method in row['methods'] and native is not None and native(path):
            return row['policy']
    return None


def route(policy, model, path, state, mode, payload, headers, turns, native_models):
    """Resolve once; the Images policy also checks the originating chat turn."""
    context = policy.resolve(model)
    if policy is images.POLICY:
        return policy.origin_route(model, path, state, mode, payload, headers, turns, context)
    provider = policy.select_provider(model, path, state, mode,
        catalogue=context.catalogue, headers=headers, openai_models=native_models(context))
    return context, provider
