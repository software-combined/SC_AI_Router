"""One bounded retry for a repairable Responses 400.

The relay retries once when the adapter that prepared the request proposes a
repair for its own rejection (`repair_rejected`, built by `rejected_repair`):
the external annotation strip for an OpenRouter 400 that names no cause, and
the subscription `invalid_encrypted_content` repair. This module keeps the
`annotation_retry` log lines; the request's `attempt_policy.Ledger` owns the
send, its connection and the one-repair budget (Plan 188).
"""
from . import errors, provider_defs, transport, upstream
from .attempt_policy import REPAIR


def maybe_retry_unattributable(described, response, raw, metrics, provider,
                               prepared, ledger, log_event, admit=None):
    """Retry once with the repair the adapter proposes for its own rejection.

    Returns (response, headers_done, prepared) plus its bounded error body, or
    None when ineligible or unchanged. The relay handles the retry's actual
    response through its ordinary failure policy. `admit` sizes the repaired
    body with the original still held, before anything is sent.
    """
    proposal = None
    # Only a Responses 400 is a repair candidate; the ledger records no
    # decision for any other status.
    candidate = (response.status == 400
                 and metrics.get('protocol') == provider_defs.RESPONSES)
    has_budget = ledger.permits(REPAIR)
    if candidate and has_budget:
        proposal = provider.repair_rejected(prepared, described, raw)
    # An ineligible line has always named the annotation strip.
    fields = {'provider': prepared.provider, 'model': metrics.get('model'),
              'repair': 'annotation_strip' if proposal is None else proposal.repair}
    if metrics.get('request_bytes') is not None:
        fields['request_bytes'] = metrics['request_bytes']
    if proposal is None:
        if candidate:
            ledger.decide(REPAIR, 'ineligible' if has_budget else 'budget')
        log_event('annotation_retry', eligible=False, attempted=False,
                  outcome='ineligible', **fields)
        return None
    fields.update(proposal.facts)
    if proposal.prepared is None:
        ledger.decide(REPAIR, 'unchanged')
        log_event('annotation_retry', eligible=True, attempted=False,
                  outcome='unchanged', **fields)
        return None
    if admit is not None:
        try:
            admit(proposal.prepared, prepared)
        except (errors.InvalidSize, errors.OversizeBusy) as exc:
            ledger.decide(REPAIR, 'refused')
            log_event('annotation_retry', eligible=True, attempted=False,
                      outcome='refused', error_type=type(exc).__name__,
                      prepared_bytes=len(proposal.prepared.body), **fields)
            raise
    if proposal.reports_rejection:
        log_event('upstream_rejected', status=response.status,
                  client_status=described[0], code=described[2],
                  tool=upstream.rejection_tool(raw, provider.defn.dialect),
                  parameter=upstream.rejection_parameter(raw),
                  serving_endpoint=upstream.serving_endpoint(raw),
                  category='PROVIDER_REJECTED', **metrics)
    ledger.decide(REPAIR)
    log_event('annotation_retry', eligible=True, attempted=True,
              outcome='started', **fields)
    retried_prepared = proposal.prepared
    try:
        response, headers_done = ledger.send(retried_prepared, metrics, REPAIR)
        metrics['upstream_status'] = response.status
        retry_raw = (transport.read_capped(response, transport.ERROR_BODY_LIMIT)
                     if response.status >= 400 else None)
    except BaseException as exc:
        log_event('annotation_retry', eligible=True, attempted=True,
                  outcome='transport_error', error_type=type(exc).__name__, **fields)
        raise
    log_event('annotation_retry', eligible=True, attempted=True,
              outcome='rejected' if retry_raw is not None else 'accepted',
              status=response.status,
              reason=upstream.rejection_reason(retry_raw, provider.defn.dialect),
              parameter=upstream.rejection_parameter(retry_raw),
              serving_endpoint=upstream.serving_endpoint(retry_raw), **fields)
    return response, headers_done, retried_prepared, retry_raw


def post_with_retry(ledger, prepared, metrics, provider, log_event, admit=None):
    """Dispatch at most twice and retain the final response for normal handling."""
    response, headers_done = ledger.send(prepared, metrics, ledger.opening)
    metrics['upstream_status'] = response.status
    raw = None
    if response.status >= 400:
        raw = transport.read_capped(response, transport.ERROR_BODY_LIMIT)
        described = upstream.describe_failure(
            None, {'status': response.status, 'body': raw},
            {'model': metrics.get('model'), 'provider': prepared.provider,
             'protocol': metrics.get('protocol'), 'dialect': provider.defn.dialect})
        retried = maybe_retry_unattributable(
            described, response, raw, metrics, provider, prepared, ledger, log_event,
            admit)
        if retried is not None:
            return retried
    return response, headers_done, prepared, raw
