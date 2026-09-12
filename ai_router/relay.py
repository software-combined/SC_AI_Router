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
from . import errors, local_services, provider_defs, setup, subscription_fallback, transport, upstream
from .providers import NATIVE_SERVICE_PATHS


def relay(handler, provider, prepared, metrics, started, has_image=False, *, log_event):
    routed = (prepared.provider == provider_defs.OPENROUTER.id
              and metrics.get('protocol') == provider_defs.RESPONSES)
    if routed:
        cached = upstream.recall_refusal(prepared.provider, metrics.get('model'), prepared.body)
        if cached is not None:
            status, message = cached
            log_event('upstream_rejected_cached', provider=prepared.provider,
                      model=metrics.get('model'), status=status, category='PROVIDER_REJECTED')
            return handler.error(errors.upstream_invalid_request(message) if status == 400
                                 else errors.preparation(message))
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
                return handler.error(exc)
        retry_after = upstream.upstream_retry_after(response, prepared, metrics)
        if retry_after is not None:
            return subscription_fallback.refused(handler, prepared, retry_after, metrics, started)
        if response.status >= 400:
            raw = response.read()
            transport.note_first_data(metrics, headers_done)
            # Gate the terminal-frame path on the protocol as well: the
            # Messages ingress shares the openrouter dialect but has no
            # Responses failure frame to send.
            if (provider.defn.dialect == 'openrouter'
                    and metrics.get('protocol') == provider_defs.RESPONSES
                    and upstream.is_context_error(raw)):
                return handler.context_error(metrics['stream'])
            if (provider.defn.dialect == 'openrouter'
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
                 'protocol': metrics.get('protocol'),
                 'elapsed_ms': round((time.monotonic() - started) * 1000, 1),
                 'timeout_s': 120,
                 'has_image': has_image, 'routed': routed})
            if described is not None:
                status, message, code = described
                # A transient upstream failure is retryable; only a
                # deterministic client-side rejection is worth remembering.
                if status in (400, 409) and routed and response.status < 500:
                    upstream.remember_refusal(prepared.provider, metrics.get('model'),
                                              prepared.body, message, status=status)
                log_event('upstream_rejected', status=response.status,
                          client_status=status, code=code,
                          parameter=upstream.rejection_parameter(raw),
                          category='PROVIDER_REJECTED',
                          **metrics, **upstream.rejection_fingerprint(prepared.body))
                if status == 400:
                    return handler.error(errors.upstream_invalid_request(message))
                return handler.error(errors.upstream_described(message) if status == 502
                                     else errors.preparation(message))
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
        for chunk in provider.adapt(response, prepared.tool_names, metrics):
            if 'first_chunk_ms' not in metrics:
                metrics['first_chunk_ms'] = round((time.monotonic() - started) * 1000, 1)
            transport.note_first_data(metrics, headers_done)
            handler.wfile.write(chunk)
            handler.wfile.flush()
            transport.note_first_write(metrics, headers_done)
        log_event('request_completed', **metrics, status=response.status,
                  total_ms=round((time.monotonic() - started) * 1000, 1))
        if metrics.get('served_model'):
            with handler.server.lock:
                handler.server.served_models[metrics['model']] = metrics['served_model']
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
            transport.emit_terminal_failure(handler.wfile, metrics)
        else:
            described = upstream.describe_failure(
                exc, None,
                {'model': metrics.get('model'), 'provider': prepared.provider,
                 'host': prepared.host, 'elapsed_ms': total_ms,
                 'timeout_s': 120,
                 'has_image': has_image})
            if described is not None:
                status, message, _ = described
                handler.error(errors.upstream_described(message) if status == 502
                              else errors.preparation(message))
            else:
                handler.error(errors.upstream_failed())
    finally:
        conn.close()
        handler.close_connection = True
