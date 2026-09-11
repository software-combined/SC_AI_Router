"""Client capability projections (Plan 064). One owner per client shape.

Each projection consumes a validated Model snapshot plus optional live
metadata and renders client-facing capability fields. Projections never
look up the model again through stale import-time maps, never touch
routing or credentials, and never import command modules.
"""


def visible_for(model, client, include_twins=False):
    """Picker visibility for one registry row; routing never consults this.

    Claude hides OpenRouter-billed Anthropic rows; the Codex picker lists
    the OpenRouter-billed GPT twins beside the subscription rows, so an
    exhausted ChatGPT allowance still leaves those models selectable on
    the OpenRouter key. Subscription rows are never hidden. Tilde aliases
    normalize before the prefix check. Unknown clients fail closed.
    "Twins" are a client's OpenRouter-billed subscription-vendor rows;
    with include_twins the hidden ones stay visible.
    """
    if client not in ('codex', 'claude'):
        raise ValueError(f'unknown client: {client}')
    if model.provider != 'openrouter' or include_twins or client == 'codex':
        return True
    return not model.slug.removeprefix('~').startswith('anthropic/')


def models_for(rows, client, include_twins=False):
    """Rows visible in the given client's picker."""
    return tuple(m for m in rows
                 if visible_for(m, client, include_twins=include_twins))
