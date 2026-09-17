"""The client table: one row per supported client (Plan 155).

A client is not a provider and an OS is neither. A row names the wire
protocol the router already serves, the predicate its picker applies, and the
predicate its own discovery listing applies. Both Claude projections read
here, so "what does Claude Code see" has one owner.

Leaf beside `provider_defs` in the dependency map: it imports the provider
table and the id roster, and nothing else.
"""
from .. import provider_defs
from .roster import CLIENT_IDS


class ClientDef:
    """One supported client: protocol, picker visibility, discovery visibility.

    `picker_visible(model, include_twins=False)` answers the catalogue
    question ("may this row appear in the client's picker"). The discovery
    predicate answers the listing's own question, and the listing applies its
    key filter on top -- that separation is why the two can differ.
    """

    __slots__ = ('id', 'label', 'protocol', 'picker_visible', 'discovery_visible')

    def __init__(self, id, label, protocol, picker_visible, discovery_visible):
        self.id, self.label, self.protocol = id, label, protocol
        self.picker_visible, self.discovery_visible = picker_visible, discovery_visible


def _listed(model, include_twins=False):
    """A surface that shows every listed row, whoever bills it."""
    return bool(model.listed)


def _listed_outside_anthropic(model, include_twins=False):
    """Claude's picker: externally billed Anthropic rows stay out.

    A Claude Code user picks the subscription or the external provider;
    listing the same model twice, once per billing route, is what this
    avoids. Tilde aliases normalize before the prefix check.
    """
    if not model.listed:
        return False
    if not provider_defs.is_external(model.provider) or include_twins:
        return True
    return not model.slug.removeprefix('~').startswith('anthropic/')


CODEX = ClientDef(id='codex', label='Codex',
                  protocol=provider_defs.RESPONSES,
                  picker_visible=_listed, discovery_visible=_listed)
CLAUDE = ClientDef(id='claude', label='Claude Code',
                   protocol=provider_defs.MESSAGES,
                   picker_visible=_listed_outside_anthropic,
                   discovery_visible=_listed)

CLIENTS = (CODEX, CLAUDE)
BY_ID = {client.id: client for client in CLIENTS}

if tuple(client.id for client in CLIENTS) != CLIENT_IDS:
    raise ValueError('client table and roster disagree')


def get(client):
    """ClientDef for an id, or None when it is unknown."""
    return BY_ID.get(client) if isinstance(client, str) else None


def client_ids():
    """Supported client ids, in table order."""
    return tuple(client.id for client in CLIENTS)
