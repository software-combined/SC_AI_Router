"""Answer refused ChatGPT helper turns from the external twin row.

Codex desktop generates thread titles, descriptions, summaries and title
reconsiderations in their own helper threads pinned to the subscription
slug (currently the legacy `gpt-5.6-luna` id). Those turns carry
`x-codex-turn-metadata: {"thread_source": "thread_title", ...}`; ordinary
user turns carry no such source. When the ChatGPT allowance is exhausted,
upstream answers 429 for every helper turn and the client stores a slice
of the prompt as the title instead.

Client 0.154 attaches the read-only app tool allowlist it derives from the
installed apps and MCP servers to those helper turns, so a helper turn can
carry tools. Tools do not disqualify a turn here: the twin is prepared from
the client's own payload, tools included, the same way a directly requested
external row is.

With the `openai_helper_fallback` state flag on, the router answers those
helper turns from the registry's external twin row (`openai/<slug>`) and
relays that response. Ordinary turns keep today's refusal. The flag is off
by default: the fallback bills that provider's key and sends the helper
prompt to it.
"""
import json

from . import errors, provider_defs, request_context, subscription_roster, wire_shape
from .image_items import has_images
from .providers import ExternalResponsesProvider
from .events import log_event

HELPER_SOURCES = frozenset({'thread_title', 'thread_description',
                            'thread_summary', 'thread_title_reconsideration'})
METADATA_HEADER = 'x-codex-turn-metadata'
MAX_METADATA_BYTES = 8192
TWIN_PREFIX = subscription_roster.TWIN_PREFIX


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


def twin_slug(model, catalogue=None):
    """Registry slug of the external twin for a subscription slug, else None.

    `catalogue` is the request's captured generation; None reads the live one."""
    if not isinstance(model, str):
        return None
    successor = subscription_roster.SUCCESSORS.get(model, model)
    rows = request_context.capture() if catalogue is None else catalogue
    entry = rows.get(TWIN_PREFIX + successor)
    if entry is None or not provider_defs.is_external(entry.provider):
        return None
    defn = provider_defs.get(entry.provider)
    return entry.slug if defn.serves(provider_defs.RESPONSES) else None


class Plan:
    """External twin prepared lazily, only once upstream actually refuses.

    `target` is the refused request's own context retargeted to the twin
    row: same request id, same registry generation, whatever a refresh
    swapped in between the plan and the refusal."""

    __slots__ = ('target', 'path', 'payload', 'raw_body', 'headers', 'credentials',
                 'region')

    def __init__(self, target, path, payload, raw_body, headers, credentials,
                 region='global'):
        self.target, self.path, self.payload = target, path, payload
        self.raw_body, self.headers = raw_body, headers
        self.credentials = credentials
        self.region = region

    def prepared(self):
        """Prepared request for the twin row; raises exactly as prepare() does."""
        target = self.target
        payload = dict(self.payload, model=target.slug)
        defn = provider_defs.get(target.row.provider)
        return ExternalResponsesProvider(defn, self.region).prepare(
            target.slug, self.path, payload, self.raw_body, self.headers,
            self.credentials, context=target)


def plan(state, prepared, path, payload, raw_body, headers, credentials):
    """Fallback plan for this turn, or None when it is not eligible.

    Only Responses turns the subscription owns that a helper thread source
    marks qualify; tools do not disqualify one.
    """
    if not state.get('openai_helper_fallback') or path != '/responses':
        return None
    if prepared.provider != provider_defs.OPENAI.id:
        return None
    if not helper_turn(headers):
        return None
    context = prepared.context or request_context.resolve(
        payload.get('model'), request_context.capture())  # a direct call
    slug = twin_slug(context.slug, context.catalogue)
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
    return Plan(request_context.retarget(context, slug), path, payload, raw_body,
                headers, credentials, region)


def prepare(provider, model, path, payload, raw_body, headers, server, decoded_len=None,
            context=None):
    """provider.prepare plus the refused-turn fallback plan when eligible.

    Only Responses adapters own these two paths, so every prepared Responses
    body also passes the observe-only contract check.
    """
    prepared = provider.prepare(model, path, payload, raw_body, headers,
                                server.credentials, decoded_len=decoded_len,
                                context=context)
    if path in ('/responses', '/responses/compact'):
        _observe_contract(provider, prepared, model, path, payload, raw_body)
    prepared.fallback = plan(server.state, prepared, path, payload, raw_body, headers,
                             server.credentials)
    return prepared


def _observe_contract(provider, prepared, model, path, payload, raw_body):
    """One `wire_contract` line of rule names and counts when a rule fires.

    The body goes upstream unchanged whatever this finds. A passthrough body
    is the client's payload, already parsed; only a rewritten one is parsed
    again. A fault in the check is logged by its type and never fails a turn.
    """
    try:
        wire = (payload if prepared.body is raw_body
                else wire_shape.decode_wire(prepared.body))
        found = wire_shape.violations(provider.defn.dialect, wire)
    except Exception as exc:  # noqa: BLE001 - observation must never fail a turn
        found = {'error_type': type(exc).__name__}
    if any(found.values()):
        log_event('wire_contract', provider=prepared.provider, model=model, path=path,
                  **found)


def refusal_message(prepared, metrics):
    """Answer text for a refused turn: whose limit it is, and what to do.

    Fixed wording from the provider's own definition, never upstream prose.
    An external route names no subscription, so it keeps the neutral text.
    """
    defn = provider_defs.get(prepared.provider)
    label = None if defn is None else defn.subscription_label
    if label is None:
        # An external route has no subscription to name: the catalogue's
        # neutral rate-limit case owns that wording.
        return errors.upstream_rate_limited().message
    model = metrics.get('model')
    model = model if isinstance(model, str) and model else 'This model'
    return (f'{model} is rate limited on your {label}; the turn was not served. '
            'Retry shortly, or select a routed model instead.')


def refused(handler, prepared, retry_after, metrics, started):
    """Answer a refused turn: the planned twin row, else the retryable 503."""
    refusal = errors.upstream_rate_limited(refusal_message(prepared, metrics))
    fallback = prepared.fallback
    if fallback is None:
        return handler.error(refusal, retry_after)
    try:
        twin = fallback.prepared()
    except (LookupError, ValueError, PermissionError, OSError) as exc:
        # No key, unreadable twin row, rejected effort: keep today's answer.
        log_event('subscription_fallback_unavailable', model=metrics.get('model'),
                  fallback_model=fallback.target.slug, reason=type(exc).__name__)
        return handler.error(refusal, retry_after)
    log_event('subscription_fallback', model=metrics.get('model'),
              fallback_model=fallback.target.slug, path=fallback.path)
    fields = ('request_bytes', 'stream', 'reasoning_effort', 'tool_definitions',
              'read_ms', 'prepare_ms', 'local_prepare_ms')
    # Fresh metrics: attempt one's upstream timings belong to the 429. The
    # protocol rides along so a mid-stream failure still emits the terminal
    # frame (transport.emit_terminal_failure keys on it, Plan 141).
    # The twin's context is the refused request's, so its final record
    # carries the same request id.
    defn = provider_defs.get(twin.context.row.provider)
    _region = getattr(fallback, 'region', 'global')
    twin_metrics = {k: metrics[k] for k in fields if k in metrics}
    twin_metrics.update(request_id=twin.context.request_id, provider=defn.id,
                        model=twin.context.slug,
                        path=fallback.path, helper_fallback=True,
                        protocol=provider_defs.RESPONSES,
                        # The twin's own cap, from its freshly prepared body.
                        max_output_tokens=getattr(twin, 'output_cap', None))
    # The owned-request slot still covers this hand-off; relay no longer
    # takes or releases a slot of its own.
    return handler.relay(ExternalResponsesProvider(defn, _region), twin, twin_metrics, started,
                         has_images(fallback.payload.get('input')))
