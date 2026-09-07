"""Local trial: retain Codex subscription authentication; isolate OpenRouter keys."""
import hmac
import http.client
import json
import io
import os
import threading
import time
import traceback
from compression import zstd
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from .runtime import MAX_BODY, VERSION, log_event
from . import providers
from .providers import NATIVE_SERVICE_PATHS, PreparationError


class InvalidSize(ValueError):
    """Request body rejected on size grounds; maps to 413."""


class Credentials:
    """OpenRouter key lookup; read per request so rotation needs no restart."""
    def __init__(self, state):
        self.state = state

    def openrouter_key(self):
        auth = json.loads(Path(self.state['opencode_auth']).read_text())['openrouter']
        if auth['type'] != 'api':
            raise ValueError('OpenCode credential is not an API key')
        return auth['key']


class Router(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, state):
        super().__init__(('127.0.0.1', state['port']), Handler)
        self.state = state
        self.lock = threading.Lock()
        self.inflight = 0
        self.credentials = Credentials(state)

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
        self.send_json(status, {'error': {'message': message, 'type': 'router_error'}})

    def authorized_path(self):
        prefix = '/' + self.server.state['token']
        candidate, sep, _ = self.path[1:].partition('/')
        if self.headers.get('Origin') or not sep or not hmac.compare_digest(candidate, self.server.state['token']):
            return None
        path = self.path[len(prefix):]
        return path.removeprefix('/backend-api/codex')

    def do_GET(self):
        path = self.authorized_path()
        if path is None:
            return self.error(403, 'Forbidden')
        if path == '/health':
            return self.send_json(200, {'status': 'ok', 'version': VERSION,
                                        'inflight': self.server.inflight})
        if self.headers.get('Upgrade', '').lower() == 'websocket':
            # Codex explicitly handles 426 by switching this session to HTTP/SSE.
            return self.error(426, 'Use HTTP streaming for this local trial')
        return self.error(404, 'Unsupported route')

    def do_POST(self):
        started = time.monotonic()
        path = self.authorized_path()
        if path is None:
            return self.error(403, 'Forbidden')
        if path not in NATIVE_SERVICE_PATHS | {'/responses', '/responses/compact'}:
            return self.error(404, 'Unsupported route')
        self.connection.settimeout(120)
        try:
            raw, payload, size = self.read_body()
            model = payload.get('model')
            if not isinstance(model, str) and path not in NATIVE_SERVICE_PATHS:
                return self.error(400, 'Missing model')
            provider = providers.select(model, path, self.server.state.get('openai_models', []))
            if os.environ.get('ROUTER_DEBUG'):
                log_event('provider_selected', provider=provider.name, model=model, path=path)
            if path == '/responses/compact' and provider.name == 'openrouter':
                key = self.server.credentials.openrouter_key()
                try:
                    return self.send_json(200, {'output': provider.compact(model, payload, key)})
                except PreparationError as exc:
                    return self.error(409, str(exc))
                except (OSError, http.client.HTTPException):
                    return self.error(502, 'Compaction summarizer unavailable')
            prepared = provider.prepare(model, path, payload, raw,
                                        dict(self.headers), self.server.credentials)
        except PermissionError as exc:
            return self.error(401, str(exc))
        except InvalidSize as exc:
            return self.error(413, str(exc))
        except PreparationError as exc:
            return self.error(409, str(exc))
        except (ValueError, KeyError, OSError, TypeError, AttributeError, zstd.ZstdError):
            return self.error(400, 'Invalid model, payload, or local authentication configuration')
        metrics = {'provider': prepared.provider,
                   'model': model, 'path': path, 'request_bytes': size,
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
        try:
            conn.request('POST', prepared.path, body=prepared.body, headers=prepared.headers)
            response = conn.getresponse()
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
            log_event('transport_error', **metrics, error_type=type(exc).__name__,
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
