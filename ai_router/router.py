"""Local trial: retain client subscription authentication; isolate provider keys."""
import http.client
import os
import socket
import threading
import time
from compression import zstd
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from . import (capabilities, errors, ingress, local_services, model_prompt_page,
               provider_defs, relay, setup, subscription_fallback, transport)
from .credentials import Credentials
from .protocols import owned_paths, select as select_protocol
from .errors import InvalidSize, PreparationError
from .providers import NATIVE_SERVICE_PATHS
from .runtime import MAX_BODY, ROUTER_HOME, log_event

MAX_INFLIGHT = 32


def _harden_listener(sock, platform=None):
    """Windows: bind exclusively so no local process can share the port.

    Python's HTTPServer sets SO_REUSEADDR, which on Windows lets another
    local process bind the same loopback port and receive router traffic;
    SO_EXCLUSIVEADDRUSE forbids that. POSIX already refuses the second bind
    without SO_REUSEPORT, so only Windows sets the flag.

    Trade-off: after an abrupt exit, a Windows rebind can wait while
    connections the old listener accepted finish closing; the scheduled
    task's retry covers that window.
    """
    platform = os.name if platform is None else platform
    exclusive = getattr(socket, 'SO_EXCLUSIVEADDRUSE', None)
    if platform == 'nt' and exclusive is not None:
        sock.setsockopt(socket.SOL_SOCKET, exclusive, 1)


class Router(ThreadingHTTPServer):
    daemon_threads = True
    drain_deadline_s = 120
    max_inflight = MAX_INFLIGHT
    # Windows takes SO_EXCLUSIVEADDRUSE in server_bind instead; leaving
    # SO_REUSEADDR on would undo it.
    allow_reuse_address = os.name != 'nt'

    def server_bind(self):
        _harden_listener(self.socket)
        super().server_bind()

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
        return ingress.send_json(self, status, obj, headers)

    def send_compaction_stream(self, output):
        return ingress.send_compaction_stream(self, output)

    def error(self, err):
        return ingress.error(self, err, log_event=log_event)

    def authorized_path(self):
        return ingress.authorized_path(self)

    def context_error(self, streaming):
        return ingress.context_error(self, streaming, log_event=log_event)

    def do_GET(self):
        return ingress.do_get(self)

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
            if path.startswith('/model-prompt/'):
                return model_prompt_page.handle_page(
                    self, path[len('/model-prompt/'):], True)
            return self.error(errors.unsupported_route())
        if (self.headers.get('Content-Type') or '').split(';', 1)[0].strip().lower() \
                != 'application/json':
            return self.error(errors.unsupported_media_type())
        # One slot spans read_body, prepare and relay; rejects above return first.
        with self.server.lock:
            if self.server.inflight >= self.server.max_inflight:
                over = True
            else:
                self.server.inflight += 1
                over = False
        if over:
            return self.retryable_reject(errors.too_many_inflight(), retry_after='1')
        try:
            return self._owned_post(path, via_path, started)
        finally:
            with self.server.lock:
                self.server.inflight -= 1

    def _owned_post(self, path, via_path, started):
        provider = None
        policy = None
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
                    output = compact_call(key)
                    if path == '/responses' and payload.get('stream') is True:
                        return self.send_compaction_stream(output)
                    return self.send_json(200, {'output': output})
                except PreparationError as exc:
                    return self.error(errors.retryable_preparation(str(exc)))
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
            # Responses 400 ends the turn at once; the Messages path keeps
            # today's 409 (Claude Code's retry semantics are out of scope).
            if policy is not None and policy.name == provider_defs.MESSAGES:
                return self.error(errors.retryable_preparation(str(exc)))
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
        return ingress.read_body(self, MAX_BODY)

    def relay(self, provider, prepared, metrics, started, has_image=False):
        return relay.relay(self, provider, prepared, metrics, started, has_image,
                           log_event=log_event)
