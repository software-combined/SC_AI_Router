"""Local trial: retain client subscription authentication; isolate provider keys."""
import hmac
import http.client
import json
import io
import os
import socket
import threading
import time
from compression import zstd
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .credentials import Credentials
from . import (capabilities, claude, errors, local_services, provider_defs,
               setup, subscription_fallback, transport, upstream)
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

def _payload_has_image(payload):
    """True when the parsed turn carries an input_image block; False on doubt."""
    # ponytail: walk the parsed payload, don't substring-match or re-parse the body;
    # prose mentioning images must not count.
    if not isinstance(payload, dict):
        return False
    return capabilities.has_images(payload.get('input'))


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    timeout = 120

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
        token = self.server.state['token'].encode()
        candidate, sep, _ = self.path[1:].partition('/')
        # Byte compares (Plan 136): compare_digest rejects non-ASCII str with
        # TypeError, and latin-1 ingress input can carry bytes 0x80-0xFF.
        if sep and hmac.compare_digest(candidate.encode('iso-8859-1'), token):
            return self.path[len(prefix):].removeprefix('/backend-api/codex'), True
        header = self.headers.get('Authorization', '')
        if header.startswith('Bearer ') and hmac.compare_digest(
                header[len('Bearer '):].encode('iso-8859-1'), token):
            return self.path.removeprefix('/backend-api/codex'), False
        return None, False

    def context_error(self, streaming):
        err = errors.context_window()
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
        # One slot spans read_body, prepare and relay; rejects above return first.
        with self.server.lock:
            self.server.inflight += 1
        try:
            return self._owned_post(path, via_path, started)
        finally:
            with self.server.lock:
                self.server.inflight -= 1

    def _owned_post(self, path, via_path, started):
        provider = None
        self.connection.settimeout(120)
        try:
            raw, payload, size = self.read_body()
            read_done = time.monotonic()
            # Snapshot before provider.prepare mutates or strips the payload.
            has_image = _payload_has_image(payload)
            model = payload.get('model')
            if not isinstance(model, str) and path not in NATIVE_SERVICE_PATHS:
                return self.error(errors.missing_model())
            mode = self.server.state.get('openai_mode', 'subscription')
            policy = select_protocol(self.command, path)
            if policy is None:
                return self.error(errors.unsupported_route())
            provider = policy.select_provider(model, path, self.server.state, mode)
            if provider.kind == provider_defs.SUBSCRIPTION and not via_path:
                return self.error(errors.bearer_for_no_subscription_only())
            compact_call = policy.compaction_call(provider, model, path, payload)
            if compact_call is not None:
                # Compact before prepare(): a rejected effort must not block it.
                # Key lookup stays outside the send try so credential
                # errors keep 401/400, not 502.
                key = self.server.credentials.key_for(provider.defn.id)
                try:
                    return self.send_json(200, {'output': compact_call(key)})
                except PreparationError as exc:
                    return self.error(errors.preparation(str(exc)))
                except (OSError, http.client.HTTPException):
                    return self.error(errors.compaction_unavailable())
            try:
                prepared = subscription_fallback.prepare(provider, model, path, payload,
                                                         raw, dict(self.headers), self.server)
            except local_services.LocalAnswer as exc:
                return self.error(exc)
            if os.environ.get('ROUTER_DEBUG'):
                log_event('provider_selected', provider=provider.name, model=model, path=path)
        except PermissionError as exc:
            return self.error(errors.map_client_error(exc))
        except InvalidSize as exc:
            return self.error(errors.invalid_size(str(exc)))
        except PreparationError as exc:
            return self.error(errors.preparation(str(exc)))
        except LookupError as exc:
            if isinstance(exc, KeyError):
                # Malformed payload/tool-fragment indexing, not keylessness:
                # keep the original payload-error mapping and open no window.
                return self.error(errors.map_client_error(exc))
            defn = provider.defn if provider is not None else None
            setup.open_key_window(self.server, self.server.credentials.home,
                                  defn.id if defn is not None else None)
            return self.error(errors.credential_problem(
                '%s Open the key setup page to connect a %s key.'
                % (exc, provider_defs.label_for(
                    defn.id if defn is not None else provider_defs.DEFAULT_EXTERNAL))))
        except (ValueError, KeyError, OSError, zstd.ZstdError,
                AttributeError, TypeError) as exc:
            err = errors.map_client_error(exc)
            if err.code == 'INTERNAL_ERROR':
                log_event('request_failed', code=err.code,
                          error_type=type(exc).__name__,
                          location=transport.describe_location(exc))
            return self.error(err)
        _reasoning = payload.get('reasoning')
        prepare_done = time.monotonic()
        metrics = {'provider': prepared.provider,
                   'protocol': policy.name,
                   'model': model, 'path': path, 'request_bytes': size,
                   'stream': payload.get('stream') is True,
                   'reasoning_effort': _reasoning.get('effort') if isinstance(_reasoning, dict) else None,
                   'tool_definitions': len(payload.get('tools', [])),
                   'local_prepare_ms': round((time.monotonic() - started) * 1000, 1),
                   # Per-phase detail; cumulative fields keep their meaning.
                   'read_ms': round((read_done - started) * 1000, 1),
                   'prepare_ms': round((prepare_done - read_done) * 1000, 1)}
        log_event('request_started', **metrics)
        self.relay(provider, prepared, metrics, started, has_image)

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

    def relay(self, provider, prepared, metrics, started, has_image=False):
        conn = http.client.HTTPSConnection(prepared.host, timeout=120)
        sent = False
        response = None
        try:
            # Phases land inside post_with_phases even on failure.
            response, headers_done = transport.post_with_phases(
                conn, prepared, metrics)
            if (provider.defn.dialect == 'openai' and metrics['path'] in NATIVE_SERVICE_PATHS
                    and response.status in (401, 403)):
                response.read()
                log_event('native_upstream_rejected', path=metrics['path'],
                          upstream_status=response.status)
                try:
                    local_services.answer(metrics['path'])
                except local_services.LocalAnswer as exc:
                    return self.error(exc)
            retry_after = upstream.upstream_retry_after(response, prepared, metrics)
            if retry_after is not None:
                return subscription_fallback.refused(self, prepared, retry_after, metrics, started)
            if response.status >= 400:
                raw = response.read()
                transport.note_first_data(metrics, headers_done)
                # Gate the terminal-frame path on the protocol as well: the
                # Messages ingress shares the openrouter dialect but has no
                # Responses failure frame to send.
                if (provider.defn.dialect == 'openrouter'
                        and metrics.get('protocol') == provider_defs.RESPONSES
                        and upstream.is_context_error(raw)):
                    return self.context_error(metrics['stream'])
                if (provider.defn.dialect == 'openrouter'
                        and response.status in (401, 403)
                        and metrics.get('protocol') == provider_defs.RESPONSES
                        and self.server.credentials.key_rejected(prepared.provider)):
                    setup.open_key_window(self.server, self.server.credentials.home,
                                          prepared.provider)
                    label = provider_defs.label_for(prepared.provider)
                    return self.error(errors.credential_problem(
                        f'The stored {label} key was rejected. '
                        'Open the key setup page to connect a new one.'))
                described = upstream.describe_failure(
                    None, {'status': response.status, 'body': raw},
                    {'model': metrics.get('model'), 'provider': prepared.provider,
                     'elapsed_ms': round((time.monotonic() - started) * 1000, 1),
                     'timeout_s': 120,
                     'has_image': has_image})
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
            metrics['response_kind'], metrics['response_encoding'] = transport.describe_response(response)
            upstream.validate_response(response, prepared)
            self.send_response(response.status)
            transport.relay_headers(response, self.send_header, metrics.get('model'))
            self.send_header('Connection', 'close')
            self.end_headers()
            sent = True
            for chunk in provider.adapt(response, prepared.tool_names, metrics):
                if 'first_chunk_ms' not in metrics:
                    metrics['first_chunk_ms'] = round((time.monotonic() - started) * 1000, 1)
                transport.note_first_data(metrics, headers_done)
                self.wfile.write(chunk)
                self.wfile.flush()
                transport.note_first_write(metrics, headers_done)
            log_event('request_completed', **metrics, status=response.status,
                        total_ms=round((time.monotonic() - started) * 1000, 1))
            if metrics.get('served_model'):
                with self.server.lock:
                    self.server.served_models[metrics['model']] = metrics['served_model']
        except (OSError, http.client.HTTPException, ValueError, KeyError,
                TypeError, AttributeError) as exc:
            total_ms = round((time.monotonic() - started) * 1000, 1)
            log_event('transport_error',
                        status=response.status if response is not None else None,
                        **metrics, error_type=type(exc).__name__,
                        error_category=exc.msg if isinstance(exc, json.JSONDecodeError) else type(exc).__name__,
                        location=transport.describe_location(exc),
                        total_ms=total_ms)
            if sent:  # best-effort terminal frame on Responses SSE
                transport.emit_terminal_failure(self.wfile, metrics)
            else:
                described = upstream.describe_failure(
                    exc, None,
                    {'model': metrics.get('model'), 'provider': prepared.provider,
                     'host': prepared.host, 'elapsed_ms': total_ms,
                     'timeout_s': 120,
                     'has_image': has_image})
                if described is not None:
                    status, message = described
                    self.error(errors.upstream_described(message) if status == 502
                               else errors.preparation(message))
                else:
                    self.error(errors.upstream_failed())
        finally:
            conn.close()
            self.close_connection = True
