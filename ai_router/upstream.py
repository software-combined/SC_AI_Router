"""Upstream failure policy (Plan 127 split; behaviour unchanged).

Failure classification, retry handling and response-encoding gates for
requests the router relays upstream. Adapters build requests; this module
decides how an upstream refusal is described to the client.

Pure policy: no dispatch, no model data, no credentials. It may read a
response object but never a request body except the error snapshot the
caller already bounded.
"""
import json
import re

from . import provider_defs
from .runtime import log_event


def _explicit_context_code(data):
    """True only on explicit context-limit fields, never message prose."""
    if not isinstance(data, dict):
        return False
    if data.get('error_type') == 'context_length_exceeded':
        return True
    error = data.get('error')
    if not isinstance(error, dict):
        return False
    if error.get('code') == 'context_length_exceeded':
        return True
    if error.get('error_type') == 'context_length_exceeded':
        return True
    metadata = error.get('metadata')
    raw = metadata.get('raw') if isinstance(metadata, dict) else None
    if isinstance(raw, str):
        try:
            return _explicit_context_code(json.loads(raw))
        except ValueError:
            return False
    return False


def is_context_error(body):
    """Recognize explicit upstream codes, never infer from user-bearing prose."""
    try:
        return _explicit_context_code(json.loads(body))
    except (ValueError, TypeError):
        return False


def upstream_retry_after(response, prepared, metrics):
    """Consume an upstream 429 and return its Retry-After; None otherwise.

    Codex treats a bare 429 as turn-fatal, so the caller must answer 503.
    """
    if response.status != 429:
        return None
    response.read()
    log_event('upstream_rate_limited', provider=prepared.provider, path=metrics['path'])
    return response.getheader('Retry-After', '2')


def _provider_reason(body):
    """(provider_name, fixed_category, wire_tool) from an upstream error body.

    Only structural fragments leave this function: never raw bodies, schemas,
    argument values, secret-bearing text, or arbitrary upstream prose. The
    category is fixed wording chosen from the error shape; the offending tool
    is kept only after the bounded identity match below.
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
    text = None
    if isinstance(raw, str):
        try:
            inner = json.loads(raw)
            text = inner.get('error') if isinstance(inner, dict) else raw
        except ValueError:
            text = raw
    if not isinstance(text, str):
        text = error.get('message') if isinstance(error.get('message'), str) else None
    if not isinstance(text, str) or not text.strip():
        return None
    tool = None
    match = re.search(r'\bns_[0-9a-f]{12}_\S+|\b[a-z][\w.-]*\.[\w-]+\b', text)
    if match:
        tool = match.group(0).rstrip(':,.')
    lowered = text.lower()
    if 'invalid_client_tool_schema' in lowered or 'must be an object' in lowered:
        reason = 'the tool schema was rejected'
    elif 'invalid' in lowered and 'tool' in lowered:
        reason = 'a tool call was rejected'
    else:
        reason = 'the request was rejected'
    return provider, reason, tool


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
    """Name an upstream failure for the client: (status, message) or None.

    Pure: no reads, no logging, no clock. `response` is a snapshot
    {'status': int, 'body': bytes} or None when headers never arrived.
    Unknown shapes return None so the caller keeps existing behavior.
    """
    model = info.get('model', 'the model')
    timeout = info.get('timeout_s', 120)
    if response is not None:
        if response.get('status') == 429:
            return None  # existing Retry-After path owns 429s
        parsed = _provider_reason(response.get('body', b''))
        if parsed is None:
            return None
        provider, reason, tool = parsed
        who = f'upstream {provider}' if provider else 'upstream'
        message = (f'{model} was rejected by {who} '
                   f'(HTTP {response.get("status")}): {reason}. '
                   'Do not retry the unchanged request')
        if tool:
            message += f'; offending tool: {tool}'
        return 409, message
    if isinstance(exc, TimeoutError):
        elapsed = round((info.get('elapsed_ms') or 0) / 1000)
        message = (f'{model} did not answer within {timeout}s '
                   f'(waited {elapsed}s). Retry a shorter turn')
        # Tilde aliases and pinned ids share the vendor prefix.
        if (isinstance(model, str) and model.removeprefix('~').startswith('x-ai/')
                and info.get('has_image')):
            message += '; Grok image turns stall upstream, retry text-only'
        return 502, message
    if isinstance(exc, OSError):
        host = info.get('host')
        if host:
            return 502, f'{model} is unreachable at {host}: check the network connection and retry'
        return 502, f'{model} lost its upstream connection before responding; retry'
    return None
