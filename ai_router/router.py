"""Local trial: retain client subscription authentication; isolate provider keys."""
import http.client
import os
import socket
import threading
import time
from compression import zstd
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from . import (errors, ingress, local_services, model_prompt_page,
               provider_defs, relay, setup, subscription_discovery,
               subscription_fallback, transport, turn_budget)
from .credentials import Credentials
from .protocols import select as select_protocol
from .errors import InvalidSize, PreparationError
from .image_items import has_images
from .providers import is_native_service, reject_opaque_agent_items
from .runtime import MAX_BODY, ROUTER_HOME, log_event

MAX_INFLIGHT = 32
# Bounds the client socket: idle pre-auth reads and blocked writes.
CLIENT_TIMEOUT_S = 120


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
    # Parallel sub-agent connects burst past the stdlib backlog of 5; the
    # in-flight cap still applies after accept, so this admits, not refuses.
    request_queue_size = 64
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
        # One large turn at a time, read to last send: the parsed form costs
        # roughly five times its bytes, and sub-agents replay the same history.
        self.oversize_lock = threading.Lock()
        self.inflight = 0
        self.draining = False
        self.served_models = {}
        self.credentials = credentials if credentials is not None else Credentials(state, ROUTER_HOME)

    def drain_and_exit(self):
        with self.lock:
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
    # Kept eager: under 1 ms on a 4 MiB body; RecursionError is contained by
    # the handler (plan 163).
    # ponytail: walk the parsed payload, don't substring-match or re-parse the body;
    # prose mentioning images must not count.
    if not isinstance(payload, dict):
        return False
    return has_images(payload.get('input'))


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    timeout = CLIENT_TIMEOUT_S
    # True while this request holds the server's single large-request slot.
    oversize_held = False

    def log_message(self, *args):
        pass  # Request URLs and upstream credentials must never enter access logs.

    def send_json(self, status, obj, headers=None):
        return ingress.send_json(self, status, obj, headers)

    def send_compaction_stream(self, output):
        return ingress.send_compaction_stream(self, output)

    def error(self, err, retry_after=None):
        return ingress.error(self, err, log_event=log_event, retry_after=retry_after)

    def authorized_path(self):
        return ingress.authorized_path(self)

    def context_error(self, streaming):
        return ingress.context_error(self, streaming, log_event=log_event)

    def do_GET(self):
        return ingress.do_get(self)

    def drain_reject(self):
        return self.error(errors.draining(), retry_after='2')

    def do_POST(self):
        started = time.monotonic()
        path, via_path = self.authorized_path()
        if path is None:
            return self.error(errors.forbidden())
        path, _, query = path.partition('?')
        if self.server.draining:
            return self.drain_reject()
        if path == '/shutdown':
            # Portable restart: every supervisor relaunches an exited service,
            # unlike `launchctl kill` which exists only on macOS.
            # Non-daemon like the SIGTERM path, or teardown kills the drain.
            threading.Thread(target=self.server.drain_and_exit, daemon=False).start()
            return self.send_json(200, {'status': 'draining'})
        if select_protocol(self.command, path) is None:
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
        # The drain flag is re-read under the same lock so a drain that lands
        # between admission and the increment cannot strand a request.
        with self.server.lock:
            if self.server.draining:
                verdict = 'draining'
            elif self.server.inflight >= self.server.max_inflight:
                verdict = 'over'
            else:
                self.server.inflight += 1
                verdict = None
        if verdict == 'draining':
            return self.drain_reject()
        if verdict == 'over':
            return self.error(errors.too_many_inflight(), retry_after='1')
        try:
            ready = self._owned_post(path, via_path, started)
            if ready is not None:
                self.relay(*ready)
        finally:
            # A large prepared body lives until relay returns, so the slot
            # spans the stream; this frame drops its reference first.
            ready = None
            if self.oversize_held:
                self.server.oversize_lock.release()
                self.oversize_held = False
            with self.server.lock:
                self.server.inflight -= 1

    def _owned_post(self, path, via_path, started):
        provider = policy = None
        # Facts for the refusal line: sizes and classes, never content.
        facts = {'compressed_bytes': self._declared_bytes(),
                 'decode_limit_bytes': transport.MAX_REQUEST_BYTES}
        self.connection.settimeout(CLIENT_TIMEOUT_S)
        try:
            raw, payload, size, decoded_len = self.read_body()
            read_done = time.monotonic()
            facts.update(compressed_bytes=size, decoded_bytes=decoded_len)
            if decoded_len > MAX_BODY:
                # The client's own composition, before prepare rewrites it.
                facts.update(turn_budget.class_stats(payload.get('input')))
            # Snapshot before provider.prepare mutates or strips the payload.
            has_image = _payload_has_image(payload)
            model = payload.get('model')
            if not isinstance(model, str) and not is_native_service(path):
                return self.error(errors.missing_model())
            mode = self.server.state.get('openai_mode', 'subscription')
            policy = select_protocol(self.command, path)
            if policy is None:
                return self.error(errors.unsupported_route())
            context = policy.resolve(model)  # this request's one registry read (Plan 188)
            provider = policy.select_provider(
                model, path, self.server.state, mode, catalogue=context.catalogue,
                openai_models=subscription_discovery.request_models(
                    self.server, dict(self.headers), self.path.partition('?')[2]))
            if provider.kind == provider_defs.EXTERNAL: reject_opaque_agent_items(payload.get('input'))
            if provider.kind == provider_defs.SUBSCRIPTION and not via_path:
                return self.error(errors.bearer_for_no_subscription_only())
            compact_call = policy.compaction_call(provider, model, path, payload, context)
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
                                                         raw, dict(self.headers), self.server,
                                                         decoded_len=decoded_len, context=context)
                # Prepare may grow the body (a rewrite escapes non-ASCII text):
                # admission counts what will be sent, never trims it.
                facts.update(prepared_bytes=len(prepared.body),
                             prepared_decoded_bytes=prepared.decoded_body_bytes)
                self.admit(prepared)
            except local_services.LocalAnswer as exc:
                return self.error(exc)
            if os.environ.get('ROUTER_DEBUG'):
                log_event('provider_selected', provider=provider.name, model=model, path=path)
        except PermissionError as exc:
            return self.error(errors.map_client_error(exc))
        except errors.OversizeBusy:
            return self.error(errors.oversize_busy(), retry_after='2')
        except InvalidSize as exc:
            err = errors.invalid_size(str(exc))
            log_event('turn_refused', code=err.code, **facts)
            return self.error(err)
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
            pid = defn.id if defn is not None else provider_defs.DEFAULT_EXTERNAL
            setup.open_key_window(self.server, self.server.credentials.home, pid)
            return self.error(errors.credential_problem(
                detail='%s: %s' % (provider_defs.label_for(pid), exc)))
        except (ValueError, KeyError, OSError, zstd.ZstdError,
                AttributeError, TypeError, RecursionError) as exc:
            err = errors.map_client_error(exc)
            if err.code == 'INTERNAL_ERROR':
                log_event('request_failed', code=err.code,
                          error_type=type(exc).__name__,
                          location=transport.describe_location(exc))
            return self.error(err)
        _reasoning = payload.get('reasoning')
        prepare_done = time.monotonic()
        metrics = {'request_id': context.request_id, 'provider': prepared.provider,
                   'protocol': policy.name,
                   'model': model, 'path': path, 'request_bytes': size,
                   'stream': payload.get('stream') is True,
                   'reasoning_effort': _reasoning.get('effort') if isinstance(_reasoning, dict) else None,
                   'max_output_tokens': getattr(prepared, 'output_cap', None),
                   'context_tokens': prepared.context_tokens,
                   'tool_definitions': len(payload.get('tools', [])),
                   'local_prepare_ms': round((time.monotonic() - started) * 1000, 1),
                   # Per-phase detail; cumulative fields keep their meaning.
                   'read_ms': round((read_done - started) * 1000, 1),
                   'prepare_ms': round((prepare_done - read_done) * 1000, 1)}
        log_event('request_started', **metrics)
        return provider, prepared, metrics, started, has_image

    def read_body(self):
        return ingress.read_body(self, MAX_BODY, self._take_oversize_slot)

    def admit(self, prepared, retained=None):
        """Admit one body for sending, with any body the caller still retains.

        InvalidSize past the request ceiling; past MAX_BODY together, the
        turn takes (or keeps) the large-request slot or raises OversizeBusy.
        """
        held = sum(transport.request_bytes(body) for body in (prepared, retained)
                   if body is not None)
        if held > MAX_BODY and not self._take_oversize_slot():
            raise errors.OversizeBusy()

    def _take_oversize_slot(self):
        """Take or keep the large-request slot; False while another turn has it."""
        if self.oversize_held:
            return True
        if not self.server.oversize_lock.acquire(blocking=False):
            return False
        self.oversize_held = True
        return True

    def _declared_bytes(self):
        try:
            size = int(self.headers.get('Content-Length', '-1'))
        except (TypeError, ValueError):
            return None
        return size if size >= 0 else None

    def relay(self, provider, prepared, metrics, started, has_image=False):
        return relay.relay(self, provider, prepared, metrics, started, has_image,
                           log_event=log_event, admit=self.admit)
