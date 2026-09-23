"""One bounded retry for a repairable Responses 400.

The relay retries once when a provider 400 can be repaired without changing
what the turn means. Two conditions qualify: an OpenRouter Responses 400 that
names no cause (no code, tool or parameter) is retried with annotation-only
top-level fields removed, and a subscription Responses 400 reporting
`invalid_encrypted_content` is retried with the OpenAI-owned reasoning blobs
removed from `input`. The strip lists and the retry gates live here with the
retry policy; the source-limit ceiling on `ai_router/upstream.py` keeps the pure
helpers here rather than beside the other wire-body helpers.
"""
import http.client
import io
import json
from compression import zstd

from . import compaction as comp, provider_defs, transport, upstream

_ANNOTATION_ONLY_FIELDS = frozenset((
    'client_metadata', 'prompt_cache_options', 'prompt_cache_key', 'metadata',
    'safety_identifier', 'store', 'include', 'service_tier', 'truncation',
    'background', 'top_logprobs', 'user', 'stream_options'))
# Matches runtime.MAX_DECODE_FACTOR without importing the composition root.
ZSTD_DECODE_LIMIT = 6 * transport.MAX_UPSTREAM_BODY


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


def strip_reasoning_blobs(body, content_encoding=None):
    """Remove OpenAI-owned reasoning blobs from `input`; None when unchanged.

    `compaction.strip_reasoning_blobs` owns the field semantics: the blob goes,
    and an item left without readable reasoning text goes with it. Only the
    bounded retry reaches this, so a healthy subscription turn keeps the blob
    that `subscription_history.normalize` deliberately preserves.
    """
    raw = body
    encoding = (content_encoding or '').strip().lower()
    if encoding == 'zstd':
        try:
            with zstd.ZstdFile(io.BytesIO(body)) as stream:
                raw = stream.read(ZSTD_DECODE_LIMIT + 1)
        except (OSError, EOFError, ValueError, zstd.ZstdError):
            return None
        if len(raw) > ZSTD_DECODE_LIMIT:
            return None
    elif encoding not in ('', 'identity'):
        return None
    payload = upstream.parse_payload(raw)
    if payload is None:
        return None
    items = payload.get('input')
    if not isinstance(items, list):
        return None
    stripped = comp.strip_reasoning_blobs(items)
    if stripped == items:
        return None
    return json.dumps({**payload, 'input': stripped},
                      separators=(',', ':')).encode('utf-8')


def _copy_prepared(prepared, body):
    headers = {key: value for key, value in prepared.headers.items()
               if key.lower() not in transport.HOP_HEADERS
               and key.lower() != 'content-encoding'}
    return transport.Prepared(prepared.host, prepared.path, headers,
                               body, prepared.tool_names, prepared.provider,
                               prepared.fallback, prepared.output_cap,
                               prepared.context_tokens)


def maybe_retry_unattributable(described, response, raw, metrics, provider,
                               prepared, attempts, log_event):
    """Retry once with the repair its own rejection calls for.

    Returns (response, headers_done, prepared) plus its bounded error body, or
    None when ineligible. The relay handles the retry's actual response through
    its ordinary failure policy.
    """
    code = described[2] if described is not None else None
    responses_400 = (response.status == 400
            and metrics.get('protocol') == provider_defs.RESPONSES)
    unnamed = (responses_400
            and provider.defn.dialect == provider_defs.DIALECT_OPENROUTER
            and described is not None
            and code is None
            and not upstream.is_context_error(raw)
            and upstream.rejection_tool(raw, provider.defn.dialect) is None
            and upstream.rejection_parameter(raw) is None
            and upstream.rejection_reason(raw, provider.defn.dialect)
            == 'the request was rejected')
    # The subscription route forwards the reasoning blobs that
    # `subscription_history.normalize` preserves, and the ChatGPT backend
    # rejects a turn whose replayed blob it will not accept. Repair that one
    # named condition on the retry only.
    encrypted_blob = (responses_400
            and provider.defn.dialect == provider_defs.DIALECT_OPENAI
            and code == 'invalid_encrypted_content'
            and not upstream.is_context_error(raw))
    fields = {'provider': prepared.provider, 'model': metrics.get('model'),
              'repair': 'reasoning_blobs' if encrypted_blob else 'annotation_strip'}
    if metrics.get('request_bytes') is not None:
        fields['request_bytes'] = metrics['request_bytes']
    if not (unnamed or encrypted_blob):
        log_event('annotation_retry', eligible=False, attempted=False,
                  outcome='ineligible', **fields)
        return None
    content_encoding = next(
        (value for key, value in prepared.headers.items()
         if key.lower() == 'content-encoding'), '')
    stripped = (strip_reasoning_blobs(prepared.body, content_encoding)
                if encrypted_blob else strip_annotations(prepared.body))
    if stripped is None:
        log_event('annotation_retry', eligible=True, attempted=False,
                  outcome='unchanged', **fields)
        return None
    if encrypted_blob:
        log_event('upstream_rejected', status=response.status,
                  client_status=described[0], code=code,
                  tool=upstream.rejection_tool(raw, provider.defn.dialect),
                  parameter=upstream.rejection_parameter(raw),
                  serving_endpoint=upstream.serving_endpoint(raw),
                  category='PROVIDER_REJECTED', **metrics)
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
