"""One bounded retry for unattributable external-dialect Responses 400s.

The relay retries once with annotation-only top-level fields removed when
an OpenRouter Responses 400 names no cause (no code, tool or parameter).
The strip list and the retry gate live here with the retry policy; the
source-limit ceiling on `ai_router/upstream.py` keeps the pure helper here
rather than beside the other wire-body helpers.
"""
import http.client
import json

from . import provider_defs, transport, upstream

_ANNOTATION_ONLY_FIELDS = frozenset((
    'client_metadata', 'prompt_cache_options', 'prompt_cache_key', 'metadata',
    'safety_identifier', 'store', 'include', 'service_tier', 'truncation',
    'background', 'top_logprobs', 'user', 'stream_options'))


def strip_annotations(body):
    """Remove annotation-only top-level fields; None when nothing would change."""
    payload = upstream.parse_payload(body)
    if payload is None:
        return None
    cut = {key: value for key, value in payload.items()
           if key not in _ANNOTATION_ONLY_FIELDS}
    if len(cut) == len(payload):
        return None
    return json.dumps(cut, separators=(',', ':')).encode('utf-8')


def _copy_prepared(prepared, body):
    return transport.Prepared(prepared.host, prepared.path, prepared.headers,
                               body, prepared.tool_names, prepared.provider,
                               prepared.fallback, prepared.output_cap,
                               prepared.context_tokens)


def maybe_retry_unattributable(described, response, raw, metrics, provider,
                               prepared, attempts):
    """Retry once with annotation-only fields removed when an external-dialect
    Responses 400 names no cause. Returns (response, headers_done, prepared)
    or None when ineligible or the retried dispatch refused the turn. Never
    retries twice: a refused retry falls back to the caller's original
    handling, and the caller owns `attempts` so no connection outlives the
    request.
    """
    if not (response.status == 400
            and metrics.get('protocol') == provider_defs.RESPONSES
            and provider.defn.dialect == provider_defs.DIALECT_OPENROUTER
            and described is not None
            and described[2] is None
            and upstream.rejection_tool(raw, provider.defn.dialect) is None
            and upstream.rejection_parameter(raw) is None
            and upstream.rejection_reason(raw, provider.defn.dialect)
            == 'the request was rejected'):
        return None
    stripped = strip_annotations(prepared.body)
    if stripped is None:
        return None
    retried_prepared = _copy_prepared(prepared, stripped)
    fresh = http.client.HTTPSConnection(prepared.host,
                                        timeout=transport.UPSTREAM_TIMEOUT_S)
    try:
        response, headers_done = transport.post_with_phases(
            fresh, retried_prepared, metrics)
    except BaseException:
        fresh.close()
        raise
    attempts.append(fresh)
    if response.status >= 400:
        transport.read_capped(response, transport.ERROR_BODY_LIMIT)
        return None
    return response, headers_done, retried_prepared
