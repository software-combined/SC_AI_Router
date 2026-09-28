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
import hashlib
import json
import sys

from . import claude_compat, outbound, provider_defs, request_context, transport
from .errors import ClaudeSubscriptionRequired, PreparationError, UnknownModel
from . import registry
from .clients import registry as client_table
from .registry import by_slug, upstream_id_for

# POST-only Messages paths; a future GET-only route (like /v1/models) must
# not silently become POST-routable.
CLAUDE_POST_PATHS = frozenset({'/v1/messages', '/v1/messages/count_tokens'})
CLAUDE_ALIAS_PREFIX = 'claude/'
CLAUDE_ROUTE_PREFIX = 'claude/scg/'


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
    if bare.startswith('anthropic/'):
        return bare  # already passes the client filter
    # Desktop 2.2553.1 rejects vendor words in IDs even with a family tier.
    # Keep the actual vendor/model/billing name in display_name, not the ID.
    return CLAUDE_ROUTE_PREFIX + hashlib.sha256(slug.encode()).hexdigest()


def unalias(model, catalogue=None):
    """Strip the discovery prefix back to the registry slug, tilde restored.

    `catalogue` is the request's captured generation (request_context);
    None reads the live registry once, for callers outside a request."""
    if not isinstance(model, str) or not model.startswith(CLAUDE_ALIAS_PREFIX):
        return model
    rows = request_context.capture() if catalogue is None else catalogue
    if model.startswith(CLAUDE_ROUTE_PREFIX):
        return next((entry.slug for entry in rows.values()
                     if row_alias(entry) == model), model)
    # Older discovery IDs remain valid for saved sessions and CLI commands.
    rest = model[len(CLAUDE_ALIAS_PREFIX):]
    for candidate in (rest, '~' + rest):
        if candidate in rows:
            return candidate
    return model  # unknown: leave untouched for subscription passthrough


# Tier words the desktop accepts in anthropic_family_tier (client 1.49585.0).
FAMILY_TIERS = frozenset({'sonnet', 'opus', 'haiku', 'fable', 'mythos'})
FAMILY_TIER_DEFAULT = 'sonnet'


def family_tier(alias):
    """Tier word one discovery id stands in for; sonnet unless it names one."""
    if isinstance(alias, str) and alias.startswith('anthropic/claude-'):
        word = alias.removeprefix('anthropic/claude-').split('-', 1)[0]
        if word in FAMILY_TIERS:
            return word
    return FAMILY_TIER_DEFAULT


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
            rows.append({'id': alias, 'display_name': entry.display_name,
                         'anthropic_family_tier': family_tier(alias)})
    return {'data': rows}


USAGE = 'usage: python3.14 -m ai_router.claude --listing'


if __name__ == '__main__':
    if sys.argv[1:] != ['--listing']:
        raise SystemExit(USAGE)
    print(json.dumps(models_listing(), sort_keys=True))


def resolve(model, catalogue=None):
    """Registry slug for a discovery id or direct slug; model untouched if unknown."""
    rows = request_context.capture() if catalogue is None else catalogue
    slug = unalias(model, rows)
    if isinstance(slug, str) and slug in rows:
        return slug
    if isinstance(model, str) and model.startswith('anthropic/') and '~' + model in rows:
        return '~' + model  # bare Anthropic id lists without its tilde
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
    if isinstance(model, str) and model.startswith(CLAUDE_ROUTE_PREFIX) and slug == model:
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
