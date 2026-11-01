"""Codex capability projection (Plan 064). One owner for Codex fields.

Consumed by catalogue merge (new/merged entries) and the legacy apply path
(live refreshes). The same snapshot through either path yields identical
capability fields. Pinned exclusions, default reasoning, schema quirks,
tier, and probe-gated flags are preserved, never promoted.
"""
from ..capabilities import (advertised_or_pinned, catalogue_patch,
                            checked_level_entries)


def capability_fields(model, live=None, default=None):
    """Codex capability fields for one validated Model snapshot.

    `live` is the optional live metadata entry for the same slug; when
    absent, pinned snapshot values stand. `default` overrides the snapshot
    default reasoning level; the apply path passes the catalogue row's own
    default so existing rows keep their operative value. Returns the patch
    dict applied onto catalogue rows by both merge and apply paths.
    """
    slug = model.slug
    patch = catalogue_patch(slug)
    advertised = advertised_or_pinned(
        slug, ((live or {}).get('reasoning') or {}).get('supported_efforts'))
    patch['supported_reasoning_levels'] = checked_level_entries(
        slug, advertised, model.default_reasoning if default is None else default)
    arch = ((live or {}).get('architecture') or {})
    if 'input_modalities' in arch:
        mods = arch['input_modalities']
        patch['input_modalities'] = [m for m in model.modalities if m in mods]
    else:
        patch['input_modalities'] = list(model.modalities)
    return patch
