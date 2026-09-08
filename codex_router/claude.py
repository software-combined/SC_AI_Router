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
from . import providers
from .capabilities import OPENROUTER_HOST
from .providers import PreparationError
from .registry import by_slug

ANTHROPIC_HOST = 'api.anthropic.com'
ANTHROPIC_PREFIX = '/api'
CLAUDE_PATHS = frozenset({'/v1/messages', '/v1/messages/count_tokens'})


def _is_openrouter_slug(model):
    entry = by_slug(model) if isinstance(model, str) else None
    return entry is not None and entry.provider == 'openrouter'


class ClaudeOpenRouterProvider:
    name = 'openrouter-claude'

    def prepare(self, model, path, payload, raw_body, headers, credentials):
        if path not in CLAUDE_PATHS:
            raise PreparationError('Claude ingress serves messages only')
        return providers.Prepared(
            OPENROUTER_HOST, ANTHROPIC_PREFIX + path,
            {'Authorization': 'Bearer ' + credentials.openrouter_key(),
             'Content-Type': 'application/json'},
            raw_body, set(), self.name)

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
