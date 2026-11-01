"""Client-visible model set behind the new-model prompt (Plan 135).

Codex reads its catalogue once at startup, so a router update that adds
models needs an explicit restart offer. This module answers two questions
about the same view-time projection: which models the client's picker would
show right now (`visible_models`), and which of those the user has not seen
yet (`pending`). `notice` mints the single-use link the approval page and
its POST carry. Unlike the catalogue file, the answers are policy-filtered:
an unverified or out-of-policy row is never announced. The answers are not
cached; the seen set and the notice live in the router home.
"""
import hmac
import json
import secrets
import time
from pathlib import Path

from . import catalogue, model_policy
from .atomic_write import replace_json

SNAPSHOT_FILE = 'model-prompt.json'
NOTICE_TTL_S = 48 * 60 * 60


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


def _visible(client, allowed, available=None):
    visible, _hidden = catalogue._visible_rows(client, allowed,
                                               available=available)
    # The picker label, not the stored display name: the `· OpenRouter`
    # suffix belongs to the picker's own route column, and an approval
    # page or dialog that repeats it reads as noise.
    return [(model.slug, catalogue.catalog_name(model)) for model in visible]


def _available(home):
    # Key-filtered id set, or None before the first `/models/user`
    # success. Routing and the prompt share this read so the announced
    # set never widens the routable set.
    from . import availability as _availability
    return _availability.effective_ids(
        home, _availability.current_key(home), _availability.current_region(home))


def visible_models(home, client='codex'):
    """[(slug, label)] the client's picker would show right now.

    ``allowed`` is resolved per call from ``model-policy.json``: an absent
    policy is unfiltered and a rejected or unresolvable one is the empty
    set. The running router gates requests on the allowlist it captured at
    startup, so a policy delivered while it runs is visible here before it
    is routable. Rows that are not listed (Plan 145) are never returned.
    The label is the picker's own (`<Vendor>: <Model> <Version?>`), so the
    dialog, the approval page and the picker name a model the same way.
    """
    _scope_key, allowed = _scope(home)
    return _visible(_client(client), allowed, _available(home))


def _read_doc(home, scope, client):
    """Snapshot document for this scope and client, or None when unusable."""
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
    return doc


def _read_seen(home, scope, client):
    doc = _read_doc(home, scope, client)
    return None if doc is None else list(doc['seen'])


def _notice_of(doc):
    """(nonce, expires) from a snapshot document; (None, None) when unusable."""
    notice = doc.get('notice') if isinstance(doc, dict) else None
    if not isinstance(notice, dict):
        return None, None
    nonce, expires = notice.get('nonce'), notice.get('expires')
    if not isinstance(nonce, str) or not nonce:
        return None, None
    if not isinstance(expires, (int, float)) or isinstance(expires, bool):
        return None, None
    return nonce, float(expires)


def _remember(home, scope, client, seen, notice=None):
    """Snapshot write; False when the home is unwritable."""
    doc = {'scope': scope, 'client': client, 'seen': list(seen)}
    if notice is not None:
        doc['notice'] = notice
    try:
        replace_json(Path(home) / SNAPSHOT_FILE, doc)
    except OSError:
        return False
    return True


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
    """[(slug, label)] visible now that the snapshot has not seen.

    The first call for a scope seeds the snapshot with everything visible
    and returns []; a scope change re-seeds the same way. A rejected or
    unresolvable policy returns [] and writes nothing.
    """
    client = _client(client)
    scope, allowed = _scope(home)
    if _rejected(scope, allowed):
        return []
    visible = _visible(client, allowed, _available(home))
    seen = _read_seen(home, scope, client)
    if seen is None:
        _remember(home, scope, client, [slug for slug, _ in visible])
        return []
    known = set(seen)
    return [(slug, name) for slug, name in visible if slug not in known]


def notice(home, client='codex', now=None):
    """(nonce, rows) for an approval page, minting a single-use nonce.

    Returns (None, []) when nothing is pending or the policy is rejected.
    An unexpired nonce is reused so a second trigger does not invalidate a
    page the user already has open.
    """
    client = _client(client)
    scope, allowed = _scope(home)
    if _rejected(scope, allowed):
        return None, []
    rows = pending(home, client)
    if not rows:
        return None, []
    now = time.time() if now is None else now
    doc = _read_doc(home, scope, client)
    nonce, expires = _notice_of(doc)
    if not nonce or expires <= now:
        minted = secrets.token_urlsafe(32)
        seen = [] if doc is None else list(doc['seen'])
        if not _remember(home, scope, client, seen,
                         notice={'nonce': minted,
                                 'expires': now + NOTICE_TTL_S}):
            return None, []
        nonce = minted
    return nonce, rows


def check_notice(home, client, nonce, now=None):
    """Pending rows for a valid unexpired nonce, or None when it is invalid."""
    client = _client(client)
    scope, allowed = _scope(home)
    if _rejected(scope, allowed):
        return None
    expected, expires = _notice_of(_read_doc(home, scope, client))
    now = time.time() if now is None else now
    if (not expected or not isinstance(nonce, str) or not nonce
            or expires is None or expires <= now
            or not hmac.compare_digest(expected.encode('utf-8'),
                                       nonce.encode('utf-8'))):
        return None
    return pending(home, client)


def acknowledge(home, client='codex', displayed=None):
    """Record the displayed rows as seen and return them.

    The union is taken with ``displayed`` when the page supplies it and with
    the recomputed pending set otherwise, never with everything visible, so
    a model added later still announces. Seen slugs outside the current
    allowlist are dropped rather than carried forward. The notice is
    dropped, so a link is single-use.
    """
    client = _client(client)
    scope, allowed = _scope(home)
    if _rejected(scope, allowed):
        return []
    visible = _visible(client, allowed, _available(home))
    if displayed is None:
        shown = pending(home, client)  # seeds an unseen scope and returns []
    else:
        names = dict(visible)
        shown = [(slug, names[slug]) for slug in displayed if slug in names]
    seen = _read_seen(home, scope, client) or []
    union = list(dict.fromkeys(
        _in_policy(seen, allowed) + [slug for slug, _ in shown]))
    _remember(home, scope, client, union)
    return shown
