"""Explicit wire-protocol dispatch (Plan 062).

One small table maps method+path to a protocol policy. The HTTP handler
reads/auths a request, asks for the protocol, invokes it, and relays; it no
longer branches on client-specific provider tables. Each policy supplies its
provider selector plus the retry/header callbacks the relay path needs.

The path rows are built from their owners (Plan 125): `providers` owns the
native service paths and `claude` owns the Messages paths, so a path added
there is routable here without a second edit.
"""
from .. import claude, providers
from . import messages, responses

POST = 'POST'

TABLE = (
    # Responses family: Codex turns, compaction, native service paths.
    {'methods': (POST,), 'paths': frozenset({'/responses', '/responses/compact'}),
     'policy': responses.POLICY},
    {'methods': (POST,), 'paths': frozenset(providers.NATIVE_SERVICE_PATHS),
     'policy': responses.POLICY},
    # Messages family: Claude Code ingress.
    {'methods': (POST,), 'paths': claude.CLAUDE_POST_PATHS,
     'policy': messages.POLICY},
)


def owned_paths():
    """Every path any protocol row owns; the handler allowlist."""
    paths = set()
    for row in TABLE:
        paths |= row['paths']
    return frozenset(paths)


def select(method, path):
    """Protocol policy for this request, or None when no protocol owns it."""
    for row in TABLE:
        if method in row['methods'] and path in row['paths']:
            return row['policy']
    return None
