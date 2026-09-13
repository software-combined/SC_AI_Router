"""Shared HTTP transport leaves (Plan 062). No policy, no model data.

Prepared, hop-header rules, raw stream iteration, and response header relay.
Transport never imports router, claude, registry, or the installer.
"""
import http.client  # noqa: F401 (re-exported for consumer call sites)
import json
import time
import traceback

from . import provider_defs


HOP_HEADERS = {'host', 'connection', 'content-length', 'transfer-encoding',
               'upgrade', 'keep-alive', 'proxy-authorization', 'proxy-authenticate',
               'te', 'trailer', 'cookie'}


class Prepared:
    """Upstream target plus wire body. Built by protocol adapters.

    `fallback` is the optional plan for answering this request elsewhere
    when upstream refuses it (see subscription_fallback); None means the
    refusal is relayed as-is.
    """

    __slots__ = ('host', 'path', 'headers', 'body', 'tool_names', 'provider',
                 'fallback')

    def __init__(self, host, path, headers, body, tool_names, provider,
                 fallback=None):
        self.host, self.path, self.headers = host, path, headers
        self.body, self.tool_names, self.provider = body, tool_names, provider
        self.fallback = fallback


def passthrough(response):
    while chunk := response.read1(65536):
        yield chunk


def post_with_phases(conn, prepared, metrics):
    """POST and wait for headers, recording connect/send/headers phases.

    Each timestamp lands in a finally, so a failure raises with the
    phases recorded so far already in metrics (transport_error
    carries them). Returns (response, headers_done) on success.
    """
    setup_done = time.monotonic()
    try:
        conn.connect()
    finally:
        connect_done = time.monotonic()
        metrics['connect_ms'] = round((connect_done - setup_done) * 1000, 1)
    try:
        conn.request('POST', prepared.path, body=prepared.body,
                     headers=prepared.headers)
    finally:
        send_done = time.monotonic()
        metrics['send_ms'] = round((send_done - connect_done) * 1000, 1)
    try:
        response = conn.getresponse()
    finally:
        headers_done = time.monotonic()
        metrics['headers_ms'] = round((headers_done - send_done) * 1000, 1)
    return response, headers_done


def note_first_data(metrics, headers_done):
    """First upstream read-return; a buffering adapter's TTFB is not provider TTFB."""
    if 'first_data_ms' not in metrics:
        metrics['first_data_ms'] = round((time.monotonic() - headers_done) * 1000, 1)


def note_first_write(metrics, headers_done):
    """First downstream write; forwarding delay, not network TTFB."""
    if 'first_write_ms' not in metrics:
        metrics['first_write_ms'] = round((time.monotonic() - headers_done) * 1000, 1)


def describe_response(response):
    """Fixed-category response shape for metrics; never header strings.

    Returns (kind, encoding) where kind is sse/json/other and encoding
    is identity/gzip/deflate/br/zstd/other. Unknown or absent values
    map to the generic bucket so arbitrary upstream content can never
    reach logs through this path (Plan 060 rule).
    """
    content_type = (response.getheader('Content-Type', '') or '').lower()
    if 'text/event-stream' in content_type:
        kind = 'sse'
    elif 'json' in content_type:
        kind = 'json'
    else:
        kind = 'other'
    encoding = (response.getheader('Content-Encoding', '') or '').strip().lower()
    if encoding in ('', 'identity'):
        encoding = 'identity'
    elif encoding not in ('gzip', 'deflate', 'br', 'zstd'):
        encoding = 'other'
    return kind, encoding


def describe_location(exc):
    """One-line traceback handle for the failing adapter frame."""
    return ';'.join(
        f'{frame.filename.split("/")[-1]}:{frame.lineno}:{frame.name}'
        for frame in traceback.extract_tb(exc.__traceback__, limit=3))


def emit_terminal_failure(wfile, metrics):
    """Best-effort mid-stream terminal frame on Responses SSE only.

    The protocol, not the provider name, decides: a Messages stream carries
    no `response.failed` frame. No-op for non-SSE bodies; a dead socket never
    raises from the error path.
    """
    from .errors import upstream_failed
    if not (metrics.get('stream') is True
            and metrics.get('response_kind') == 'sse'
            and metrics.get('response_encoding') == 'identity'
            and metrics.get('protocol') == provider_defs.RESPONSES):
        # Identity only: appending plaintext to an encoded stream would be
        # undecodable for the client.
        return
    frame = ('event: response.failed\ndata: ' + json.dumps(
        {'type': 'response.failed',
         'response': upstream_failed().body()}) + '\n\n').encode()
    try:
        wfile.write(frame)
        wfile.flush()
    except (OSError, ValueError):
        # Closed-file ValueError plus dead-socket OSError: never raise here.
        pass
    else:
        # Only claim the frame once it is written: the log line must not report
        # a terminal frame the client never received.
        metrics['terminal_source'] = 'router'


def relay_headers(response, send_header, model):
    """Forward upstream headers, pinning openai-model to the requested slug.

    Codex warns on any mismatch with the configured slug, so the upstream
    model name never goes out on that header; /health reports the real one.
    """
    for key, value in response.getheaders():
        if key.lower() in HOP_HEADERS or key.lower() in ('set-cookie', 'openai-model'):
            continue
        send_header(key, value)
    if isinstance(model, str):
        send_header('openai-model', model)
