"""Upstream relay loop: response streaming and failure policy (Plan 128).

Collaborator behind `ai_router.router.Handler`. The body moved here
verbatim from `Handler.relay` with no behaviour change; the handler keeps
a thin wrapper so the public method name used by tests stays valid. The
handler stays the router: new relay/failure behaviour goes here.

`log_event` is injected by the handler so a test patching
`ai_router.router.log_event` keeps seeing this module's events; always call
the injected object, never a fresh import.
"""
import http.client
import json
import time
from . import errors, local_services, provider_defs, setup, stream_errors, stream_relay, strip_retry, subscription_fallback, transport, upstream, wire_shape
from .providers import is_native_service


def relay(handler, provider, prepared, metrics, started, has_image=False, *, log_event,
          admit=None):
    routed = (provider.defn.caches_deterministic_refusals()
              and metrics.get('protocol') == provider_defs.RESPONSES)
    if routed:
        cached = upstream.recall_refusal(prepared.provider, metrics.get('model'), prepared.body)
        if cached is not None:
            status, message = cached
            log_event('upstream_rejected_cached', provider=prepared.provider,
                      model=metrics.get('model'), status=status, category='PROVIDER_REJECTED')
            return handler.error(errors.upstream_invalid_request(message) if status == 400
                                 else errors.retryable_preparation(message))
    conn = http.client.HTTPSConnection(prepared.host, timeout=transport.UPSTREAM_TIMEOUT_S)
    sent, response, record = False, None, None
    attempts = [conn]
    refusal_body = prepared.body
    try:
        # Phases land inside post_with_phases even on failure.
        response, headers_done, prepared, drained = strip_retry.post_with_retry(
            conn, prepared, metrics, attempts, provider, log_event, admit)
        if (provider.defn.dialect == provider_defs.DIALECT_OPENAI
                and is_native_service(metrics['path'])
                and response.status in (401, 403)):
            log_event('native_upstream_rejected', path=metrics['path'],
                      upstream_status=response.status)
            try:
                local_services.answer(metrics['path'])
            except local_services.LocalAnswer as exc:
                return handler.error(exc)
        retry_after = upstream.upstream_retry_after(
            response, prepared, metrics, body=drained)
        if retry_after is not None:
            category, retry_after = retry_after
            if (category in ('quota', 'auth')
                    and metrics.get('protocol') == provider_defs.RESPONSES
                    and provider.defn.opens_key_window_on_auth_failure()):
                if category == 'auth':
                    if handler.server.credentials.key_rejected(prepared.provider):
                        setup.open_key_window(handler.server,
                                              handler.server.credentials.home,
                                              prepared.provider)
                    return handler.error(errors.credential_problem(
                        f'The stored {provider_defs.label_for(prepared.provider)} key was '
                        'rejected. Open the key setup page to connect a new one.'))
                return handler.error(errors.upstream_invalid_request(
                    f'The {provider_defs.label_for(prepared.provider)} account has no '
                    'remaining credit; check the provider billing settings'))
            return subscription_fallback.refused(handler, prepared, retry_after, metrics, started, admit)
        if response.status >= 400:
            raw = drained
            transport.note_first_data(metrics, headers_done)
            # Context frames are Responses-only; Messages ingress has none.
            if (provider.defn.sends_context_error_frame()
                    and metrics.get('protocol') == provider_defs.RESPONSES
                    and upstream.is_context_error(raw)):
                return handler.context_error(metrics['stream'])
            if (provider.defn.opens_key_window_on_auth_failure()
                    and response.status in (401, 403)
                    and metrics.get('protocol') == provider_defs.RESPONSES
                    and handler.server.credentials.key_rejected(prepared.provider)):
                setup.open_key_window(handler.server, handler.server.credentials.home,
                                      prepared.provider)
                label = provider_defs.label_for(prepared.provider)
                return handler.error(errors.credential_problem(
                    f'The stored {label} key was rejected. '
                    'Open the key setup page to connect a new one.'))
            described = upstream.describe_failure(
                None, {'status': response.status, 'body': raw},
                {'model': metrics.get('model'), 'provider': prepared.provider,
                 'protocol': metrics.get('protocol'), 'dialect': provider.defn.dialect,
                 'elapsed_ms': round((time.monotonic() - started) * 1000, 1),
                 'timeout_s': transport.UPSTREAM_TIMEOUT_S, 'has_image': has_image,
                 'routed': routed})
            if described is not None:
                status, message, code = described
                if status == 400 and response.status == 402:
                    # Key funds: a final 400 naming the cause, never a
                    # Retry-After, never the dead-key window, never cached.
                    log_event('upstream_rejected', status=response.status,
                              client_status=status, code='KEY_NO_CREDIT',
                              category='KEY_NO_CREDIT', **metrics)
                    return handler.error(errors.key_no_credit(message))
                if status == 503:
                    # Transient: retried, never remembered. `Retry-After` is
                    # inert for Codex but other clients may honour it.
                    log_event('upstream_unavailable', status=response.status,
                              client_status=status, code=code,
                              parameter=upstream.rejection_parameter(raw),
                              serving_endpoint=upstream.serving_endpoint(raw),
                              category='UPSTREAM_UNAVAILABLE', **metrics,
                              **wire_shape.fingerprint(prepared.body, provider.defn.dialect))
                    return handler.error(errors.upstream_unavailable(message),
                                         retry_after='2')
                # A cached answer must be one the client treats as final.
                if status == 400 and routed and response.status < 500:
                    upstream.remember_refusal(prepared.provider, metrics.get('model'),
                                              refusal_body, message)
                log_event('upstream_rejected', status=response.status,
                          client_status=status, code=code,
                          tool=upstream.rejection_tool(raw, provider.defn.dialect),
                          parameter=upstream.rejection_parameter(raw),
                          serving_endpoint=upstream.serving_endpoint(raw),
                          category='PROVIDER_REJECTED', **metrics,
                          **wire_shape.fingerprint(prepared.body, provider.defn.dialect))
                if status == 400:
                    return handler.error(errors.upstream_invalid_request(message))
                if status == 409:
                    return handler.error(errors.retryable_preparation(message))
                return handler.error(errors.upstream_described(message))
            else:
                handler.send_response(response.status)
                transport.relay_headers(response, handler.send_header, metrics.get('model'))
                handler.send_header('Connection', 'close')
                handler.end_headers()
                handler.wfile.write(raw)
                handler.wfile.flush()
                handler.close_connection = True
                return
        metrics['upstream_headers_ms'] = round((time.monotonic() - started) * 1000, 1)
        metrics['response_kind'], metrics['response_encoding'] = transport.describe_response(response)
        upstream.validate_response(response, prepared)
        handler.send_response(response.status)
        transport.relay_headers(response, handler.send_header, metrics.get('model'))
        handler.send_header('Connection', 'close')
        handler.end_headers()
        sent = True
        # One extra upstream attempt is allowed, and only while the client has
        # no answer frames (see stream_relay.retryable_stream_failure);
        # `attempts` owns every connection a retry opens so none outlive the
        # request.
        record = stream_relay.StreamRecord()
        while True:
            stream_relay.relay_stream(handler, provider, response, prepared,
                                      metrics, started, headers_done, record)
            retry_code = stream_relay.code_of(metrics)
            # At most one retry: this guard is evaluated before the second pass,
            # so a provider that fails both attempts cannot loop.
            if record.stream_retry or not stream_relay.retryable_stream_failure(
                    metrics, record, prepared.body):
                break
            record.stream_retry = 1
            metrics['stream_retry'] = 1
            metrics['retry_code'] = retry_code
            # The retry inherits nothing from the failed attempt: its frames
            # are dropped rather than forwarded, and its verdict must not
            # survive into the second attempt's log line.
            stream_relay.clear_terminal_fields(metrics)
            log_event('stream_retry', code=retry_code, provider=prepared.provider,
                      model=metrics.get('model'), path=metrics.get('path'),
                      forwarded_delta_bytes=record.forwarded_bytes)
            response, headers_done = stream_relay.reopen_stream(
                prepared, metrics, attempts, started)
            # No second send_response: the status line and headers of the first
            # attempt are already on the wire, and every response header is
            # written before the first body byte, so a retry only continues the
            # open body. Re-sending them would append a second header block to
            # the client's stream.
            upstream.validate_response(response, prepared)
            # A retry that opened replaces the whole uncommitted attempt: its
            # verdict replaces the failed attempt's held one, so the hold stays
            # dropped after this point and only this attempt's frames can
            # reach the client.
            record.hold.clear()
        # The settled path flushes the hold exactly like the error path: the
        # frames the client never saw still belong to it, and a flush that
        # moved bytes is the stream's first downstream write.
        if record.flush(handler):
            transport.note_first_write(metrics, headers_done)
        metrics.update(stream_relay.streamed_metrics(record))
        if not record.stream_retry:
            metrics['stream_retry'] = 0
        log_event('request_failed' if metrics.get('code') else 'request_completed',
                  **metrics, status=response.status,
                  total_ms=round((time.monotonic() - started) * 1000, 1))
        if metrics.get('served_model'):
            with handler.server.lock:
                handler.server.served_models[metrics['model']] = metrics['served_model']
    # `admit` refused a repaired body before its send: the client holds no bytes yet.
    except errors.OversizeBusy:
        handler.error(errors.oversize_busy(), retry_after='2')
    except errors.InvalidSize as exc:
        handler.error(errors.invalid_size(str(exc)))
    except (OSError, http.client.HTTPException, ValueError, KeyError,
            TypeError, AttributeError) as exc:
        total_ms = round((time.monotonic() - started) * 1000, 1)
        location = transport.describe_location(exc)
        # A client that hung up mid-stream is not an upstream fault: its own
        # event, and no terminal frame (the socket is gone).
        client_abort = (sent and isinstance(exc, (BrokenPipeError, ConnectionResetError))
                        and 'socketserver.py' in location)
        if record is not None:
            # Whatever setup frames were held still belong to the client, and
            # the terminal frame this tier is about to add must follow them.
            if record.flush(handler):
                transport.note_first_write(metrics, headers_done)
            metrics.update(stream_relay.streamed_metrics(record))
        # One terminal frame per stream: a held terminal from the failed
        # attempt was just flushed with the provider's own verdict, so a
        # generic frame after it would mask that verdict. Writing it before the
        # log line is what lets the line report the frame the client received.
        # Only the provider's held terminal may stand in for the generic frame,
        # and only if it actually reached the client.
        if sent and record.client_terminal is None and not client_abort:
            # A client that holds no terminal frame needs one; a retry that
            # replaced the failed attempt's verdict still owes exactly one.
            transport.emit_terminal_failure(handler.wfile, metrics)
            # The router's own frame is the terminal the client now holds; a
            # dead socket simply leaves the record without one, and the log
            # line below reports that absence instead of claiming it.
            if metrics.get('terminal_source') == stream_errors.TERMINAL_FROM_ROUTER:
                record.client_terminal = stream_errors.TERMINAL_FROM_ROUTER
        if record is not None:
            # Report the writer of the terminal the client actually holds; a
            # client that received none gets no claim at all.
            if record.client_terminal:
                metrics['terminal_source'] = record.client_terminal
            else:
                metrics.pop('terminal_source', None)
        log_event('client_disconnected' if client_abort else 'transport_error',
                  status=response.status if response is not None else None,
                  **metrics, error_type=type(exc).__name__,
                  error_category=exc.msg if isinstance(exc, json.JSONDecodeError) else type(exc).__name__,
                  location=location,
                  total_ms=total_ms)
        if not sent:
            described = upstream.describe_failure(
                exc, None,
                {'model': metrics.get('model'), 'provider': prepared.provider,
                 'host': prepared.host, 'elapsed_ms': total_ms,
                 'timeout_s': transport.UPSTREAM_TIMEOUT_S,
                 'has_image': has_image})
            if described is not None:
                status, message, _ = described
                handler.error(errors.upstream_described(message) if status == 502
                              else errors.preparation(message))
            else:
                handler.error(errors.upstream_failed())
    finally:
        conn.close()
        for extra in attempts[1:]:
            extra.close()
        # A client that left, or any other exit, releases what was still held.
        if record is not None:
            record.hold.clear()
        handler.close_connection = True
