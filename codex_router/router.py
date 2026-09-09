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
from .credentials import Credentials, ENV_VAR as _CREDENTIALS_ENV_VAR
from . import claude, errors, local_services, providers, setup, transport
from .protocols import owned_paths, select as select_protocol
from .errors import InvalidSize, PreparationError
from .providers import NATIVE_SERVICE_PATHS
from .runtime import MAX_BODY, ROUTER_HOME, VERSION, log_event


class Router(ThreadingHTTPServer):
    daemon_threads = True
    drain_deadline_s = 120

    def __init__(self, state, fileno=None, credentials=None):
        sock = (None if fileno is None else
                socket.fromfd(fileno, socket.AF_INET, socket.SOCK_STREAM))
        if sock is not None and sock.getsockname()[1] != state['port']:
            # A foreign launchd socket (e.g. the CI runner's own Listeners
            # entry) would serve nobody on our port: drop it and fall back
            # to the configured bind instead of going deaf with no error.
            sock.close()
            sock = None
        if sock is None:
            self.allow_reuse_port = True
            super().__init__(('127.0.0.1', state['port']), Handler)
        else:
            super().__init__(('127.0.0.1', state['port']), Handler,
                             bind_and_activate=False)
            self.socket.close()
            self.socket = sock
            self.server_activate()
        self.state = state
        self.lock = threading.Lock()
        self.inflight = 0
        self.draining = False
        self.served_models = {}
        self.credentials = credentials if credentials is not None else Credentials(state, ROUTER_HOME)

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

def _payload_has_image(body):
    """True when the serialized request carries an input_image block; False on doubt."""
    # ponytail: parse, don't substring-match; prose mentioning images must not count.
    try:
        payload = json.loads(body.decode() if isinstance(body, bytes) else '')
    except (ValueError, UnicodeDecodeError, AttributeError):
        return False
    items = payload.get('input') if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return False
    return any(isinstance(item, dict) and isinstance(item.get('content'), list)
               and any(isinstance(block, dict) and block.get('type') == 'input_image'
                       for block in item['content'])
               for item in items)


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass  # Request URLs and upstream credentials must never enter access logs.

    def send_json(self, status, obj, headers=None):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def error(self, err):
        prefix = '/' + self.server.state.get('token', '')
        raw = self.path
        suffix = raw[len(prefix):] if prefix != '/' and raw.startswith(prefix) else '<unrouted>'
        log_event('request_rejected', status=err.status, code=err.code,
                  path=suffix.split('?')[0][:200])
        try:
            self.send_json(err.status, err.body())
        except OSError:
            pass  # Client already disconnected; the event log keeps the record.

    def authorized_path(self):
        # Setup URLs carry their own token plus nonce and enforce same-origin
        # themselves, so the generic rebinding rejection exempts their path.
        if (self.headers.get('Origin')
                and '/setup/' not in self.path.split('?', 1)[0]):
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

    def context_error(self, message, streaming):
        err = errors.context_window(message)
        if not streaming:
            return self.error(err)
        # Codex recognizes context_length_exceeded inside response.failed;
        # a plain HTTP 400/409 does not mark its context full for recovery.
        log_event('request_rejected', status=200, code=err.code)
        body = ('event: response.failed\ndata: ' + json.dumps(
            {'type': 'response.failed', 'response': err.body()}) + '\n\n').encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def do_GET(self):
        path, _ = self.authorized_path()
        if path is None:
            return self.error(errors.forbidden())
        path = path.split('?', 1)[0]
        if path.startswith('/setup/'):
            return setup.serve(self, path[len('/setup/'):], False)
        if path == '/health':
            return self.send_json(200, {'status': 'ok', 'version': VERSION,
                                        'inflight': self.server.inflight,
                                        'draining': self.server.draining,
                                        'served_models': dict(self.server.served_models)})
        if path == '/v1/models':
            return self.send_json(200, claude.models_listing())
        if self.server.draining:
            return self.drain_reject()
        if self.headers.get('Upgrade', '').lower() == 'websocket':
            # Codex explicitly handles 426 by switching this session to HTTP/SSE.
            return self.error(errors.websocket_rejected())
        return self.error(errors.unsupported_route())

    def drain_reject(self):
        return self.retryable_reject(errors.draining())

    def retryable_reject(self, err, retry_after='2'):
        self.send_json(err.status, err.body(), {'Retry-After': retry_after})

    def do_POST(self):
        started = time.monotonic()
        path, via_path = self.authorized_path()
        if path is None:
            return self.error(errors.forbidden())
        path = path.split('?', 1)[0]
        if self.server.draining:
            return self.drain_reject()
        if path == '/shutdown':
            # Portable restart: every supervisor relaunches an exited service,
            # unlike `launchctl kill` which exists only on macOS.
            # Non-daemon like the SIGTERM path, or teardown kills the drain.
            threading.Thread(target=self.server.drain_and_exit, daemon=False).start()
            return self.send_json(200, {'status': 'draining'})
        if path not in owned_paths():
            if path.startswith('/setup/'):
                return setup.serve(self, path[len('/setup/'):], True)
            return self.error(errors.unsupported_route())
        self.connection.settimeout(120)
        try:
            raw, payload, size = self.read_body()
            model = payload.get('model')
            if not isinstance(model, str) and path not in NATIVE_SERVICE_PATHS:
                return self.error(errors.missing_model())
            mode = self.server.state.get('openai_mode', 'subscription')
            policy = select_protocol(self.command, path)
            if policy is None:
                return self.error(errors.unsupported_route())
            provider = policy.select_provider(model, path, self.server.state, mode)
            if provider.name in ('openai-subscription', 'anthropic-subscription') and not via_path:
                return self.error(errors.bearer_for_no_subscription_only())
            compact_call = policy.compaction_call(provider, model, path, payload)
            if compact_call is not None:
                # Compact before prepare(): a rejected effort must not block it.
                # Hold an inflight slot so drain waits for mid-compaction
                # releases. Key lookup stays outside the try so credential
                # errors keep 401/400, not 502.
                key = self.server.credentials.openrouter_key()
                with self.server.lock:
                    self.server.inflight += 1
                try:
                    return self.send_json(200, {'output': compact_call(key)})
                except PreparationError as exc:
                    return self.error(errors.preparation(str(exc)))
                except (OSError, http.client.HTTPException):
                    return self.error(errors.compaction_unavailable())
                finally:
                    with self.server.lock:
                        self.server.inflight -= 1
            try:
                prepared = provider.prepare(model, path, payload, raw,
                                            dict(self.headers), self.server.credentials)
            except local_services.LocalAnswer as exc:
                return self.error(exc)
            if os.environ.get('ROUTER_DEBUG'):
                log_event('provider_selected', provider=provider.name, model=model, path=path)
        except PermissionError as exc:
            return self.error(errors.map_client_error(exc))
        except InvalidSize as exc:
            return self.error(errors.invalid_size(str(exc)))
        except errors.ContextWindowExceeded as exc:
            return self.context_error(str(exc), payload.get('stream') is True)
        except PreparationError as exc:
            return self.error(errors.preparation(str(exc)))
        except LookupError as exc:
            if isinstance(exc, KeyError):
                # Malformed payload/tool-fragment indexing, not keylessness:
                # keep the original payload-error mapping and open no window.
                return self.error(errors.map_client_error(exc))
            setup.open_key_window(self.server, self.server.credentials.home)
            return self.error(errors.credential_problem(
                '%s Open the key setup page to connect an OpenRouter key.' % exc))
        except (ValueError, KeyError, OSError, zstd.ZstdError,
                AttributeError, TypeError) as exc:
            err = errors.map_client_error(exc)
            if err.code == 'INTERNAL_ERROR':
                frames = traceback.extract_tb(exc.__traceback__, limit=3)
                location = ';'.join(
                    f'{frame.filename.split("/")[-1]}:{frame.lineno}:{frame.name}'
                    for frame in frames)
                log_event('request_failed', code=err.code,
                          error_type=type(exc).__name__, location=location)
            return self.error(err)
        _reasoning = payload.get('reasoning')
        metrics = {'provider': prepared.provider,
                   'model': model, 'path': path, 'request_bytes': size,
                   'stream': payload.get('stream') is True,
                   'reasoning_effort': _reasoning.get('effort') if isinstance(_reasoning, dict) else None,
                   'tool_definitions': len(payload.get('tools', [])),
                   'local_prepare_ms': round((time.monotonic() - started) * 1000, 1)}
        log_event('request_started', **metrics)
        with self.server.lock:
            self.server.inflight += 1
        self.relay(provider, prepared, metrics, started)

    def _stored_key_dead(self):
        """True only when the stored key file itself fails check_key on 401/403."""
        if self.server.credentials.env.get(_CREDENTIALS_ENV_VAR, '').strip():
            return False  # The file is not the effective credential.
        if setup.setup_pending(self.server.state):
            return False  # A window is already open; answer the raw 401.
        try:
            stored = (self.server.credentials.home / 'openrouter.key').read_text().strip()
        except OSError:
            return False
        if not stored:
            return True
        try:
            setup.check_key(stored)
        except (ValueError, OSError) as exc:
            return isinstance(exc, setup.KeyRejected) and exc.status in (401, 403)
        return False

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
                    return self.error(exc)
            retry_after = providers.upstream_retry_after(response, prepared, metrics)
            if retry_after is not None:
                return self.retryable_reject(errors.upstream_rate_limited(), retry_after)
            if response.status >= 400:
                raw = response.read()
                if prepared.provider == 'openrouter' and providers.is_context_error(raw):
                    return self.context_error(errors.context_window().message, metrics['stream'])
                if (prepared.provider == 'openrouter'
                        and response.status in (401, 403)
                        and self._stored_key_dead()):
                    setup.open_key_window(self.server, self.server.credentials.home)
                    return self.error(errors.credential_problem(
                        'The stored OpenRouter key was rejected. '
                        'Open the key setup page to connect a new one.'))
                described = providers.describe_failure(
                    None, {'status': response.status, 'body': raw},
                    {'model': metrics.get('model'), 'provider': prepared.provider,
                     'elapsed_ms': round((time.monotonic() - started) * 1000, 1),
                     'timeout_s': 120,
                     'has_image': _payload_has_image(prepared.body)})
                if described is not None:
                    status, message = described
                    log_event('upstream_rejected', status=response.status,
                              client_status=status, **metrics)
                    return self.error(errors.upstream_described(message) if status == 502
                                      else errors.preparation(message))
                self.send_response(response.status)
                transport.relay_headers(response, self.send_header, metrics.get('model'))
                self.send_header('Connection', 'close')
                self.end_headers()
                self.wfile.write(raw)
                self.wfile.flush()
                self.close_connection = True
                return
            metrics['upstream_headers_ms'] = round((time.monotonic() - started) * 1000, 1)
            providers.validate_response(response, prepared)
            self.send_response(response.status)
            transport.relay_headers(response, self.send_header, metrics.get('model'))
            self.send_header('Connection', 'close')
            self.end_headers()
            sent = True
            for chunk in provider.adapt(response, prepared.tool_names, metrics):
                if 'first_chunk_ms' not in metrics:
                    metrics['first_chunk_ms'] = round((time.monotonic() - started) * 1000, 1)
                self.wfile.write(chunk)
                self.wfile.flush()
            log_event('request_completed', **metrics, status=response.status,
                        total_ms=round((time.monotonic() - started) * 1000, 1))
            if metrics.get('served_model'):
                with self.server.lock:
                    self.server.served_models[metrics['model']] = metrics['served_model']
        except (OSError, http.client.HTTPException, ValueError, KeyError) as exc:
            total_ms = round((time.monotonic() - started) * 1000, 1)
            log_event('transport_error',
                        status=response.status if response is not None else None,
                        **metrics, error_type=type(exc).__name__,
                        error_category=exc.msg if isinstance(exc, json.JSONDecodeError) else type(exc).__name__,
                        total_ms=total_ms)
            if not sent:
                described = providers.describe_failure(
                    exc, None,
                    {'model': metrics.get('model'), 'provider': prepared.provider,
                     'host': prepared.host, 'elapsed_ms': total_ms,
                     'timeout_s': 120,
                     'has_image': _payload_has_image(prepared.body)})
                if described is not None:
                    status, message = described
                    self.error(errors.upstream_described(message) if status == 502
                               else errors.preparation(message))
                else:
                    self.error(errors.upstream_failed())
        finally:
            with self.server.lock:
                self.server.inflight -= 1
            conn.close()
            self.close_connection = True
