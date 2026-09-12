"""Client-visible model set behind the new-model prompt (Plan 135).

Codex reads its catalogue once at startup, so a router update that adds
models needs an explicit restart offer. This module answers one question -
which models this client's picker would show right now - by resolving the
same projection and allowlist the catalogue merge uses, at view time.
Unlike the catalogue file, the answer is policy-filtered: an unverified or
out-of-policy row is never announced. The answer itself is not cached or
logged.
"""
from . import catalogue, model_policy


def visible_models(home, client='codex'):
    """[(slug, display_name)] the client's picker would show right now.

    ``allowed`` is resolved per call from ``model-policy.json``: an absent
    policy is unfiltered and a rejected one is the empty set. The running
    router gates requests on the allowlist it captured at startup, so a
    policy delivered while it runs is visible here before it is routable.
    Rows that are not listed (Plan 145) are never returned. Only the Codex
    projection is implemented; anything else fails closed.
    """
    if client != 'codex':
        raise ValueError(f'unsupported client: {client}')
    _, _, allowed = model_policy.load(home)
    visible, _hidden = catalogue._visible_rows(client, allowed)
    return [(model.slug, model.display_name) for model in visible]
