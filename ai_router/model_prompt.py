"""Client-visible model set behind the new-model prompt (Plan 135).

Codex reads its catalogue once at startup, so a router update that adds
models needs an explicit restart offer. This module answers two questions
about the same view-time projection: which models the client's picker would
show right now (`visible_models`), and which of those the user has not seen
yet (`pending`). Unlike the catalogue file, both answers are
policy-filtered: an unverified or out-of-policy row is never announced. The
answers are not cached; the seen set lives in the router home.
"""
import json
from pathlib import Path

from . import catalogue, model_policy
from .atomic_write import replace_json

SNAPSHOT_FILE = 'model-prompt.json'


def _client(client):
    """Only the Codex projection is implemented; anything else fails closed."""
    if client != 'codex':
        raise ValueError(f'unsupported client: {client}')
    return client


def _scope(home):
    """(scope key, allowed) for the current policy; broken links are rejected."""
    try:
        portco, department, allowed = model_policy.load(home)
    except OSError:  # vanished between read and stat: reject, never widen
        return 'none', ()
    if allowed is None and (Path(home) / model_policy.POLICY_FILE).is_symlink():
        # A dangling link reads as "no policy"; a policy that cannot be
        # resolved must never widen the announced set.
        return 'none', ()
    if portco is None:
        return 'none', allowed
    return f'{portco}/{department or "-"}', allowed


def _visible(client, allowed):
    visible, _hidden = catalogue._visible_rows(client, allowed)
    return [(model.slug, model.display_name) for model in visible]


def visible_models(home, client='codex'):
    """[(slug, display_name)] the client's picker would show right now.

    ``allowed`` is resolved per call from ``model-policy.json``: an absent
    policy is unfiltered and a rejected or unresolvable one is the empty
    set. The running router gates requests on the allowlist it captured at
    startup, so a policy delivered while it runs is visible here before it
    is routable. Rows that are not listed (Plan 145) are never returned.
    """
    _scope_key, allowed = _scope(home)
    return _visible(_client(client), allowed)


def _read_seen(home, scope, client):
    """Seen slugs recorded for this scope and client, or None when unusable."""
    try:
        doc = json.loads((Path(home) / SNAPSHOT_FILE).read_text())
    except (OSError, ValueError):
        return None
    if (not isinstance(doc, dict) or doc.get('scope') != scope
            or doc.get('client') != client):
        return None
    seen = doc.get('seen')
    if not isinstance(seen, list) or any(not isinstance(s, str) for s in seen):
        return None
    return seen


def _remember(home, scope, client, seen):
    """Best-effort snapshot write: an unwritable home announces nothing."""
    try:
        replace_json(Path(home) / SNAPSHOT_FILE,
                     {'scope': scope, 'client': client, 'seen': list(seen)})
    except OSError:
        pass


def _rejected(scope, allowed):
    """True for a policy that is present but could not be resolved.

    A valid policy that allows no models keeps its real scope key and seeds
    like any other scope, so a later grant still announces; only the absent
    or rejected cases share the ``'none'`` key with an empty allowlist.
    """
    return scope == 'none' and allowed == ()


def _in_policy(seen, allowed):
    """Drop seen slugs the current allowlist no longer covers."""
    allowset = None if allowed is None else frozenset(allowed)
    return [slug for slug in seen if allowset is None or slug in allowset]


def pending(home, client='codex'):
    """[(slug, display_name)] visible now that the snapshot has not seen.

    The first call for a scope seeds the snapshot with everything visible
    and returns []; a scope change re-seeds the same way. A rejected or
    unresolvable policy returns [] and writes nothing.
    """
    client = _client(client)
    scope, allowed = _scope(home)
    if _rejected(scope, allowed):
        return []
    visible = _visible(client, allowed)
    seen = _read_seen(home, scope, client)
    if seen is None:
        _remember(home, scope, client, [slug for slug, _ in visible])
        return []
    known = set(seen)
    return [(slug, name) for slug, name in visible if slug not in known]


def acknowledge(home, client='codex'):
    """Record the displayed pending rows as seen and return them.

    The union is taken with the pending set, never with everything visible,
    so a model added later still announces. Seen slugs outside the current
    allowlist are dropped rather than carried forward.
    """
    client = _client(client)
    scope, allowed = _scope(home)
    if _rejected(scope, allowed):
        return []
    shown = pending(home, client)
    seen = _read_seen(home, scope, client) or []
    union = list(dict.fromkeys(
        _in_policy(seen, allowed) + [slug for slug, _ in shown]))
    _remember(home, scope, client, union)
    return shown
