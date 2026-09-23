"""HTTP ingress: auth, body limits, GET routes and error shaping (Plan 128).

Collaborator behind `ai_router.router.Handler`. The bodies moved here
verbatim from `Handler` with no behaviour change; the handler keeps thin
wrappers so the public method names used by tests stay valid. The handler
stays the router: new ingress validation goes here.

`log_event` is injected by the handler so a test patching
`ai_router.router.log_event` keeps seeing this module's events; always call
the injected object, never a fresh import.
"""
import hmac
import http.client
import io
import json
import secrets
from compression import zstd
from . import errors, model_prompt_page, protocols, setup, sse, subscription_discovery
from .errors import InvalidSize, OversizeBusy
from .runtime import MAX_DECODE_FACTOR, VERSION


def send_json(handler, status, obj, headers=None):
    body = json.dumps(obj).encode()
    try:
        handler.send_response(status)
        handler.send_header('Content-Type', 'application/json')
        handler.send_header('Content-Length', str(len(body)))
        for k, v in (headers or {}).items():
            handler.send_header(k, v)
        handler.send_header('Connection', 'close')
        handler.end_headers()
        handler.wfile.write(body)
    except OSError:
        pass  # Client already disconnected; nothing more can be delivered.
    finally:
        handler.close_connection = True


def send_compaction_stream(handler, output):
    """Send one local V2 compaction item in the Responses event stream."""
    if not isinstance(output, list) or len(output) != 1 \
            or not isinstance(output[0], dict):
        raise ValueError('Compaction output must contain one item')
    item = output[0]
    response = {'id': 'resp_' + secrets.token_hex(8),
                'object': 'response', 'status': 'completed',
                'output': [item]}
    events = ({'type': 'response.output_item.done', 'output_index': 0,
               'item': item},
              {'type': 'response.completed', 'response': response})
    # Serialize every frame before sending headers: post-start failures cannot
    # be remapped to a second JSON response.
    body = b''.join(sse.frame(json.dumps(event).encode()) for event in events)
    try:
        handler.send_response(200)
        handler.send_header('Content-Type', 'text/event-stream')
        handler.send_header('Content-Length', str(len(body)))
        handler.send_header('Connection', 'close')
        handler.end_headers()
        handler.wfile.write(body)
    except (OSError, http.client.HTTPException):
        pass  # Client already disconnected after the single response began.
    finally:
        handler.close_connection = True


MAX_LOG_DETAIL = 200


def error(handler, err, *, log_event, retry_after=None):
    """Log the rejection, then answer it. `detail` is the log's copy of the
    technical reason the plain message leaves out; every refusal, retryable
    or not, leaves one line here."""
    prefix = '/' + handler.server.state.get('token', '')
    raw = handler.path
    suffix = raw[len(prefix):] if prefix != '/' and raw.startswith(prefix) else '<unrouted>'
    fields = {'status': err.status, 'code': err.code,
              'path': suffix.split('?')[0][:200]}
    detail = getattr(err, 'detail', None)
    if detail:
        fields['detail'] = str(detail)[:MAX_LOG_DETAIL]
    if retry_after:
        fields['retry_after'] = retry_after
    log_event('request_rejected', **fields)
    try:
        handler.send_json(err.status, err.body(),
                          {'Retry-After': retry_after} if retry_after else None)
    except OSError:
        pass  # Client already disconnected; the event log keeps the record.


def authorized_path(handler):
    if not _loopback_host(handler):
        return None, False
    # Setup and prompt URLs carry their own token plus nonce and enforce
    # same-origin themselves, so the generic rebinding rejection exempts
    # their paths.
    if handler.headers.get('Origin'):
        target = handler.path.split('?', 1)[0]
        if '/setup/' not in target and '/model-prompt/' not in target:
            return None, False
    prefix = '/' + handler.server.state['token']
    token = handler.server.state['token'].encode()
    candidate, sep, _ = handler.path[1:].partition('/')
    # Byte compares (Plan 136): compare_digest rejects non-ASCII str with
    # TypeError, and latin-1 ingress input can carry bytes 0x80-0xFF.
    if sep and hmac.compare_digest(candidate.encode('iso-8859-1'), token):
        return handler.path[len(prefix):].removeprefix('/backend-api/codex'), True
    header = handler.headers.get('Authorization', '')
    if header.startswith('Bearer ') and hmac.compare_digest(
            header[len('Bearer '):].encode('iso-8859-1'), token):
        return handler.path.removeprefix('/backend-api/codex'), False
    return None, False


def _loopback_host(handler):
    """False when Host names anything but the loopback interface.

    Rebinding reaches the loopback through a name the attacker controls, and
    a browser always sends Host even on the GETs that carry no Origin. This
    is defence in depth: the path token stays the primary control, and a
    Host-less HTTP/1.0 client is still answered.
    """
    name = (handler.headers.get('Host') or '').split(':', 1)[0].strip().lower()
    return not name or name in ('127.0.0.1', 'localhost')


def context_error(handler, streaming, *, log_event):
    err = errors.context_window()
    if not streaming:
        return handler.error(err)
    # Codex recognizes context_length_exceeded inside response.failed;
    # a plain HTTP 400/409 does not mark its context full for recovery.
    log_event('request_rejected', status=200, code=err.code)
    body = ('event: response.failed\ndata: ' + json.dumps(
        {'type': 'response.failed', 'response': err.body()}) + '\n\n').encode()
    try:
        handler.send_response(200)
        handler.send_header('Content-Type', 'text/event-stream')
        handler.send_header('Content-Length', str(len(body)))
        handler.send_header('Connection', 'close')
        handler.end_headers()
        handler.wfile.write(body)
    except OSError:
        pass  # Client already disconnected after the stream was requested.
    finally:
        handler.close_connection = True


def do_get(handler):
    path, _ = handler.authorized_path()
    if path is None:
        return handler.error(errors.forbidden())
    path, _, query = path.partition('?')
    if path == '/models':
        return subscription_discovery.serve(handler, query)
    if path.startswith('/setup/'):
        return setup.serve(handler, path[len('/setup/'):], False)
    if path == '/model-prompt':
        return model_prompt_page.handle_check(handler)
    if path.startswith('/model-prompt/'):
        return model_prompt_page.handle_page(
            handler, path[len('/model-prompt/'):], False)
    if path == '/health':
        from . import availability as _availability
        from . import provider_defs as _defs
        snap = _availability.current()
        region = handler.server.state.get('openrouter_region', 'global')
        if not _defs.valid_region(region):
            region = 'global'
        return handler.send_json(200, {'status': 'ok', 'version': VERSION,
                                       'inflight': handler.server.inflight,
                                       'max_inflight': handler.server.max_inflight,
                                       'draining': handler.server.draining,
                                       'served_models': dict(handler.server.served_models),
                                       'openrouter_region': region,
                                       'openrouter_host': _defs.region_host(
                                           _defs.DEFAULT_EXTERNAL, region),
                                       'models_availability': (
                                           None if snap is None else {
                                               'models': len(snap.get('models') or ()),
                                               'fetched_at': snap.get('fetched_at')})})
    if path == '/v1/models':
        listing = protocols.listing('GET', path,
                                    handler.server.state.get('allowed_models'))
        return handler.send_json(200, listing)
    if handler.server.draining:
        return handler.drain_reject()
    if handler.headers.get('Upgrade', '').lower() == 'websocket':
        # Codex explicitly handles 426 by switching this session to HTTP/SSE.
        return handler.error(errors.websocket_rejected())
    return handler.error(errors.unsupported_route())


def read_body(handler, max_body, oversize_guard=None):
    # max_body arrives from the handler so the existing patch point on
    # ai_router.router.MAX_BODY still bounds this read (Plan 128).
    # `oversize_guard` is asked on the declared size and again on the decoded
    # size, so a body past the ordinary cap is read or expanded only while the
    # slot is free: the schema-heavy turns that need the headroom compress at
    # ratios no declared-size check can predict.
    size = int(handler.headers.get('Content-Length', '-1'))
    encoding = handler.headers.get('Content-Encoding', '')
    # zstd may expand past max_body so prepare can slim tool_search schemas, and
    # a compressed body past max_body is that same shape: the 2026-09-18 turn
    # (17.6 MB on the wire) was refused here as a framing error before the trim
    # that could have served it ever ran. Read it to the decode ceiling and let
    # the decoded size decide, which is what the ceiling exists for.
    limit = max_body * MAX_DECODE_FACTOR if encoding == 'zstd' else max_body
    if size < 0 or size > limit or handler.headers.get('Transfer-Encoding'):
        raise InvalidSize('Invalid request size')
    # One oversized body in memory at a time: the declared size asks before the
    # read, the decoded size asks again before the expansion.
    if size > max_body and oversize_guard is not None and not oversize_guard():
        raise OversizeBusy()
    body = handler.rfile.read(size)
    if encoding == 'zstd':
        with zstd.ZstdFile(io.BytesIO(body)) as stream:
            decoded = stream.read(max_body + 1)
            if len(decoded) > max_body:
                if oversize_guard is not None and not oversize_guard():
                    raise OversizeBusy()
                decoded += stream.read(limit - max_body + 1)
    else:
        decoded = body
    if len(decoded) > limit:
        raise InvalidSize('Decoded request is too large')
    return body, json.loads(decoded), size, len(decoded)
