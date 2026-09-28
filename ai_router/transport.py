"""Shared HTTP transport leaves (Plan 062). No policy, no model data.

Prepared, hop-header rules, raw stream iteration, and response header relay.
Transport never imports router, claude, registry, or the installer.
"""
import http.client  # noqa: F401 (re-exported for consumer call sites)
import json
import time
import traceback
from collections import namedtuple

from . import messages_errors, provider_defs, request_evidence
from .errors import InvalidSize


HOP_HEADERS = {'host', 'connection', 'content-length', 'transfer-encoding',
               'upgrade', 'keep-alive', 'proxy-authorization', 'proxy-authenticate',
               'te', 'trailer', 'cookie'}


class ResponseFormat(namedtuple('ResponseFormat', 'protocol operation stream kind encoding')):
    """Immutable wire facts for one HTTP response attempt, separate from logs."""
    __slots__ = ()

    @classmethod
    def capture(cls, request, response):
        return cls(request.protocol, request.operation, request.stream, *describe_response(response))


class Prepared:
    """Upstream target plus wire body. Built by protocol adapters.

    `fallback` is the optional plan for answering this request elsewhere
    when upstream refuses it (see subscription_fallback); None means the
    refusal is relayed as-is. `context` is the request's resolved snapshot
    (request_context.Resolved) the adapter prepared against.
    `decoded_body_bytes` is what `body` decodes to: the size ingress decoded
    for the client's own compressed bytes, len(body) for a body the adapter
    serialized; `len(body)` is always the wire size.
    """

    __slots__ = ('host', 'path', 'headers', 'body', 'tool_names', 'provider',
                 'fallback', 'output_cap', 'context_tokens', 'context',
                 'decoded_body_bytes')

    def __init__(self, host, path, headers, body, tool_names, provider,
                 fallback=None, output_cap=None, context_tokens=None, context=None,
                 decoded_body_bytes=None):
        self.host, self.path, self.headers = host, path, headers
        self.body, self.tool_names, self.provider = body, tool_names, provider
        self.fallback, self.context = fallback, context
        self.decoded_body_bytes = decoded_body_bytes
        # The output cap this request asks upstream for, when the adapter
        # computes one; None when the client's own body passes through.
        self.output_cap = output_cap
        # Input tokens this thread carries, when the adapter computed one;
        # None keeps the provider's own usage on the wire.
        self.context_tokens = context_tokens


# The local resource ceiling on one request, on the wire and decoded, for
# every route and encoding. It bounds what one turn may make this router hold
# (a native turn is forwarded whole, and a zstd one may decode this far so
# prepare can slim released-tool schemas); it is no provider's or
# subscription's limit. runtime.MAX_BODY stays the ordinary threshold.
MAX_REQUEST_BYTES = 96 * 1024 * 1024


def encoded(headers):
    """True when `headers` declare a Content-Encoding other than identity."""
    return any(key.lower() == 'content-encoding'
               and value.strip().lower() not in ('', 'identity')
               for key, value in headers.items())


def request_bytes(prepared):
    """The larger of one prepared body's wire and decoded sizes.

    InvalidSize past MAX_REQUEST_BYTES, and for a compressed body that does
    not carry its decoded size: its wire length alone would under-count it.
    """
    wire, decoded = len(prepared.body), prepared.decoded_body_bytes
    if decoded is None:
        if encoded(prepared.headers):
            raise InvalidSize('Invalid request size')
        decoded = wire
    if max(wire, decoded) > MAX_REQUEST_BYTES:
        raise InvalidSize('Decoded request is too large')
    return max(wire, decoded)


def passthrough(response):
    while chunk := response.read1(65536):
        yield chunk


MAX_UPSTREAM_BODY = 16 * 1024 * 1024  # matches runtime.MAX_BODY; pinned by a test
ERROR_BODY_LIMIT = 1024 * 1024  # an error envelope is parsed, never relayed whole
# Operation timeout on the upstream socket, not a turn deadline.
UPSTREAM_TIMEOUT_S = 120


def read_capped(response, limit):
    """The whole body, or ValueError once it exceeds `limit` bytes.

    Reads in read1 pieces so a hostile upstream cannot make one call
    allocate the full body before the check runs.
    """
    chunks, total = [], 0
    read1 = getattr(response, 'read1', None)
    if read1 is None:
        # Test doubles shaped like the old whole-body surface; the real
        # http.client.HTTPResponse always offers read1.
        body = response.read()
        if len(body) > limit:
            raise ValueError('upstream body exceeds %d bytes' % limit)
        return body
    while piece := read1(65536):
        total += len(piece)
        if total > limit:
            raise ValueError('upstream body exceeds %d bytes' % limit)
        chunks.append(piece)
    return b''.join(chunks)


def post_with_phases(conn, prepared, metrics):
    """POST and wait for headers, recording connect/send/headers phases.

    Each timestamp lands in a finally, so a failure raises with the
    phases recorded so far already in metrics (transport_error
    carries them). Returns (response, headers_done) on success. Every send
    passes here, so no body past the request ceiling ever leaves.
    """
    request_bytes(prepared)
    setup_done = time.monotonic()
    request_evidence.phase(metrics, 'connect')
    try:
        conn.connect()
    finally:
        connect_done = time.monotonic()
        metrics['connect_ms'] = round((connect_done - setup_done) * 1000, 1)
    request_evidence.phase(metrics, 'send')
    try:
        conn.request('POST', prepared.path, body=prepared.body,
                     headers=prepared.headers)
    finally:
        send_done = time.monotonic()
        metrics['send_ms'] = round((send_done - connect_done) * 1000, 1)
    request_evidence.phase(metrics, 'headers')
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


def write_full(wfile, data):
    """Write one complete body or raise on an explicit short write."""
    written = wfile.write(data)
    if written is not None and written != len(data):
        raise OSError('short client write')
    wfile.flush()


def emit_terminal_failure(wfile, response_format):
    """Best-effort native terminal on a repairable identity event stream."""
    from .errors import upstream_failed
    if not (response_format.stream is True
            and response_format.kind == 'sse'
            and response_format.encoding == 'identity'
            and response_format.protocol in (provider_defs.RESPONSES, provider_defs.MESSAGES)):
        # Identity only: appending plaintext to an encoded stream would be
        # undecodable for the client.
        return False
    messages = response_format.protocol == provider_defs.MESSAGES
    native = 'error' if messages else 'response.failed'
    body = (messages_errors.render(upstream_failed()).body() if messages else
            {'type': native, 'response': upstream_failed().body()})
    frame = ('event: ' + native + '\ndata: ' + json.dumps(body) + '\n\n').encode()
    try:
        write_full(wfile, frame)
    except (OSError, ValueError):
        # Closed-file ValueError plus dead-socket OSError: never raise here.
        return False
    # The caller records its terminal only after successful delivery.
    return True


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
