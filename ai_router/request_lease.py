"""The HTTP controller's large-request ownership and content-free evidence.

A discarded ingress body needs no streaming lease. Retained fallback data,
large prepared bodies and retry pairs do. The controller supplies its patched
threshold and logger; this module never imports the boot composition root.
"""
import time
import uuid

from . import errors, request_evidence, transport


def begin(handler, version):
    """Reset per-POST facts, including on a reused HTTP connection."""
    handler.oversize_held = False
    handler.lease_facts = {'request_id': uuid.uuid4().hex, 'router_version': version}
    handler.lease_facts.update({key: value for key, value in
                               request_evidence.client_threads(handler.headers).items()
                               if value is not None})
    handler.lease_busy = {}


def read_complete(handler, wire_bytes, decoded_bytes):
    handler.lease_facts.update(wire_bytes=wire_bytes, decoded_bytes=decoded_bytes)
    handler.lease_facts.pop('decoded_lower_bound_bytes', None)


def acquire(handler, stage, log_event, **sizes):
    """Take or keep the slot; snapshot its blocking owner under the same lock."""
    handler.lease_facts.update(stage=stage, **sizes)
    with handler.server.lock:
        now = time.monotonic()
        if handler.oversize_held:
            return True
        if not handler.server.oversize_lock.acquire(blocking=False):
            handler.lease_busy = dict(handler.lease_facts)
            owner = handler.server.oversize_owner
            if owner is not None:
                handler.lease_busy.update(
                    owner_request_id=owner['request_id'], owner_stage=owner['stage'],
                    owner_held_ms=round((now - owner['acquired_at']) * 1000, 1))
            return False
        handler.oversize_held = True
        handler.server.oversize_owner = {
            'request_id': handler.lease_facts['request_id'], 'stage': stage,
            'acquired_at': now}
        handler.lease_busy = {}
        fields = dict(handler.lease_facts)
    log_event('oversize_slot_acquired', **fields)
    return True


def release(handler, reason, log_event):
    """Release only this request's slot; a previous borrower cannot free it."""
    with handler.server.lock:
        if not handler.oversize_held:
            return
        owner = handler.server.oversize_owner
        if owner is None or owner['request_id'] != handler.lease_facts['request_id']:
            return
        fields = dict(handler.lease_facts,
                      acquisition_stage=owner['stage'], release_reason=reason,
                      held_ms=round((time.monotonic() - owner['acquired_at']) * 1000, 1))
        handler.server.oversize_owner = None
        handler.oversize_held = False
        handler.server.oversize_lock.release()
    log_event('oversize_slot_released', **fields)


def downgrade(handler, prepared, max_body, log_event):
    """Call only after preparation's frame, and its large locals, have died."""
    if (handler.oversize_held and prepared.fallback is None
            and prepared.response_adapter is None
            and transport.request_bytes(prepared) <= max_body):
        release(handler, 'prepared_small', log_event)


def admit(handler, prepared, retained, max_body, log_event):
    """Retry admission includes the original body; it never downgrades a lease."""
    held = sum(transport.request_bytes(body) for body in (prepared, retained)
               if body is not None)
    sizes = {'prepared_wire_bytes': len(prepared.body), 'retained_accounted_bytes': held}
    if prepared.decoded_body_bytes is not None:
        sizes['prepared_decoded_bytes'] = prepared.decoded_body_bytes
    handler.lease_facts.update(sizes)
    if held > max_body and not acquire(
            handler, 'retry' if retained is not None else 'prepared', log_event, **sizes):
        raise errors.OversizeBusy()
