"""Upstream failure policy (Plan 127 split; behaviour unchanged).

Failure classification, retries and response encoding. Adapters build requests; this module
decides how an upstream refusal is described to the client.

Pure policy: no dispatch, no model data, no credentials. It may read a
response object but never a request body except the error snapshot the
caller already bounded, plus the prepared body `rejection_fingerprint`
reduces to structural counts.
"""
import hashlib
import json
import re
import threading
import time

from . import provider_defs
from .events import log_event
from .stream_errors import metadata_endpoint, is_context_error

KEY_NO_CREDIT_MESSAGE = (
    '{model} cannot run on the OpenRouter key: '
    'it has no remaining credit. '
    'Contact IT for a topped-up key, then retry')


_429_QUOTA_CODES = frozenset((
    'insufficient_quota', 'billing_hard_limit_reached', 'billing_not_active',
    'credit_balance_too_low'))
_429_AUTH_CODES = frozenset((
    'invalid_api_key', 'insufficient_permissions', 'account_deactivated',
    'authentication_error'))


def _429_codes(body):
    """Structured 429 codes from the error envelope; never message prose."""
    try:
        payload = json.loads(body.decode() if isinstance(body, bytes) else body)
    except (ValueError, UnicodeDecodeError, AttributeError):
        return ()
    if not isinstance(payload, dict) or not isinstance(payload.get('error'), dict):
        return ()
    error = payload['error']
    codes = [error.get('code'), error.get('type'), error.get('error_type')]
    metadata = error.get('metadata')
    if isinstance(metadata, dict):
        codes.append(metadata.get('provider_code'))
    return tuple(c.lower() for c in codes if isinstance(c, str))


def classify_429(body):
    """'quota' | 'auth' | 'transient' from structured 429 codes only."""
    for code in _429_codes(body):
        if code in _429_QUOTA_CODES or 'quota' in code or 'billing' in code or 'credit' in code:
            return 'quota'
        if code in _429_AUTH_CODES or 'permission' in code or 'api_key' in code \
                or 'authentication' in code:
            return 'auth'
    return 'transient'


def upstream_retry_after(response, prepared, metrics, body):
    """Consume an upstream 429; return (category, Retry-After), else None.

    Codex treats a bare 429 as turn-fatal, so the caller must answer 503.
    The caller passes the already-drained body: this module must never
    import transport (domain boundary), so it never reads the socket itself.
    """
    if response.status != 429:
        return None
    category = classify_429(body)
    log_event('upstream_rate_limited', provider=prepared.provider, path=metrics['path'],
              category=category)
    return category, response.getheader('Retry-After', '2')


_CODE_SHAPE = re.compile(r'^[A-Za-z0-9_.-]{1,40}$')

# Serving-endpoint slugs observed in `openrouter_metadata` (router-metadata
# guide and the OpenAPI `OpenRouterMetadata`/`EndpointInfo`/`RouterAttempt`
# schemas, read 2026-09-14):
# `endpoints.available[]` entries carry `provider` with a `selected` flag,
# and `attempts[]` entries carry `provider`. Slashes allow `vendor/slug`
# shapes; the bound keeps prose out of the log.
_ENDPOINT_SHAPE = re.compile(r'^[A-Za-z0-9_.\-/]{1,64}$')


def _bounded_endpoint(value):
    if isinstance(value, bool) or not isinstance(value, str):
        return None
    text = value.strip()
    return text if _ENDPOINT_SHAPE.match(text) else None


_PARAM_SHAPE = re.compile(
    r'(?:input|tools)(?:\[[0-9]{1,6}\])?'
    r'(?:\.(?:content|summary|type|parameters|items|required|enum|name|arguments)'
    r'(?:\[[0-9]{1,6}\])?){0,4}|model|reasoning\.effort')


def rejection_parameter(body):
    """Only allowlisted schema paths, never arbitrary property names or prose."""
    for _ in range(2):  # Direct error or the provider's nested raw envelope.
        try:
            payload = json.loads(body)
        except (ValueError, TypeError):
            return None
        error = payload.get('error') if isinstance(payload, dict) else None
        if not isinstance(error, dict):
            return None
        param = error.get('param')
        if isinstance(param, str) and len(param) <= 96 and _PARAM_SHAPE.fullmatch(param):
            return param
        metadata = error.get('metadata')
        body = metadata.get('raw') if isinstance(metadata, dict) else None
    return None


def _error_code(error, inner_error):
    """A provider code only when the field is already code-shaped.

    Upstream prose is never rewritten into a code: a value that does not
    match the code shape on its own yields None, so the client message and
    the log can never carry an upstream sentence.
    """
    metadata = error.get('metadata')
    candidates = [error.get('code'), error.get('error_type')]
    if isinstance(metadata, dict):
        candidates.append(metadata.get('provider_code'))
    if isinstance(inner_error, dict):
        candidates += [inner_error.get('code'), inner_error.get('error_type')]
    for candidate in candidates:
        if isinstance(candidate, str) and _CODE_SHAPE.match(candidate.strip()):
            return candidate.strip().lower()
    return None


def serving_endpoint(body):
    """Bounded serving-endpoint slug from a response body, else None.

    Reads, in order, the selected entry of
    `openrouter_metadata.endpoints.available[]`, the `provider` of each
    `openrouter_metadata.attempts[]` entry, then
    `error.metadata.provider_name`. Only code-shaped slugs leave this
    function; anything else yields None. Accepts a body, a parsed payload,
    or a terminal event dict.
    """
    if isinstance(body, dict):
        payload = body
    else:
        try:
            payload = json.loads(body.decode() if isinstance(body, bytes) else body)
        except (ValueError, TypeError, UnicodeDecodeError, AttributeError):
            return None
    if not isinstance(payload, dict):
        return None
    value = metadata_endpoint(payload, _bounded_endpoint)
    if value:
        return value
    error = payload.get('error')
    if isinstance(error, dict):
        inner = error.get('metadata')
        if isinstance(inner, dict):
            value = _bounded_endpoint(inner.get('provider_name'))
            if value:
                return value
    return None


def _provider_reason(body):
    """(provider_name, fixed_category, wire_tool, bounded_code) from an error body.

    Only structural fragments leave this function: never raw bodies, schemas,
    argument values, secret-bearing text, or arbitrary upstream prose. The
    category is fixed wording chosen from the error shape; the offending tool
    is kept only after the bounded identity match below; the code comes from
    fixed code fields only.
    """
    try:
        payload = json.loads(body.decode() if isinstance(body, bytes) else body)
    except (ValueError, UnicodeDecodeError, AttributeError):
        return None
    if not isinstance(payload, dict):
        return None
    error = payload.get('error')
    if not isinstance(error, dict):
        return None
    metadata = error.get('metadata')
    provider = metadata.get('provider_name') if isinstance(metadata, dict) else None
    raw = metadata.get('raw') if isinstance(metadata, dict) else None
    text, inner = None, None
    if isinstance(raw, str):
        try:
            inner = json.loads(raw)
            text = inner.get('error') if isinstance(inner, dict) else raw
        except ValueError:
            text = raw
    inner_error = inner.get('error') if isinstance(inner, dict) else None
    if not isinstance(text, str):
        text = error.get('message') if isinstance(error.get('message'), str) else None
    if not isinstance(text, str) or not text.strip():
        return None
    tool = None
    match = re.search(r'\bns_[0-9a-f]{12}_\S+|\b[a-z][\w.-]*\.[\w-]+\b|\b[A-Za-z0-9_-]+__[A-Za-z0-9_-]+\b', text)
    if match:
        tool = match.group(0).rstrip(':,.')
    lowered = text.lower()
    if 'invalid_client_tool_schema' in lowered or 'must be an object' in lowered:
        reason = 'the tool schema was rejected'
    elif 'invalid' in lowered and 'tool' in lowered:
        reason = 'a tool call was rejected'
    else:
        reason = 'the request was rejected'
    return provider, reason, tool, _error_code(error, inner_error)


def rejection_fingerprint(prepared_body):
    """Structural counts from a prepared wire body; never content.

    Returns {'items', 'item_kinds', 'tools'} with counts only: no item text,
    tool descriptions, schema text, arguments, ids, or names. Undecodable
    bodies return {}.
    """
    try:
        payload = json.loads(prepared_body.decode() if isinstance(prepared_body, bytes)
                             else prepared_body)
    except (ValueError, UnicodeDecodeError, AttributeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    items = payload.get('input')
    if not isinstance(items, list):
        return {}
    kinds = {}
    for item in items:
        kind = item.get('type') if isinstance(item, dict) else None
        kind = kind if isinstance(kind, str) else 'unknown'
        kinds[kind] = kinds.get(kind, 0) + 1
    tools = payload.get('tools', [])
    return {'items': len(items), 'item_kinds': kinds,
            'tools': len(tools) if isinstance(tools, list) else 0}


_REFUSALS = {}
_REFUSAL_LOCK = threading.Lock()
_REFUSAL_MAX = 8
_REFUSAL_TTL_S = 60


def _refusal_key(provider, model, body):
    digest = hashlib.sha256(body if isinstance(body, bytes) else str(body).encode()).hexdigest()
    return (provider, model, digest)


def recall_refusal(provider, model, body, now=None):
    """The cached (client status, message) for an identical body, else None."""
    clock = now if now is not None else time.monotonic()
    with _REFUSAL_LOCK:
        hit = _REFUSALS.get(_refusal_key(provider, model, body))
    if hit is None or clock - hit[1] > _REFUSAL_TTL_S:
        return None
    return hit[0]


def remember_refusal(provider, model, body, message, now=None, *, status=400):
    """Cache a described refusal; evict oldest writes past 8 entries."""
    clock = now if now is not None else time.monotonic()
    key = _refusal_key(provider, model, body)
    with _REFUSAL_LOCK:
        _REFUSALS[key] = ((status, message), clock)
        while len(_REFUSALS) > _REFUSAL_MAX:
            oldest = min(_REFUSALS, key=lambda candidate: _REFUSALS[candidate][1])
            _REFUSALS.pop(oldest, None)


def clear_refusals():
    """Drop the process-local refusal cache (tests)."""
    with _REFUSAL_LOCK:
        _REFUSALS.clear()


def validate_response(response, prepared):
    """Check adapted Responses encoding before forwarding response headers.

    Only dialect-adapted upstreams are gated: a Messages passthrough never
    promises plaintext tool handoff in the Responses sense.
    """
    defn = provider_defs.get(prepared.provider)
    if (defn is not None and defn.serves(provider_defs.RESPONSES)
            and prepared.tool_names):
        encoding = response.getheader('Content-Encoding', '').strip().lower()
        if encoding not in ('', 'identity'):
            raise ValueError('unsupported plaintext handoff response encoding')


def describe_failure(exc, response, info):
    """Name an upstream failure for the client: (status, message, code) or None.

    Pure: no reads, no logging, no clock. `response` is a snapshot
    {'status': int, 'body': bytes} or None when headers never arrived.
    Unknown shapes return None so the caller keeps existing behavior. The
    switch-back recovery joins the message only for a routed turn
    (`info['routed']`), where a mid-thread model swap is the likely cause.
    """
    model = info.get('model', 'the model')
    timeout = info.get('timeout_s', 120)
    if response is not None:
        if response.get('status') == 429:
            return None  # existing Retry-After path owns 429s
        if response.get('status') == 402:
            # Status alone names the cause: the key cannot afford the turn.
            # The code comes from fixed fields only; prose never classifies.
            parsed = _provider_reason(response.get('body', b''))
            code = parsed[3] if parsed is not None else None
            return 400, KEY_NO_CREDIT_MESSAGE.format(model=model), code
        if (info.get('protocol') == provider_defs.RESPONSES
                and (response.get('status', 0) >= 500 or response.get('status') == 408)):
            parsed = _provider_reason(response.get('body', b'')) or (None,)
            who = f'upstream {parsed[0]}' if parsed[0] else 'upstream'
            return 503, (f'{model} is unavailable at {who} '
                         f'(HTTP {response.get("status")}); retry shortly'), None
        parsed = _provider_reason(response.get('body', b''))
        if parsed is None:
            return None
        provider, reason, tool, code = parsed
        who = f'upstream {provider}' if provider else 'upstream'
        message = (f'{model} was rejected by {who} '
                   f'(HTTP {response.get("status")}'
                   f'{", code " + code if code else ""}): {reason}. ')
        if info.get('routed'):
            message += ('Switch this thread back to the previous model, '
                        f'or start a new thread for {model}. ')
        message += 'Do not retry the unchanged request'
        if tool:
            message += f'; offending tool: {tool}'
        param = rejection_parameter(response.get('body', b''))
        if param:
            message += f'; field: {param}'
        if (info.get('protocol') == provider_defs.RESPONSES
                and not is_context_error(response.get('body', b''))):
            return 400, message, code
        return 409, message, code
    if isinstance(exc, TimeoutError):
        elapsed = round((info.get('elapsed_ms') or 0) / 1000)
        message = (f'{model} did not answer within {timeout}s '
                   f'(waited {elapsed}s). Retry a shorter turn')
        # Tilde aliases and pinned ids share the vendor prefix.
        if (isinstance(model, str) and model.removeprefix('~').startswith('x-ai/')
                and info.get('has_image')):
            message += '; Grok image turns stall upstream, retry text-only'
        return 502, message, None
    if isinstance(exc, OSError):
        host = info.get('host')
        if host:
            return 502, f'{model} is unreachable at {host}: check the network connection and retry', None
        return 502, f'{model} lost its upstream connection before responding; retry', None
    return None
