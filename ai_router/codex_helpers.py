"""Codex's metadata helper IDs, separate from the person's chat model.

The desktop asks for bare Luna IDs. An external-only catalogue needs hidden
aliases or the client can silently fall back to its first ordinary model.
Aliases are routing hints, never exemptions from key or company policy.
"""
import json

from . import subscription_roster

ROUTE_HEADER = 'x-scg-codex-route'
HELPER_SOURCES = frozenset({'thread_title', 'thread_description',
                            'thread_summary', 'thread_title_reconsideration'})
METADATA_HEADER = 'x-codex-turn-metadata'
MAX_METADATA_BYTES = 8192
LUNA_TWIN = 'openai/gpt-6-luna'
ALIASES = subscription_roster.HELPER_SLUGS | {
    LUNA_TWIN.removeprefix(subscription_roster.TWIN_PREFIX)}


def switched(headers):
    return any(key.lower() == ROUTE_HEADER for key in headers)


def helper_turn(headers):
    """Only a bounded, known helper source qualifies; prompt text never does."""
    raw = next((v for k, v in headers.items() if k.lower() == METADATA_HEADER), None)
    if not isinstance(raw, str) or len(raw) > MAX_METADATA_BYTES:
        return False
    try:
        meta = json.loads(raw)
    except ValueError:
        return False
    source = meta.get('thread_source') if isinstance(meta, dict) else None
    return isinstance(source, str) and source in HELPER_SOURCES


def routed_slug(model, path, headers, mode):
    """External-only helpers use Luna; ordinary and subscription turns keep their ID."""
    if (path == '/responses' and (mode == 'none' or switched(headers))
            and helper_turn(headers)):
        return LUNA_TWIN
    return model


def aliases(models):
    """Hidden client IDs only when the filtered catalogue already admits Luna."""
    luna = next((row for row in models if row.get('slug') == LUNA_TWIN), None)
    return ([dict(luna, slug=slug, visibility='hide') for slug in sorted(ALIASES)]
            if luna is not None else [])


def served_slug(row):
    """The real model behind an owned hidden alias, for readiness checks."""
    slug = row.get('slug')
    if slug in ALIASES:
        return LUNA_TWIN if row.get('visibility') == 'hide' else None
    return slug
