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
                               prepared, attempts, log_event):
    """Retry once with annotation-only fields removed when an external-dialect
    Responses 400 names no cause. Returns (response, headers_done, prepared)
    plus its bounded error body, or None when ineligible. The relay handles
    the retry's actual response through its ordinary failure policy.
    """
    eligible = (response.status == 400
            and metrics.get('protocol') == provider_defs.RESPONSES
            and provider.defn.dialect == provider_defs.DIALECT_OPENROUTER
            and described is not None
            and described[2] is None
            and not upstream.is_context_error(raw)
            and upstream.rejection_tool(raw, provider.defn.dialect) is None
            and upstream.rejection_parameter(raw) is None
            and upstream.rejection_reason(raw, provider.defn.dialect)
            == 'the request was rejected')
    fields = {'provider': prepared.provider, 'model': metrics.get('model')}
    if not eligible:
        log_event('annotation_retry', eligible=False, attempted=False,
                  outcome='ineligible', **fields)
        return None
    stripped = strip_annotations(prepared.body)
    if stripped is None:
        log_event('annotation_retry', eligible=True, attempted=False,
                  outcome='unchanged', **fields)
        return None
    log_event('annotation_retry', eligible=True, attempted=True,
              outcome='started', **fields)
    retried_prepared = _copy_prepared(prepared, stripped)
    fresh = http.client.HTTPSConnection(prepared.host,
                                        timeout=transport.UPSTREAM_TIMEOUT_S)
    try:
        response, headers_done = transport.post_with_phases(
            fresh, retried_prepared, metrics)
        retry_raw = (transport.read_capped(response, transport.ERROR_BODY_LIMIT)
                     if response.status >= 400 else None)
    except BaseException as exc:
        fresh.close()
        log_event('annotation_retry', eligible=True, attempted=True,
                  outcome='transport_error', error_type=type(exc).__name__, **fields)
        raise
    attempts.append(fresh)
    log_event('annotation_retry', eligible=True, attempted=True,
              outcome='rejected' if retry_raw is not None else 'accepted',
              status=response.status,
              reason=upstream.rejection_reason(retry_raw, provider.defn.dialect),
              parameter=upstream.rejection_parameter(retry_raw),
              serving_endpoint=upstream.serving_endpoint(retry_raw), **fields)
    return response, headers_done, retried_prepared, retry_raw


def post_with_retry(conn, prepared, metrics, attempts, provider, log_event):
    """Dispatch at most twice and retain the final response for normal handling."""
    response, headers_done = transport.post_with_phases(conn, prepared, metrics)
    raw = None
    if response.status >= 400:
        raw = transport.read_capped(response, transport.ERROR_BODY_LIMIT)
        described = upstream.describe_failure(
            None, {'status': response.status, 'body': raw},
            {'model': metrics.get('model'), 'provider': prepared.provider,
             'protocol': metrics.get('protocol'), 'dialect': provider.defn.dialect})
        retried = maybe_retry_unattributable(
            described, response, raw, metrics, provider, prepared, attempts, log_event)
        if retried is not None:
            return retried
    return response, headers_done, prepared, raw
