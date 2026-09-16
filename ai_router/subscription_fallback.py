"""Answer refused ChatGPT helper turns from the external twin row.

Codex desktop generates thread titles, descriptions, summaries and title
reconsiderations in their own helper threads pinned to the subscription
slug (today `gpt-5.6-luna`). Those turns carry
`x-codex-turn-metadata: {"thread_source": "thread_title", ...}`; ordinary
user turns carry no such source. When the ChatGPT allowance is exhausted,
upstream answers 429 for every helper turn and the client stores a slice
of the prompt as the title instead.

With the `openai_helper_fallback` state flag on, the router answers those
helper turns from the registry's external twin row (`openai/<slug>`) and
relays that response. Ordinary turns keep today's refusal. The flag is off
by default: the fallback bills that provider's key and sends the helper
prompt to it.
"""
import json

from . import errors, provider_defs
from .image_items import has_images
from .providers import ExternalResponsesProvider
from .registry import by_slug
from .events import log_event

HELPER_SOURCES = frozenset({'thread_title', 'thread_description',
                            'thread_summary', 'thread_title_reconsideration'})
METADATA_HEADER = 'x-codex-turn-metadata'
MAX_METADATA_BYTES = 8192
TWIN_PREFIX = 'openai/'


def helper_turn(headers):
    """True when the turn metadata names a thread metadata (helper) turn."""
    raw = next((v for k, v in headers.items() if k.lower() == METADATA_HEADER), None)
    if not isinstance(raw, str) or len(raw) > MAX_METADATA_BYTES:
        return False
    try:
        meta = json.loads(raw)
    except ValueError:
        return False
    if not isinstance(meta, dict):
        return False
    source = meta.get('thread_source')
    return isinstance(source, str) and source in HELPER_SOURCES


def twin_slug(model):
    """Registry slug of the external twin for a subscription slug, else None."""
    entry = by_slug(TWIN_PREFIX + model) if isinstance(model, str) else None
    if entry is None or not provider_defs.is_external(entry.provider):
        return None
    defn = provider_defs.get(entry.provider)
    return entry.slug if defn.serves(provider_defs.RESPONSES) else None


class Plan:
    """External twin prepared lazily, only once upstream actually refuses."""

    __slots__ = ('slug', 'path', 'payload', 'raw_body', 'headers', 'credentials',
                 'region')

    def __init__(self, slug, path, payload, raw_body, headers, credentials,
                 region='global'):
        self.slug, self.path, self.payload = slug, path, payload
        self.raw_body, self.headers = raw_body, headers
        self.credentials = credentials
        self.region = region

    def prepared(self):
        """Prepared request for the twin row; raises exactly as prepare() does."""
        payload = dict(self.payload, model=self.slug)
        defn = provider_defs.get(by_slug(self.slug).provider)
        return ExternalResponsesProvider(defn, self.region).prepare(
            self.slug, self.path, payload, self.raw_body, self.headers,
            self.credentials)


def plan(state, prepared, path, payload, raw_body, headers, credentials):
    """Fallback plan for this turn, or None when it is not eligible.

    Only Responses turns the subscription owns, carrying a helper thread
    source and no tools, qualify. The tool check keeps the twin's redispatch
    body identical to the client's own payload, which the subscription
    prepare may otherwise rewrite.
    """
    if not state.get('openai_helper_fallback') or path != '/responses':
        return None
    if prepared.provider != provider_defs.OPENAI.id or payload.get('tools'):
        return None
    if not helper_turn(headers):
        return None
    slug = twin_slug(payload.get('model'))
    if slug is None:
        return None
    # Plan 068: the twin is an external row, so the portco allowlist gates
    # this redispatch exactly as it gates a directly requested external row.
    allowed = state.get('allowed_models')
    if allowed is not None and slug not in allowed:
        return None
    # Key-filtered availability gates the twin like a direct request: the
    # fallback builds its adapter outright, so the owns() gate never runs.
    from . import availability as _availability
    if not _availability.permitted(slug):
        return None
    region = state.get('openrouter_region', 'global')
    if not provider_defs.valid_region(region):
        region = 'global'
    return Plan(slug, path, payload, raw_body, headers, credentials, region)


def prepare(provider, model, path, payload, raw_body, headers, server):
    """provider.prepare plus the refused-turn fallback plan when eligible."""
    prepared = provider.prepare(model, path, payload, raw_body, headers, server.credentials)
    prepared.fallback = plan(server.state, prepared, path, payload, raw_body, headers,
                             server.credentials)
    return prepared


def refused(handler, prepared, retry_after, metrics, started):
    """Answer a refused turn: the planned twin row, else the existing 503."""
    fallback = prepared.fallback
    if fallback is None:
        return handler.retryable_reject(errors.upstream_rate_limited(), retry_after)
    try:
        twin = fallback.prepared()
    except (LookupError, ValueError, PermissionError, OSError) as exc:
        # No key, unreadable twin row, rejected effort: keep today's answer.
        log_event('subscription_fallback_unavailable', model=metrics.get('model'),
                  fallback_model=fallback.slug, reason=type(exc).__name__)
        return handler.retryable_reject(errors.upstream_rate_limited(), retry_after)
    log_event('subscription_fallback', model=metrics.get('model'),
              fallback_model=fallback.slug, path=fallback.path)
    fields = ('request_bytes', 'stream', 'reasoning_effort', 'tool_definitions',
              'read_ms', 'prepare_ms', 'local_prepare_ms')
    # Fresh metrics: attempt one's upstream timings belong to the 429. The
    # protocol rides along so a mid-stream failure still emits the terminal
    # frame (transport.emit_terminal_failure keys on it, Plan 141).
    defn = provider_defs.get(by_slug(fallback.slug).provider)
    _region = getattr(fallback, 'region', 'global')
    twin_metrics = {k: metrics[k] for k in fields if k in metrics}
    twin_metrics.update(provider=defn.id, model=fallback.slug,
                        path=fallback.path, helper_fallback=True,
                        protocol=provider_defs.RESPONSES,
                        # The twin's own cap, from its freshly prepared body.
                        max_output_tokens=getattr(twin, 'output_cap', None))
    # The owned-request slot still covers this hand-off; relay no longer
    # takes or releases a slot of its own.
    return handler.relay(ExternalResponsesProvider(defn, _region), twin, twin_metrics, started,
                         has_images(fallback.payload.get('input')))
