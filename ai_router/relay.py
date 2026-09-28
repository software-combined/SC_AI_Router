"""Upstream relay loop: response streaming and failure policy (Plan 128).

`log_event` is injected by the handler so a test patching
`ai_router.router.log_event` keeps seeing this module's events; always call
the injected object, never a fresh import.

One `attempt_policy.Ledger` owns every send of the request (Plan 188): `relay`
walks the routes (the requested one, then at most one helper fallback twin)
and `_route` is one route's send, failure policy and stream.
"""
import http.client
import json
import time
from . import attempt_policy, errors, local_services, messages_errors, provider_defs, setup, stream_errors, stream_relay, strip_retry, subscription_fallback, transport, upstream, wire_shape
from .providers import is_native_service
def _error(handler, ledger, error, **kwargs):
    if getattr(handler, 'response_committed', False):
        ledger.mark_committed(); return False
    sent = handler.error(messages_errors.render(error) if ledger.protocol == provider_defs.MESSAGES else error, **kwargs)
    if sent is True or getattr(handler, 'response_committed', False): ledger.mark_committed()
    attempt_policy.settle_delivery(ledger, handler); return sent

def _record_terminal_source(record, metrics):
    if record.client_terminal: metrics['terminal_source'] = record.client_terminal
    else: metrics.pop('terminal_source', None)


def relay(handler, provider, prepared, metrics, started, has_image=False, *, log_event,
          admit=None):
    ledger = attempt_policy.Ledger(provider, metrics)
    route = attempt_policy.Route(provider, prepared, metrics, has_image)
    try:
        # One ledger bounds both routes; fallback hands back its twin instead of recursing.
        while isinstance(route, attempt_policy.Route):
            route = _route(handler, *route, started, ledger, log_event, admit)
    finally:
        ledger.close()
        log_event('attempt_ledger', **ledger.facts())


def _route(handler, provider, prepared, metrics, has_image, started, ledger, log_event,
           admit):
    routed = (provider.defn.caches_deterministic_refusals()
              and metrics.get('protocol') == provider_defs.RESPONSES)
    if routed:
        cached = upstream.recall_refusal(prepared.provider, metrics.get('model'), prepared.body)
        if cached is not None:
            status, message = cached
            ledger.settle(attempt_policy.cached_refusal(status))
            log_event('upstream_rejected_cached', provider=prepared.provider,
                      model=metrics.get('model'), status=status, category='PROVIDER_REJECTED')
            return _error(handler, ledger, errors.upstream_invalid_request(message)
                          if status == 400 else errors.retryable_preparation(message))
    sent, response, record, response_status = False, None, None, None
    refusal_body = prepared.body
    try:
        response, headers_done, prepared, drained = strip_retry.post_with_retry(
            ledger, prepared, metrics, provider, log_event, admit); response_status = response.status
        if response.status >= 400:
            ledger.settle(upstream.outcome_of(response.status, drained, provider.defn.dialect))
        if (provider.defn.dialect == provider_defs.DIALECT_OPENAI
                and is_native_service(metrics['path'])
                and response.status in (401, 403)):
            log_event('native_upstream_rejected', path=metrics['path'],
                      upstream_status=response.status)
            try:
                local_services.answer(metrics['path'])
            except local_services.LocalAnswer as exc:
                return _error(handler, ledger, exc)
        retry_after = upstream.upstream_retry_after(
            response, prepared, metrics, body=drained)
        if response.status >= 400 and ledger.protocol == provider_defs.MESSAGES:
            return _error(handler, ledger, messages_errors.from_outcome(ledger.outcome, response.status,
                          subscription_fallback.refusal_message(prepared, metrics),
                          upstream.KEY_NO_CREDIT_MESSAGE.format(model=metrics.get('model')), provider.defn.kind == provider_defs.SUBSCRIPTION),
                          retry_after=retry_after[1] if retry_after else None)
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
                    return _error(handler, ledger, errors.credential_problem(
                        f'The stored {provider_defs.label_for(prepared.provider)} key was '
                        'rejected. Open the key setup page to connect a new one.'))
                return _error(handler, ledger, errors.upstream_invalid_request(
                    f'The {provider_defs.label_for(prepared.provider)} account has no '
                    'remaining credit; check the provider billing settings'))
            return subscription_fallback.refused(handler, prepared, retry_after, metrics,
                                                 started, admit, ledger=ledger)
        if response.status >= 400:
            raw = drained
            transport.note_first_data(metrics, headers_done)
            # Context frames are Responses-only; Messages ingress has none.
            if (provider.defn.sends_context_error_frame()
                    and metrics.get('protocol') == provider_defs.RESPONSES
                    and upstream.is_context_error(raw)):
                sent = handler.context_error(metrics['stream'])
                if sent is True and metrics.get('stream') is True: ledger.mark_committed(stream_errors.TERMINAL_FROM_ROUTER)
                elif sent is not False or getattr(handler, 'response_committed', False): ledger.mark_committed()
                attempt_policy.settle_delivery(ledger, handler); return sent
            if (provider.defn.opens_key_window_on_auth_failure()
                    and response.status in (401, 403)
                    and metrics.get('protocol') == provider_defs.RESPONSES
                    and handler.server.credentials.key_rejected(prepared.provider)):
                setup.open_key_window(handler.server, handler.server.credentials.home,
                                      prepared.provider)
                label = provider_defs.label_for(prepared.provider)
                return _error(handler, ledger, errors.credential_problem(
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
                    return _error(handler, ledger, errors.key_no_credit(message))
                if status == 503:
                    # Transient: retried, never remembered. `Retry-After` is
                    # inert for Codex but other clients may honour it.
                    log_event('upstream_unavailable', status=response.status,
                              client_status=status, code=code,
                              parameter=upstream.rejection_parameter(raw),
                              serving_endpoint=upstream.serving_endpoint(raw),
                              category='UPSTREAM_UNAVAILABLE', **metrics,
                              **wire_shape.fingerprint(prepared.body, provider.defn.dialect))
                    return _error(handler, ledger, errors.upstream_unavailable(message),
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
                    return _error(handler, ledger, errors.upstream_invalid_request(message))
                if status == 409:
                    return _error(handler, ledger, errors.retryable_preparation(message))
                return _error(handler, ledger, errors.upstream_described(message))
            else:
                handler.send_response(response.status); handler.response_committed = True
                transport.relay_headers(response, handler.send_header, metrics.get('model'))
                handler.send_header('Connection', 'close')
                handler.end_headers()
                sent = True
                ledger.mark_committed()
                transport.write_full(handler.wfile, raw)
                handler.close_connection = True
                return
        metrics['upstream_headers_ms'] = round((time.monotonic() - started) * 1000, 1)
        metrics['response_kind'], metrics['response_encoding'] = transport.describe_response(response)
        upstream.validate_response(response, prepared, raw_encoded=metrics['response_encoding'] != 'identity')
        handler.send_response(response.status); handler.response_committed = True
        transport.relay_headers(response, handler.send_header, metrics.get('model'))
        handler.send_header('Connection', 'close')
        handler.end_headers()
        ledger.mark_committed()
        sent = True
        # The ledger allows replay only while the client holds no response byte.
        record = stream_relay.StreamRecord()
        while True:
            stream_relay.relay_stream(handler, provider, response, prepared,
                                      metrics, started, headers_done, record, attempt=len(ledger.attempts))
            if not ledger.replay(record, prepared.body):
                break
            response, headers_done = attempt_policy.replay_stream(
                ledger, record, prepared, metrics, started, log_event)
        # Flush held frames before attributing the stream's first write.
        if record.flush(handler):
            transport.note_first_write(metrics, headers_done)
        elif record.delivery_failed:
            raise record.delivery_failed
        elif record.hold.terminal is not None:
            raise OSError('terminal delivery failed')
        if ((ledger.outcome.category == attempt_policy.UNKNOWN or record.outcome is None
             or record.hold.terminal is not None) and record.normalized
                and record.client_terminal is None and sent and transport.emit_terminal_failure(handler.wfile, metrics)):
            record.client_terminal = stream_errors.TERMINAL_FROM_ROUTER
        ledger.observe(record)
        _record_terminal_source(record, metrics)
        metrics.update(stream_relay.streamed_metrics(record), **ledger.outcome_facts())
        metrics['stream_retry'] = record.stream_retry
        log_event('request_failed' if ledger.outcome.reported_failure else 'request_completed',
                  **metrics, status=response.status,
                  total_ms=round((time.monotonic() - started) * 1000, 1))
        if metrics.get('served_model'):
            with handler.server.lock:
                handler.server.served_models[metrics['model']] = metrics['served_model']
    # `admit` refused a repaired body before its send: the client holds no bytes yet.
    except errors.OversizeBusy as exc:
        ledger.settle(attempt_policy.raised(exc, sent, response, record))
        _error(handler, ledger, errors.oversize_busy(), retry_after='2')
    except errors.InvalidSize as exc:
        ledger.settle(attempt_policy.raised(exc, sent, response, record))
        _error(handler, ledger, errors.invalid_size(str(exc)))
    except (OSError, http.client.HTTPException, ValueError, KeyError,
            TypeError, AttributeError) as exc:
        total_ms = round((time.monotonic() - started) * 1000, 1); location = transport.describe_location(exc)
        # A client that hung up mid-stream is not an upstream fault: its own
        # event, and no terminal frame (the socket is gone).
        client_abort = (sent and isinstance(exc, (BrokenPipeError, ConnectionResetError)) and (
            (record is not None and record.delivery_failed is exc) or 'socketserver.py' in location))
        response_status = response.status if response is not None else (response_status or metrics.get('upstream_status'))
        raised = attempt_policy.raised(exc, sent, response, record, client_abort,
                                       response_seen=response_status is not None)
        if record is not None and not record.delivery_failed:
            # Whatever setup frames were held still belong to the client, and
            # the terminal frame this tier is about to add must follow them.
            if record.flush(handler): transport.note_first_write(metrics, headers_done)
            metrics.update(stream_relay.streamed_metrics(record))
        keep_verdict = attempt_policy.keep_delivery_verdict(ledger, record, client_abort, exc)
        ledger.settle((record.outcome if record is not None else ledger.outcome)
                      if keep_verdict else raised)
        metrics.update(ledger.outcome_facts())
        terminal_pending = (record is not None and sent and record.normalized and (record.outcome is None or record.hold.terminal is not None) and record.client_terminal is None and not record.delivery_failed and not client_abort)
        if terminal_pending:
            if transport.emit_terminal_failure(handler.wfile, metrics): record.client_terminal = stream_errors.TERMINAL_FROM_ROUTER
        if record is not None:
            ledger.observe(record)
            _record_terminal_source(record, metrics)
        log_event(attempt_policy.late_failure_event(client_abort, keep_verdict, ledger.outcome),
                    status=response_status,
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
                _error(handler, ledger, errors.upstream_described(message)
                       if status == 502 else errors.preparation(message))
            else:
                _error(handler, ledger, errors.upstream_failed())
    finally:
        # Release held frames; the ledger closes every route connection.
        if record is not None:
            ledger.observe(record)
            record.hold.clear()
        handler.close_connection = True
