"""Client capability projections (Plan 064). One owner per client shape.

Each projection consumes a validated Model snapshot plus optional live
metadata and renders client-facing capability fields. Projections never
look up the model again through stale import-time maps, never touch
routing or credentials, and never import command modules.
"""


def visible_for(model, client):
    """Picker visibility for one registry row; routing never consults this.

    Codex hides OpenRouter-billed GPT rows, Claude hides OpenRouter-billed
    Anthropic rows; subscription rows are never hidden. Tilde aliases
    normalize before the prefix check. Unknown clients fail closed.
    """
    try:
        hidden = {'codex': 'openai/', 'claude': 'anthropic/'}[client]
    except KeyError:
        raise ValueError(f'unknown client: {client}') from None
    if model.provider != 'openrouter':
        return True
    return not model.slug.removeprefix('~').startswith(hidden)


def models_for(rows, client):
    """Rows visible in the given client's picker."""
    return tuple(m for m in rows if visible_for(m, client))
