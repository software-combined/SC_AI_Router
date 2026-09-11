"""Anthropic Messages ingress for Claude Code. Same billing split, no translation.

Claude Code points ANTHROPIC_BASE_URL at the loopback router with the path
token in the URL, as the Codex base URL does. Requests arrive and leave in
Anthropic Messages format: OpenRouter serves a faithful Anthropic-compatible
endpoint, so OpenRouter-bound requests need only a host swap and a key swap
while the body travels byte-identical, which keeps thinking blocks,
tool_use IDs and cache_control exactly as the client sent them. Registry
slugs owned by OpenRouter take that route; every other model passes through
to api.anthropic.com with the client's own credentials, mirroring
SubscriptionProvider: the router key never accompanies those requests and
client credentials are never stored or logged.
"""
import json

from . import providers, transport
from .capabilities import OPENROUTER_HOST
from .errors import PreparationError, UnknownModel
from . import registry
from .registry import by_slug

ANTHROPIC_HOST = 'api.anthropic.com'
ANTHROPIC_PREFIX = '/api'
# GET and POST share the Messages paths today; the names differ so a future
# GET-only route (like /v1/models) cannot silently become POST-routable.
CLAUDE_PATHS = frozenset({'/v1/messages', '/v1/messages/count_tokens'})
CLAUDE_POST_PATHS = frozenset({'/v1/messages', '/v1/messages/count_tokens'})
CLAUDE_ALIAS_PREFIX = 'claude/'


def claude_alias(slug):
    """Discovery id for one registry slug; None when it must not list."""
    entry = by_slug(slug) if isinstance(slug, str) else None
    if entry is None or entry.provider != 'openrouter':
        return None
    bare = slug.removeprefix('~')
    if bare.startswith('anthropic/'):
        return bare  # already passes the client filter
    return CLAUDE_ALIAS_PREFIX + bare


def unalias(model):
    """Strip the discovery prefix back to the registry slug, tilde restored."""
    if not isinstance(model, str) or not model.startswith(CLAUDE_ALIAS_PREFIX):
        return model
    rest = model[len(CLAUDE_ALIAS_PREFIX):]
    for candidate in (rest, '~' + rest):
        if by_slug(candidate) is not None:
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


def models_listing():
    """Anthropic-style {data: [{id, display_name, anthropic_family_tier}]}.

    Verified rows first A-Z by display name, then preview rows A-Z."""
    ordered = sorted(registry.MODELS, key=lambda m: (m.tier != 'verified',
                                            m.display_name.casefold()))
    rows = []
    for entry in ordered:
        alias = claude_alias(entry.slug)
        if alias is not None:
            rows.append({'id': alias, 'display_name': entry.display_name,
                         'anthropic_family_tier': family_tier(alias)})
    return {'data': rows}


def resolve(model):
    """Registry slug for a discovery id or direct slug; model untouched if unknown."""
    slug = unalias(model)
    if isinstance(slug, str) and by_slug(slug) is not None:
        return slug
    if (
        isinstance(model, str)
        and model.startswith('anthropic/')
        and by_slug('~' + model) is not None
    ):
        return '~' + model  # bare Anthropic id lists without its tilde
    return model


def _is_openrouter_slug(model):
    entry = by_slug(resolve(model)) if isinstance(model, str) else None
    return entry is not None and entry.provider == 'openrouter'


class ClaudeOpenRouterProvider:
    name = 'openrouter-claude'

    def prepare(self, model, path, payload, raw_body, headers, credentials):
        if path not in CLAUDE_POST_PATHS:
            raise PreparationError('Claude ingress serves messages only')
        body = raw_body
        slug = resolve(model)
        # resolve() only returns a different string for a known registry slug.
        # payload is the parsed form of this same body, so rewrite the alias
        # there instead of decoding raw_body again.
        if isinstance(model, str) and slug != model and isinstance(payload, dict):
            payload['model'] = slug
            body = json.dumps(payload).encode()
        return transport.Prepared(
            OPENROUTER_HOST, ANTHROPIC_PREFIX + path,
            {'Authorization': 'Bearer ' + credentials.openrouter_key(),
             'Content-Type': 'application/json'},
            body, set(), self.name)

    def adapt(self, response, tool_names, notes=None):
        yield from transport.passthrough(response)


class ClaudeSubscriptionProvider:
    name = 'anthropic-subscription'
    host = ANTHROPIC_HOST

    def prepare(self, model, path, payload, raw_body, headers, credentials):
        auth = headers.get('Authorization', '')
        if not (auth.startswith('Bearer ') or 'x-api-key' in headers):
            raise PermissionError('Claude subscription authentication required')
        fwd = {k: v for k, v in headers.items() if k.lower() not in transport.HOP_HEADERS}
        return transport.Prepared(self.host, path, fwd, raw_body, set(), self.name)

    def adapt(self, response, tool_names, notes=None):
        yield from transport.passthrough(response)


def select(model, path, openai_mode='subscription', anthropic_mode=None,
           allowed=None):
    if _is_openrouter_slug(model):
        # Plan 068: a portco allowlist gates routing, never just the picker.
        # None means no policy provisioned (today's behavior). Aliases and
        # bare Anthropic ids resolve to the registry slug before the check.
        slug = resolve(model)
        if allowed is not None and slug not in frozenset(allowed):
            raise UnknownModel(slug, ())
        return ClaudeOpenRouterProvider()
    # Independent subscription choice; missing mode reproduces the legacy
    # behavior of following openai_mode. Never widened by migration.
    if (anthropic_mode if anthropic_mode is not None else openai_mode) == 'none':
        raise ValueError('Model is not available without a Claude subscription; '
                         'use an OpenRouter model')
    return ClaudeSubscriptionProvider()
