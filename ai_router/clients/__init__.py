"""Client capability projections (Plan 064). One owner per client shape.

Each projection consumes a validated Model snapshot plus optional live
metadata and renders client-facing capability fields. Projections never
look up the model again through stale import-time maps, never touch
routing or credentials, and never import command modules.
"""
from . import registry as client_table


def visible_for(model, client, include_twins=False):
    """Picker visibility for one registry row; routing never consults this.

    The rule itself lives in the client table (`clients/registry.py`), which
    is the one owner of who sees what; this is the entry point every picker
    consumer calls. Unknown clients fail closed.
    """
    defn = client_table.get(client)
    if defn is None:
        raise ValueError(f'unknown client: {client}')
    return defn.picker_visible(model, include_twins=include_twins)


def models_for(rows, client, include_twins=False):
    """Rows visible in the given client's picker."""
    return tuple(m for m in rows
                 if visible_for(m, client, include_twins=include_twins))


def client_ids():
    """Supported client ids, in table order."""
    return client_table.client_ids()
