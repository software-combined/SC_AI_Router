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
import io
import json
from compression import zstd
from . import claude, errors, setup
from .errors import InvalidSize
from .runtime import VERSION


def send_json(handler, status, obj, headers=None):
    body = json.dumps(obj).encode()
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json')
    handler.send_header('Content-Length', str(len(body)))
    for k, v in (headers or {}).items():
        handler.send_header(k, v)
    handler.send_header('Connection', 'close')
    handler.end_headers()
    handler.wfile.write(body)
    handler.close_connection = True


def error(handler, err, *, log_event):
    prefix = '/' + handler.server.state.get('token', '')
    raw = handler.path
    suffix = raw[len(prefix):] if prefix != '/' and raw.startswith(prefix) else '<unrouted>'
    log_event('request_rejected', status=err.status, code=err.code,
              path=suffix.split('?')[0][:200])
    try:
        handler.send_json(err.status, err.body())
    except OSError:
        pass  # Client already disconnected; the event log keeps the record.


def authorized_path(handler):
    # Setup URLs carry their own token plus nonce and enforce same-origin
    # themselves, so the generic rebinding rejection exempts their path.
    if (handler.headers.get('Origin')
            and '/setup/' not in handler.path.split('?', 1)[0]):
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


def context_error(handler, streaming, *, log_event):
    err = errors.context_window()
    if not streaming:
        return handler.error(err)
    # Codex recognizes context_length_exceeded inside response.failed;
    # a plain HTTP 400/409 does not mark its context full for recovery.
    log_event('request_rejected', status=200, code=err.code)
    body = ('event: response.failed\ndata: ' + json.dumps(
        {'type': 'response.failed', 'response': err.body()}) + '\n\n').encode()
    handler.send_response(200)
    handler.send_header('Content-Type', 'text/event-stream')
    handler.send_header('Content-Length', str(len(body)))
    handler.send_header('Connection', 'close')
    handler.end_headers()
    handler.wfile.write(body)
    handler.close_connection = True


def do_get(handler):
    path, _ = handler.authorized_path()
    if path is None:
        return handler.error(errors.forbidden())
    path = path.split('?', 1)[0]
    if path.startswith('/setup/'):
        return setup.serve(handler, path[len('/setup/'):], False)
    if path == '/health':
        return handler.send_json(200, {'status': 'ok', 'version': VERSION,
                                       'inflight': handler.server.inflight,
                                       'draining': handler.server.draining,
                                       'served_models': dict(handler.server.served_models)})
    if path == '/v1/models':
        return handler.send_json(200, claude.models_listing())
    if handler.server.draining:
        return handler.drain_reject()
    if handler.headers.get('Upgrade', '').lower() == 'websocket':
        # Codex explicitly handles 426 by switching this session to HTTP/SSE.
        return handler.error(errors.websocket_rejected())
    return handler.error(errors.unsupported_route())


def read_body(handler, max_body):
    # max_body arrives from the handler so the existing patch point on
    # ai_router.router.MAX_BODY still bounds this read (Plan 128).
    size = int(handler.headers.get('Content-Length', '-1'))
    if size < 0 or size > max_body or handler.headers.get('Transfer-Encoding'):
        raise InvalidSize('Invalid request size')
    body = handler.rfile.read(size)
    encoding = handler.headers.get('Content-Encoding', '')
    if encoding == 'zstd':
        with zstd.ZstdFile(io.BytesIO(body)) as stream:
            decoded = stream.read(max_body + 1)
    else:
        decoded = body
    if len(decoded) > max_body:
        raise InvalidSize('Decoded request is too large')
    return body, json.loads(decoded), size
