"""Upstream failure classification, retries and response encoding.

Pure policy: no dispatch, model data, credentials or request body reads.
"""
import hashlib
import json
import re
import threading
import time

from . import outcome, provider_defs
from .events import log_event
from .stream_errors import error_codes, metadata_endpoint, is_context_error

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


def parse_payload(body):
    """The parsed JSON object, or None for an unparseable or non-object body."""
    try:
        payload = json.loads(body.decode() if isinstance(body, bytes) else body)
    except (ValueError, TypeError, UnicodeDecodeError, AttributeError):
        return None
    return payload if isinstance(payload, dict) else None
def _429_codes(body):
    error = (parse_payload(body) or {}).get('error')
    if not isinstance(error, dict):
        return ()
    codes = [error.get(key) for key in ('code', 'type', 'error_type')]
    metadata = error.get('metadata')
    if isinstance(metadata, dict):
        codes.append(metadata.get('provider_code'))
    return tuple(code.lower() for code in codes if isinstance(code, str))
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
    if response.status != 429 or is_context_error(body):
        return None
    category = classify_429(body)
    log_event('upstream_rate_limited', provider=prepared.provider, path=metrics['path'],
              category=category)
    return category, response.getheader('Retry-After', '2')
_CODE_SHAPE = re.compile(r'^[A-Za-z0-9_.-]{1,40}$')

# Serving-endpoint slugs: `endpoints.available[]`/`attempts[]` carry
# `provider`; `error.metadata.provider_name` too. Slashes allow
# `vendor/slug`; the bound keeps prose out of the log.
_ENDPOINT_SHAPE = re.compile(r'^[A-Za-z0-9_.\-/]{1,64}$')


def _bounded_endpoint(value):
    if isinstance(value, bool) or not isinstance(value, str):
        return None
    return value.strip() if _ENDPOINT_SHAPE.match(value.strip()) else None


_PARAM_SHAPE = re.compile(
    r'(?:input|tools)(?:\[[0-9]{1,6}\])?'
    r'(?:\.(?:content|summary|type|parameters|items|required|enum|name|arguments)'
    r'(?:\[[0-9]{1,6}\])?){0,4}|model|reasoning\.effort')


def rejection_parameter(body):
    """Only allowlisted schema paths, never arbitrary property names or prose."""
    for _ in range(2):  # Direct error or the provider's nested raw envelope.
        payload = parse_payload(body)
        if payload is None:
            return None
        error = payload.get('error')
        if not isinstance(error, dict):
            return None
        param = error.get('param')
        if isinstance(param, str) and len(param) <= 96 and _PARAM_SHAPE.fullmatch(param):
            return param
        metadata = error.get('metadata')
        body = metadata.get('raw') if isinstance(metadata, dict) else None
    return None


def rejection_tool(body, dialect=None):
    """The offending tool's bounded name, or None; never arbitrary prose.

    The client message no longer names the tool, so the rejection log line
    carries it. The name already passed `_provider_reason`'s identity match.
    """
    parsed = _provider_reason(body, dialect)
    return parsed[2] if parsed is not None else None


def rejection_reason(body, dialect=None):
    """The fixed category wording, or None when the body names no cause."""
    parsed = _provider_reason(body, dialect)
    return parsed[1] if parsed is not None else None


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

    Reads the selected `endpoints.available[]` entry, then each
    `attempts[]` provider, then `error.metadata.provider_name`. Only
    code-shaped slugs leave this function; anything else yields None.
    """
    payload = body if isinstance(body, dict) else parse_payload(body)
    if payload is None:
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


def _provider_reason(body, dialect=None):
    """(provider_name, fixed_category, wire_tool, bounded_code) from an error body.

    Only structural fragments leave this function: never raw bodies, schemas,
    argument values, secret-bearing text, or arbitrary upstream prose. The
    category is fixed wording chosen from the error shape; the offending tool
    is kept only after the bounded identity match below; the code comes from
    fixed code fields only. `dialect` picks the envelope reader: OpenRouter
    nests the upstream text in `error.metadata.raw`, while an
    OpenAI-compatible body carries `error.message` directly. Every other
    dialect keeps the metadata reader, so the built-in paths are unchanged.
    """
    payload = parse_payload(body)
    if payload is None:
        return None
    error = payload.get('error')
    if not isinstance(error, dict):
        return None
    metadata = error.get('metadata')
    provider = metadata.get('provider_name') if isinstance(metadata, dict) else None
    text, inner = None, None
    if dialect != provider_defs.DIALECT_OPENAI_COMPATIBLE:
        raw = metadata.get('raw') if isinstance(metadata, dict) else None
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


def validate_response(response, prepared, *, raw_encoded=False):
    """Reject encodings that require repair before response headers."""
    defn = provider_defs.get(prepared.provider)
    encoding = response.getheader('Content-Encoding', '').strip().lower()
    if (defn is not None and defn.kind == provider_defs.EXTERNAL
            and defn.serves(provider_defs.MESSAGES) and 'json' in
            response.getheader('Content-Type', '').lower()
            and encoding not in ('', 'identity')):
        raise ValueError('unsupported Messages JSON response encoding')
    if raw_encoded or not (defn is not None
            and defn.serves(provider_defs.RESPONSES) and prepared.tool_names):
        return
    if encoding not in ('', 'identity'):
        raise ValueError('unsupported plaintext handoff response encoding')
_REJECTED_BY_STATUS = {401: outcome.AUTH, 403: outcome.AUTH, 402: outcome.QUOTA}
_429_OUTCOMES = {'quota': outcome.QUOTA, 'auth': outcome.AUTH}
def outcome_of(status, body, dialect=None):
    """Classify one HTTP error status and bounded body; unreadable is UNKNOWN."""
    payload = parse_payload(body)
    error = payload.get('error') if payload is not None else None
    reason = _provider_reason(body, dialect)
    code = (_error_code(error, None) if isinstance(error, dict) else None) or (
        reason[3] if reason else None)
    codes = error_codes(payload, payload)
    error_type = next((value.strip().lower()
                       for source in (payload, error) if isinstance(source, dict)
                       for key in ('error_type', 'type')
                       for value in [source.get(key)]
                       if isinstance(value, str) and _CODE_SHAPE.match(value.strip())), None)
    named = outcome.category_for(error_type, codes)
    deterministic_reason = (reason is not None and reason[1] in
                            ('the tool schema was rejected', 'a tool call was rejected'))
    context = is_context_error(body)
    category = (
        (outcome.CONTEXT_OVERFLOW if context
         else named if named in (outcome.REFUSED, outcome.QUOTA, outcome.AUTH)
         else _429_OUTCOMES.get(classify_429(body), outcome.RATE_LIMIT))
        if status == 429
        else outcome.CONTEXT_OVERFLOW if context
        else _REJECTED_BY_STATUS.get(status) if status in _REJECTED_BY_STATUS
        else named if named != outcome.UNKNOWN
        else outcome.REFUSED if deterministic_reason
        else outcome.TRANSIENT if status >= 500 or status == 408
        else outcome.REFUSED if reason is not None
        else outcome.UNKNOWN)
    code = outcome.code_for(category, error_type, codes) or code
    # A rejected request never ran; a failed or unreadable one may have.
    return outcome.Outcome(category, outcome.STATUS, outcome.UPSTREAM, code,
                           side_effects=category in (outcome.TRANSIENT, outcome.UNKNOWN))


def describe_failure(exc, response, info):
    """Name an upstream failure for the client, or None for an unknown shape."""
    model = info.get('model', 'the model')
    dialect = info.get('dialect')
    if response is not None:
        body = response.get('body', b'')
        context = is_context_error(body)
        if response.get('status') == 429 and not context:
            return None  # existing Retry-After path owns 429s
        if response.get('status') == 402:
            # Status alone names the cause: the key cannot afford the turn.
            # The code comes from fixed fields only; prose never classifies.
            parsed = _provider_reason(response.get('body', b''), dialect)
            code = parsed[3] if parsed is not None else None
            return 400, KEY_NO_CREDIT_MESSAGE.format(model=model), code
        if (info.get('protocol') == provider_defs.RESPONSES
                and not context
                and (response.get('status', 0) >= 500 or response.get('status') == 408)):
            classified = outcome_of(response.get('status', 0), body, dialect)
            if classified.category == outcome.REFUSED:
                parsed = _provider_reason(body, dialect)
                reason = parsed[1] if parsed is not None else 'the request was rejected'
                code = classified.code or (parsed[3] if parsed is not None else None)
                message = f'{model} refused this request: {reason}. Do not retry it unchanged'
                if info.get('routed'):
                    message += (' Switch this thread back to the previous model, '
                                f'or start a new thread for {model}.')
                return 400, message, code
            return 503, (f'{model} is temporarily unavailable and the turn was '
                         'not served. Retry shortly.'), None
        parsed = _provider_reason(body, dialect)
        if parsed is None:
            if context:
                return (409, f'{model} refused this request: the request was rejected. '
                        'Do not retry it unchanged', 'context_length_exceeded')
            return None
        _, reason, tool, code = parsed
        unnamed = (code is None and tool is None
                   and reason == 'the request was rejected'
                   and rejection_parameter(response.get('body', b'')) is None
                   and info.get('protocol') == provider_defs.RESPONSES
                   and not context)
        message = (f'{model} was rejected by the provider without naming a cause. '
                   if unnamed else f'{model} refused this request: {reason}. ')
        if info.get('routed'):
            message += ('Switch this thread back to the previous model, '
                        f'or start a new thread for {model}. ')
        if not unnamed:
            message += 'Do not retry it unchanged'
        if info.get('protocol') == provider_defs.RESPONSES and not context:
            return 400, message, code
        return 409, message, code
    if isinstance(exc, TimeoutError):
        message = (f'{model} did not answer in time and this turn was not sent. '
                   'Retry a shorter turn')
        # Tilde aliases and pinned ids share the vendor prefix.
        if (isinstance(model, str) and model.removeprefix('~').startswith('x-ai/')
                and info.get('has_image')):
            message += '; retry without the image'
        return 502, message, None
    if isinstance(exc, OSError):
        return 502, (f'{model} could not be reached. '
                     'Check the network connection and retry.'), None
    return None
