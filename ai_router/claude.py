"""Anthropic Messages ingress for Claude Code. Same billing split, no translation.

Claude Code points ANTHROPIC_BASE_URL at the loopback router with the path
token in the URL, as the Codex base URL does. Requests arrive and leave in
Anthropic Messages format: an external provider listed in provider_defs with
a messages prefix serves a faithful Anthropic-compatible endpoint, so those
requests need only a host swap and a key swap while the body travels
byte-identical, which keeps thinking blocks, tool_use IDs and cache_control
exactly as the client sent them. Registry slugs owned by such a provider
take that route; every other model passes through to the subscription
upstream with the client's own credentials, mirroring SubscriptionProvider:
the router key never accompanies those requests and client credentials are
never stored or logged.
"""
import json
import sys

from . import claude_compat, messages_events, outbound, provider_defs, request_context, transport
from .errors import ClaudeSubscriptionRequired, PreparationError, UnknownModel
from . import registry
from .clients import registry as client_table
from .registry import by_slug, upstream_id_for

# POST-only Messages paths; a future GET-only route (like /v1/models) must
# not silently become POST-routable.
CLAUDE_POST_PATHS = frozenset({'/v1/messages', '/v1/messages/count_tokens'})
CLAUDE_ALIAS_PREFIX = 'claude/'


def claude_alias(slug):
    """Discovery id for one registry slug; None when it must not list."""
    return row_alias(by_slug(slug) if isinstance(slug, str) else None)


def row_alias(entry):
    """Discovery id for one registry row; None when it must not list."""
    defn = provider_defs.get(entry.provider) if entry is not None else None
    if defn is None or not defn.serves(provider_defs.MESSAGES):
        return None
    slug = entry.slug
    bare = slug.removeprefix('~')
    # Clients may filter models they do not support. Discovery never disguises
    # another vendor's model as Claude to circumvent those client filters.
    return bare


# Tier words the desktop accepts in anthropic_family_tier (client 1.49585.0).
FAMILY_TIERS = frozenset({'sonnet', 'opus', 'haiku', 'fable', 'mythos'})


def family_tier(alias):
    """Actual Claude family tier, or None for another vendor."""
    if isinstance(alias, str) and alias.startswith('anthropic/claude-'):
        word = alias.removeprefix('anthropic/claude-').split('-', 1)[0]
        if word in FAMILY_TIERS:
            return word
    return None


def models_listing(allowed=None):
    """Anthropic-style {data: [{id, display_name, anthropic_family_tier}]}.

    Verified rows first A-Z by display name, then preview rows A-Z.
    External rows outside the key-filtered snapshot hide, matching the
    picker, the prompt and request routing; subscription rows list on.
    A portco allowlist (Plan 068) hides external rows it does not name, so
    a managed install without a policy announces nothing external.
    """
    from . import availability as _availability
    snap = _availability.current()
    avail = None if snap is None else (snap.get('models') or frozenset())
    allowset = None if allowed is None else frozenset(allowed)
    defn = client_table.get('claude')
    ordered = sorted(registry.MODELS, key=lambda m: (m.tier != 'verified',
                                            m.display_name.casefold()))
    rows = []
    for entry in ordered:
        if not defn.discovery_visible(entry):
            continue
        if (allowset is not None
                and provider_defs.is_external(entry.provider)
                and entry.slug not in allowset):
            continue
        if (avail is not None
                and provider_defs.is_external(entry.provider)
                and entry.slug not in avail):
            continue
        alias = claude_alias(entry.slug)
        if alias is not None:
            row = {'id': alias, 'display_name': entry.display_name}
            tier = family_tier(alias)
            if tier is not None:
                row['anthropic_family_tier'] = tier
            rows.append(row)
    return {'data': rows}


USAGE = 'usage: python3.14 -m ai_router.claude --listing'


if __name__ == '__main__':
    if sys.argv[1:] != ['--listing']:
        raise SystemExit(USAGE)
    print(json.dumps(models_listing(), sort_keys=True))


def resolve(model, catalogue=None):
    """Registry slug for a discovery id or direct slug; model untouched if unknown."""
    rows = request_context.capture() if catalogue is None else catalogue
    slug = model
    if isinstance(slug, str) and slug in rows:
        return slug
    if isinstance(model, str) and '~' + model in rows:
        return '~' + model  # truthful discovery IDs retain tracking-row membership
    return model


class ExternalMessagesProvider:
    """One external provider serving Anthropic Messages (Plan 141)."""

    def __init__(self, defn, region='global'):
        self.defn = defn
        self.name = defn.id
        self.region = region if provider_defs.valid_region(region) else 'global'
        self.host = provider_defs.region_host(defn.id, self.region) or defn.host
        self.kind = defn.kind

    def prepare(self, model, path, payload, raw_body, headers, credentials, decoded_len=None,
                context=None):
        if path not in CLAUDE_POST_PATHS:
            raise PreparationError('Claude ingress serves messages only')
        body = raw_body
        if context is None:  # a direct call; routed requests resolved at ingress
            context = request_context.resolve(model, request_context.capture(), resolve(model))
        slug, entry = context.slug, context.row
        if getattr(entry, 'media_kind', None) is not None:
            raise PreparationError('Media generation models require the Codex Responses route')
        upstream = upstream_id_for(entry) if entry is not None else slug
        projected = outbound.project_messages_external(payload, model, upstream)
        # Unchanged bodies keep client serialization. Encoded external input
        # leaves decoded because these fresh headers omit Content-Encoding.
        if projected is not payload or transport.encoded(headers):
            body = json.dumps(projected).encode()
        return transport.Prepared(
            self.host, self.defn.path_for(provider_defs.MESSAGES, path),
            {'Authorization': 'Bearer ' + credentials.key_for(self.defn.id),
             'Content-Type': 'application/json',
             'Accept-Encoding': 'identity'},
            body, set(), self.name, context=context, decoded_body_bytes=len(body))

    def adapt(self, response, tool_names, notes=None):
        chunks = transport.passthrough(response)
        kind, encoding = transport.describe_response(response)
        if kind == 'sse':
            chunks = claude_compat.shape(chunks)
        elif kind == 'json' and encoding == 'identity':
            chunks = [claude_compat.shape_json(
                transport.read_capped(response, transport.MAX_UPSTREAM_BODY))]
        yield from chunks

    def events(self, response, notes):
        return messages_events.external_events(
            claude_compat.shaped_frames(transport.passthrough(response)), notes)


class ClaudeSubscriptionProvider:
    """The client's own Claude login; the router holds no credential."""

    def __init__(self):
        self.defn = provider_defs.ANTHROPIC
        self.name = self.defn.id
        self.host = self.defn.host
        self.kind = self.defn.kind

    def prepare(self, model, path, payload, raw_body, headers, credentials, decoded_len=None,
                context=None):
        auth = headers.get('Authorization', '')
        if not (auth.startswith('Bearer ') or 'x-api-key' in headers):
            raise PermissionError('Claude subscription authentication required')
        fwd = {k: v for k, v in headers.items() if k.lower() not in transport.HOP_HEADERS}
        projected = outbound.project_messages_subscription(payload)
        body = raw_body if projected is payload else json.dumps(projected).encode()
        return transport.Prepared(self.host, path, fwd, body, set(), self.name,
                                  context=context, decoded_body_bytes=decoded_len)

    def adapt(self, response, tool_names, notes=None):
        yield from transport.passthrough(response)


def select(model, path, openai_mode='subscription', anthropic_mode=None,
           region='global', allowed=None, catalogue=None):
    rows = request_context.capture() if catalogue is None else catalogue
    slug = resolve(model, rows)
    if isinstance(model, str) and model.startswith(CLAUDE_ALIAS_PREFIX):
        raise UnknownModel(model, ())
    entry = rows.get(slug) if isinstance(model, str) else None
    defn = provider_defs.get(entry.provider) if entry is not None else None
    if defn is not None and defn.kind == provider_defs.EXTERNAL:
        if not defn.serves(provider_defs.MESSAGES):
            raise PreparationError(
                f'{defn.label} models are available to Codex only: '
                'this model does not serve the Anthropic Messages API')
        # Plan 068: a portco allowlist gates routing, never just the picker.
        # None means no policy provisioned (today's behavior). Aliases and
        # bare Anthropic ids resolve to the registry slug before the check.
        if allowed is not None and slug not in frozenset(allowed):
            raise UnknownModel(slug, ())
        # Key-filtered availability gates routing like the picker: with no
        # successful snapshot the key shows no approved external models.
        from . import availability as _availability
        if not _availability.permitted(slug):
            raise UnknownModel(slug, ())
        return ExternalMessagesProvider(defn, region)
    # Independent subscription choice; missing mode reproduces the legacy
    # behavior of following openai_mode. Never widened by migration.
    if (anthropic_mode if anthropic_mode is not None else openai_mode) == 'none':
        raise ClaudeSubscriptionRequired()
    return ClaudeSubscriptionProvider()
