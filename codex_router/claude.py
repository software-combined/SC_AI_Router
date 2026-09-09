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

from . import providers
from .capabilities import OPENROUTER_HOST
from .errors import PreparationError
from .registry import MODELS, by_slug

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


def models_listing():
    """Anthropic-style {data: [{id, display_name}]} for gateway discovery."""
    rows = []
    for entry in MODELS:
        alias = claude_alias(entry.slug)
        if alias is not None:
            rows.append({'id': alias, 'display_name': entry.display_name})
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
        if isinstance(model, str) and slug != model:
            try:
                obj = json.loads(raw_body.decode())
            except (ValueError, UnicodeDecodeError):
                obj = None
            if isinstance(obj, dict):
                obj['model'] = slug
                body = json.dumps(obj).encode()
        return providers.Prepared(
            OPENROUTER_HOST, ANTHROPIC_PREFIX + path,
            {'Authorization': 'Bearer ' + credentials.openrouter_key(),
             'Content-Type': 'application/json'},
            body, set(), self.name)

    def adapt(self, response, tool_names, notes=None):
        yield from providers._passthrough(response)


class ClaudeSubscriptionProvider:
    name = 'anthropic-subscription'
    host = ANTHROPIC_HOST

    def prepare(self, model, path, payload, raw_body, headers, credentials):
        auth = headers.get('Authorization', '')
        if not (auth.startswith('Bearer ') or 'x-api-key' in headers):
            raise PermissionError('Claude subscription authentication required')
        fwd = {k: v for k, v in headers.items() if k.lower() not in providers.HOP_HEADERS}
        return providers.Prepared(self.host, path, fwd, raw_body, set(), self.name)

    def adapt(self, response, tool_names, notes=None):
        yield from providers._passthrough(response)


def select(model, path, openai_mode='subscription'):
    if _is_openrouter_slug(model):
        return ClaudeOpenRouterProvider()
    if openai_mode == 'none':
        raise ValueError('Model is not available without a Claude subscription; '
                         'use an OpenRouter model')
    return ClaudeSubscriptionProvider()
