"""Local trial: retain Codex subscription authentication; isolate OpenRouter keys."""
import hmac
import http.client
import json
import io
import os
import socket
import threading
import time
import traceback
from compression import zstd
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .credentials import Credentials
from .runtime import MAX_BODY, ROUTER_HOME, VERSION, log_event
from . import local_services, providers
from .providers import NATIVE_SERVICE_PATHS, PreparationError


class InvalidSize(ValueError):
    """Request body rejected on size grounds; maps to 413."""


class Router(ThreadingHTTPServer):
    daemon_threads = True
    drain_deadline_s = 120

    def __init__(self, state, fileno=None):
        if fileno is None:
            self.allow_reuse_port = True
            super().__init__(('127.0.0.1', state['port']), Handler)
        else:
            super().__init__(('127.0.0.1', state['port']), Handler,
                             bind_and_activate=False)
            self.socket.close()
            self.socket = socket.fromfd(fileno, socket.AF_INET, socket.SOCK_STREAM)
            self.server_activate()
        self.state = state
        self.lock = threading.Lock()
        self.inflight = 0
        self.draining = False
        self.credentials = Credentials(state, ROUTER_HOME)

    def drain_and_exit(self):
        self.draining = True
        log_event('draining', inflight=self.inflight)
        self.shutdown()
        deadline = time.monotonic() + self.drain_deadline_s
        while self.inflight > 0 and time.monotonic() < deadline:
            time.sleep(0.5)
        forced = self.inflight > 0
        log_event('exit', inflight=self.inflight, forced=forced)
        os._exit(0)

class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass  # Request URLs and upstream credentials must never enter access logs.

    def send_json(self, status, obj):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def error(self, status, message):
        if 400 <= status <= 599:
            prefix = '/' + self.server.state.get('token', '')
            raw = self.path
            suffix = raw[len(prefix):] if prefix != '/' and raw.startswith(prefix) else '<unrouted>'
            log_event('request_rejected', status=status, reason=message,
                      path=suffix.split('?')[0][:200])
        try:
            self.send_json(status, {'error': {'message': message, 'type': 'router_error'}})
        except OSError:
            pass  # Client already disconnected; the event log keeps the record.

    def authorized_path(self):
        if self.headers.get('Origin'):
            return None, False
        prefix = '/' + self.server.state['token']
        candidate, sep, _ = self.path[1:].partition('/')
        if sep and hmac.compare_digest(candidate, self.server.state['token']):
            return self.path[len(prefix):].removeprefix('/backend-api/codex'), True
        header = self.headers.get('Authorization', '')
        if header.startswith('Bearer ') and hmac.compare_digest(
                header[len('Bearer '):], self.server.state['token']):
            return self.path.removeprefix('/backend-api/codex'), False
        return None, False

    def do_GET(self):
        path, _ = self.authorized_path()
        if path is None:
            return self.error(403, 'Forbidden')
        if path == '/health':
            return self.send_json(200, {'status': 'ok', 'version': VERSION,
                                        'inflight': self.server.inflight,
                                        'draining': self.server.draining})
        if self.server.draining:
            return self.drain_reject()
        if self.headers.get('Upgrade', '').lower() == 'websocket':
            # Codex explicitly handles 426 by switching this session to HTTP/SSE.
            return self.error(426, 'Use HTTP streaming for this local trial')
        return self.error(404, 'Unsupported route')

    def drain_reject(self):
        body = json.dumps({'error': {'message': 'Server draining',
                                     'type': 'router_error'}}).encode()
        self.send_response(503)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Retry-After', '2')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def do_POST(self):
        started = time.monotonic()
        path, via_path = self.authorized_path()
        if path is None:
            return self.error(403, 'Forbidden')
        if self.server.draining:
            return self.drain_reject()
        if path not in NATIVE_SERVICE_PATHS | {'/responses', '/responses/compact'}:
            return self.error(404, 'Unsupported route')
        self.connection.settimeout(120)
        try:
            raw, payload, size = self.read_body()
            model = payload.get('model')
            if not isinstance(model, str) and path not in NATIVE_SERVICE_PATHS:
                return self.error(400, 'Missing model')
            mode = self.server.state.get('openai_mode', 'subscription')
            provider = providers.select(
                model, path, self.server.state.get('openai_models', []), mode)
            if provider.name == 'openai-subscription' and not via_path:
                return self.error(401, 'Bearer auth is for no-subscription mode only')
            if path == '/responses/compact' and provider.name == 'openrouter':
                # Compact raw history before prepare(): a rejected effort must not block it.
                # Hold an inflight slot so drain waits for mid-compaction releases. Key
                # lookup stays outside the try so credential errors keep 401/400, not 502.
                key = self.server.credentials.openrouter_key()
                with self.server.lock:
                    self.server.inflight += 1
                try:
                    return self.send_json(200, {'output': provider.compact(model, payload, key)})
                except PreparationError as exc:
                    return self.error(409, str(exc))
                except (OSError, http.client.HTTPException):
                    return self.error(502, 'Compaction summarizer unavailable')
                finally:
                    with self.server.lock:
                        self.server.inflight -= 1
            try:
                prepared = provider.prepare(model, path, payload, raw,
                                            dict(self.headers), self.server.credentials)
            except local_services.LocalAnswer as exc:
                return self.error(exc.status, exc.message)
            if os.environ.get('ROUTER_DEBUG'):
                log_event('provider_selected', provider=provider.name, model=model, path=path)
        except PermissionError as exc:
            return self.error(401, str(exc))
        except InvalidSize as exc:
            return self.error(413, str(exc))
        except PreparationError as exc:
            return self.error(409, str(exc))
        except (ValueError, KeyError, LookupError, OSError, TypeError, AttributeError, zstd.ZstdError):
            return self.error(400, 'Invalid model, payload, or local authentication configuration')
        _reasoning = payload.get('reasoning')
        metrics = {'provider': prepared.provider,
                   'model': model, 'path': path, 'request_bytes': size,
                   'reasoning_effort': _reasoning.get('effort') if isinstance(_reasoning, dict) else None,
                   'tool_definitions': len(payload.get('tools', [])),
                   'local_prepare_ms': round((time.monotonic() - started) * 1000, 1)}
        log_event('request_started', **metrics)
        with self.server.lock:
            self.server.inflight += 1
        self.relay(provider, prepared, metrics, started)

    def read_body(self):
        size = int(self.headers.get('Content-Length', '-1'))
        if size < 0 or size > MAX_BODY or self.headers.get('Transfer-Encoding'):
            raise InvalidSize('Invalid request size')
        body = self.rfile.read(size)
        encoding = self.headers.get('Content-Encoding', '')
        if encoding == 'zstd':
            with zstd.ZstdFile(io.BytesIO(body)) as stream:
                decoded = stream.read(MAX_BODY + 1)
        else:
            decoded = body
        if len(decoded) > MAX_BODY:
            raise InvalidSize('Decoded request is too large')
        return body, json.loads(decoded), size

    def relay(self, provider, prepared, metrics, started):
        conn = http.client.HTTPSConnection(prepared.host, timeout=120)
        sent = False
        response = None
        try:
            conn.request('POST', prepared.path, body=prepared.body, headers=prepared.headers)
            response = conn.getresponse()
            if (prepared.provider == 'openai-subscription' and metrics['path'] in NATIVE_SERVICE_PATHS
                    and response.status in (401, 403)):
                response.read()
                log_event('native_upstream_rejected', path=metrics['path'],
                          upstream_status=response.status)
                try:
                    local_services.answer(metrics['path'])
                except local_services.LocalAnswer as exc:
                    return self.error(exc.status, exc.message)
            metrics['upstream_headers_ms'] = round((time.monotonic() - started) * 1000, 1)
            self.send_response(response.status)
            for k, v in response.getheaders():
                if k.lower() not in providers.HOP_HEADERS and k.lower() != 'set-cookie':
                    self.send_header(k, v)
            self.send_header('Connection', 'close')
            self.end_headers()
            sent = True
            for chunk in provider.adapt(response, prepared.tool_names):
                if 'first_chunk_ms' not in metrics:
                    metrics['first_chunk_ms'] = round((time.monotonic() - started) * 1000, 1)
                self.wfile.write(chunk)
                self.wfile.flush()
            log_event('request_completed', **metrics, status=response.status,
                        total_ms=round((time.monotonic() - started) * 1000, 1))
        except (OSError, http.client.HTTPException, ValueError, KeyError) as exc:
            log_event('transport_error',
                        status=response.status if response is not None else None,
                        **metrics, error_type=type(exc).__name__,
                        error_category=exc.msg if isinstance(exc, json.JSONDecodeError) else type(exc).__name__,
                        traceback=traceback.format_exc(limit=3)[-4000:],
                        total_ms=round((time.monotonic() - started) * 1000, 1))
            if not sent:
                self.error(502, 'Upstream request failed')
        finally:
            with self.server.lock:
                self.server.inflight -= 1
            conn.close()
            self.close_connection = True
