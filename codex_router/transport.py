"""Shared HTTP transport leaves (Plan 062). No policy, no model data.

Prepared, hop-header rules, raw stream iteration, and response header relay.
Transport never imports router, claude, registry, or the installer.
"""
import http.client  # noqa: F401 (re-exported for consumer call sites)
import time


HOP_HEADERS = {'host', 'connection', 'content-length', 'transfer-encoding',
               'upgrade', 'keep-alive', 'proxy-authorization', 'proxy-authenticate', 'te', 'trailer'}


class Prepared:
    """Upstream target plus wire body. Built by protocol adapters."""

    __slots__ = ('host', 'path', 'headers', 'body', 'tool_names', 'provider')

    def __init__(self, host, path, headers, body, tool_names, provider):
        self.host, self.path, self.headers = host, path, headers
        self.body, self.tool_names, self.provider = body, tool_names, provider


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
