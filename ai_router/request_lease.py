"""The HTTP controller's large-request ownership and content-free evidence.

A discarded ingress body needs no streaming lease. Retained fallback data,
large prepared bodies and retry pairs do. The controller supplies its patched
threshold and logger; this module never imports the boot composition root.
"""
import threading
import time
import uuid

from . import errors, request_evidence, transport

LARGE_REQUEST_BUDGET_BYTES = 1024 * 1024 * 1024
LARGE_REQUEST_WAIT_S = 60


def initialize(server):
    server.large_request_condition = threading.Condition(server.lock)
    server.large_request_reservations = {}
    server.large_request_bytes = 0


def begin(handler, version):
    """Reset per-POST facts, including on a reused HTTP connection."""
    handler.lease_facts = {'request_id': uuid.uuid4().hex, 'router_version': version}
    handler.lease_facts.update({key: value for key, value in
                               request_evidence.client_threads(handler.headers).items()
                               if value is not None})
    handler.lease_busy = {}


def read_complete(handler, wire_bytes, decoded_bytes):
    handler.lease_facts.update(wire_bytes=wire_bytes, decoded_bytes=decoded_bytes)
    handler.lease_facts.pop('decoded_lower_bound_bytes', None)


def acquire(handler, stage, log_event, **sizes):
    """Reserve known bytes; existing holders grow without waiting on each other."""
    handler.lease_facts.update(stage=stage, **sizes)
    server = handler.server
    request_id = handler.lease_facts['request_id']
    wanted = max(sizes.values(), default=0)
    started = time.monotonic()
    deadline = started + LARGE_REQUEST_WAIT_S
    with server.large_request_condition:
        reservation = server.large_request_reservations.get(request_id)
        if reservation is not None:
            # Waiting while retaining the old body can deadlock two growing holders.
            extra = max(0, wanted - reservation['reserved_bytes'])
            reservation['reserved_bytes'] += extra
            server.large_request_bytes += extra
            return True
        while True:
            now = time.monotonic()
            if server.draining:
                raise errors.OversizeBusy(is_draining=True)
            if (not server.large_request_reservations
                    or server.large_request_bytes + wanted <= LARGE_REQUEST_BUDGET_BYTES):
                break
            remaining = deadline - now
            if remaining <= 0:
                oldest = min(server.large_request_reservations.values(),
                             key=lambda item: item['acquired_at'])
                handler.lease_busy = dict(handler.lease_facts, reserved_bytes=wanted,
                    waited_ms=round((now - started) * 1000, 1),
                    budget_used_bytes=server.large_request_bytes,
                    holders=len(server.large_request_reservations),
                    owner_held_ms=round((now - oldest['acquired_at']) * 1000, 1))
                return False
            server.large_request_condition.wait(min(1, remaining))
        server.large_request_reservations[request_id] = {
            'stage': stage, 'reserved_bytes': wanted, 'acquired_at': now,
            'waited_ms': round((now - started) * 1000, 1)}
        server.large_request_bytes += wanted
        handler.lease_busy = {}
        fields = dict(handler.lease_facts, reserved_bytes=wanted,
                      waited_ms=round((now - started) * 1000, 1),
                      budget_used_bytes=server.large_request_bytes,
                      holders=len(server.large_request_reservations))
    log_event('oversize_slot_acquired', **fields)
    return True


def release(handler, reason, log_event):
    """Release only this request's reservation, then wake budget waiters."""
    server = handler.server
    with server.large_request_condition:
        owner = server.large_request_reservations.pop(handler.lease_facts['request_id'], None)
        if owner is None:
            return
        server.large_request_bytes -= owner['reserved_bytes']
        fields = dict(handler.lease_facts,
                      acquisition_stage=owner['stage'], release_reason=reason,
                      reserved_bytes=owner['reserved_bytes'], waited_ms=owner['waited_ms'],
                      budget_used_bytes=server.large_request_bytes,
                      holders=len(server.large_request_reservations),
                      held_ms=round((time.monotonic() - owner['acquired_at']) * 1000, 1))
        server.large_request_condition.notify_all()
    log_event('oversize_slot_released', **fields)


def downgrade(handler, prepared, max_body, log_event):
    """Call only after preparation's frame, and its large locals, have died."""
    if (prepared.fallback is None
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
