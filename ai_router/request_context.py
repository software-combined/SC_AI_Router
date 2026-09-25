"""One immutable resolution snapshot per request (Plan 188 slice 1).

`model_refresh.apply` swaps the registry and the capability maps while
requests are in flight. A request therefore reads the live registry once,
here, and every later decision (owner, upstream id, tool and history
quirks, effort, images, output cap, compaction budget, the helper-fallback
twin) takes its row from this snapshot instead of a module global. The
next request captures the new generation.

A native id no registry row describes resolves with `row=None` and keeps
its own spelling; the native adapters forward it unchanged.
"""
import copy
import types
import uuid
from dataclasses import dataclass, replace
from typing import Any, Mapping

from . import registry


def capture():
    """One registry generation, as a read-only slug -> row mapping.

    Rows are frozen and shared, except that `provider_prefs` is a mutable
    dict with nested lists and dicts: a row that carries one, even `{}`, gets
    its own copy.
    """
    return types.MappingProxyType({
        slug: replace(row, provider_prefs=copy.deepcopy(row.provider_prefs))
        if row.provider_prefs is not None else row
        for slug, row in registry.BY_SLUG.items()})


@dataclass(frozen=True)
class Resolved:
    request_id: str  # one logical id for request_started and its final record
    slug: Any  # the resolved slug, or the client's own value when unresolved
    row: Any  # the slug's row in `catalogue`, or None
    catalogue: Mapping  # the generation every consumer of this request reads


def resolve(requested, catalogue, slug=None):
    """Bind one request to `catalogue`; `slug` overrides an aliased id."""
    slug = requested if slug is None else slug
    row = catalogue.get(slug) if isinstance(slug, str) else None
    return Resolved(uuid.uuid4().hex, slug, row, catalogue)


def retarget(context, slug):
    """The same request, pinned to another row of its own generation."""
    return replace(context, slug=slug, row=context.catalogue[slug])
