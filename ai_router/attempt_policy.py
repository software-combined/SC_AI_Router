import http.client
from collections import namedtuple
from dataclasses import replace

from . import errors, provider_defs, stream_attempt, stream_relay, transport, upstream
from .outcome import (CANCELLED, CLIENT, RATE_LIMIT, REFUSED, ROUTER, SEND, STATUS, STREAM,
                      SUCCESS, TRANSPORT, UNKNOWN, UPSTREAM, Outcome)

INITIAL, REPAIR, STREAM_REPLAY, HELPER_FALLBACK = (
    'initial', 'repair', 'stream_replay', 'helper_fallback')
Route = namedtuple('Route', 'provider prepared metrics has_image')


def budget(defn, protocol, opening=INITIAL):
    reasons = [opening]
    if protocol == provider_defs.RESPONSES:
        reasons.append(REPAIR)
        if defn.kind != provider_defs.SUBSCRIPTION:
            reasons.append(STREAM_REPLAY)
    return dict.fromkeys(reasons, 1)


def replay_rejection(ledger, settled, record, body):
    if not ledger.permits(STREAM_REPLAY):
        return 'budget'
    if record.forwarded_bytes:
        return 'committed'
    if not settled.replayable:
        return 'not_transient'
    if settled.source != UPSTREAM:
        return 'router_terminal'
    if settled.output:
        return 'output'
    if not stream_attempt.replay_safe(body):
        return 'side_effects'
    return None


def raised(exc, sent, response, record, client_abort=False, response_seen=False):
    if client_abort:
        category, source = CANCELLED, CLIENT
    elif isinstance(exc, errors.OversizeBusy):
        category, source = RATE_LIMIT, ROUTER
    elif isinstance(exc, errors.InvalidSize):
        category, source = REFUSED, ROUTER
    elif isinstance(exc, (OSError, http.client.HTTPException)):
        category, source = TRANSPORT, ROUTER
    else:
        category, source = UNKNOWN, ROUTER
    if sent and record is not None:
        phase = STREAM
    elif response is None and not response_seen:
        phase = SEND
    else:
        phase = STATUS
    output = record is not None and record.content_delta_bytes > 0
    if isinstance(exc, errors.OversizeBusy):
        code = 'OVERSIZE_BUSY'
    elif isinstance(exc, errors.InvalidSize):
        code = ('BODY_TOO_LARGE' if str(exc) == 'Decoded request is too large'
                else 'INVALID_REQUEST_SIZE')
    else:
        code = type(exc).__name__[:64]
    return Outcome(category, phase, source, code, output,
                   side_effects=not isinstance(exc, (errors.OversizeBusy,
                                                     errors.InvalidSize)))


def settle_delivery(ledger, handler):
    """Settle a delivery failure without replacing a contained ValueError."""
    exc = getattr(handler, 'delivery_error', None)
    if exc is None or isinstance(exc, ValueError):
        return ledger.outcome
    current = ledger.outcome
    client_abort = isinstance(exc, (BrokenPipeError, ConnectionResetError))
    settled = raised(exc, False, None, None, client_abort,
                     response_seen=current is not None)
    if current is not None:
        settled = replace(settled, phase=current.phase, output=current.output,
                          side_effects=current.side_effects)
    return ledger.settle(settled)


def keep_recorded_verdict(record, client_abort):
    """Keep a settled stream verdict unless the client abort supersedes it.

    A late upstream read error cannot replace a terminal the client already
    received or a provider verdict already settled for a held terminal. A
    client abort after replay still supersedes the earlier attempt's outcome;
    the cancellation is the fact the request ended with.
    """
    return (not client_abort and record is not None
            and record.outcome is not None and record.hold.terminal is None)


def keep_delivery_verdict(ledger, record, client_abort, exc):
    return (keep_recorded_verdict(record, client_abort)
            or (not client_abort and record is None and ledger.outcome is not None
                and isinstance(exc, ValueError)))


def late_failure_event(client_abort, keep_verdict, settled):
    if client_abort:
        return 'client_disconnected'
    if keep_verdict and settled.category == SUCCESS:
        return 'request_completed'
    return 'transport_error'


def cached_refusal(status):
    """Outcome for a deterministic refusal served from the local cache."""
    category = REFUSED if status == 400 else UNKNOWN
    return Outcome(category, STATUS, UPSTREAM, 'cached_refusal',
                   side_effects=False)


class Ledger:
    __slots__ = ('request_id', 'operation', 'protocol', 'route', 'opening',
                 'attempts', 'decisions', 'transitions', 'committed', 'outcome',
                 'terminal_source', '_budget', '_spent', '_owned')

    def __init__(self, provider, metrics):
        self.request_id = metrics.get('request_id')
        self.operation = metrics.get('path')
        self.protocol = metrics.get('protocol')
        self.attempts, self.decisions, self._owned = [], [], []
        self.transitions, self.committed = 0, False
        self.outcome = self.terminal_source = None
        self._enter(provider, INITIAL)

    def _enter(self, provider, opening):
        self.route, self.opening = provider.defn.id, opening
        self._budget = budget(provider.defn, self.protocol, opening)
        self._spent = dict.fromkeys(self._budget, 0)

    def permits(self, reason):
        if reason == HELPER_FALLBACK:
            return not self.transitions
        return self._spent.get(reason, 0) < self._budget.get(reason, 0)

    def decide(self, reason, rejection=None):
        if rejection is None and not self.permits(reason):
            rejection = 'budget'
        self.decisions.append('%s:%s' % (reason, rejection or 'approved'))
        return rejection is None

    def send(self, prepared, metrics, reason):
        if self._spent.get(reason, 0) >= self._budget.get(reason, 0):
            raise RuntimeError('attempt budget exhausted')
        self._spent[reason] += 1
        self.attempts.append((len(self.attempts) + 1, self.route, reason))
        conn = http.client.HTTPSConnection(
            prepared.host, timeout=transport.UPSTREAM_TIMEOUT_S)
        self._owned.append(conn)
        return transport.post_with_phases(conn, prepared, metrics)

    def reopen(self, prepared, metrics, started):
        phases = {key: metrics[key] for key in
                  ('connect_ms', 'send_ms', 'headers_ms') if key in metrics}
        try:
            response, headers_done = self.send(prepared, metrics, STREAM_REPLAY)
        finally:
            metrics.update(phases)
        if response.status != 200:
            metrics['retry_code'] = 'retry_http_%d' % response.status
            try:
                transport.read_capped(response, transport.ERROR_BODY_LIMIT)
            finally:
                close = getattr(response, 'close', None)
                if close is not None:
                    close()
            raise ValueError('upstream refused the retry')
        kind, encoding = transport.describe_response(response)
        if (kind, encoding) != ('sse', 'identity'):
            metrics['retry_code'] = 'retry_%s_%s' % (kind, encoding)
            raise ValueError('upstream answered the retry with a different body')
        metrics['upstream_headers_ms'] = round((headers_done - started) * 1000, 1)
        metrics['response_kind'], metrics['response_encoding'] = kind, encoding
        return response, headers_done

    def replay(self, record, body):
        settled = record.outcome or Outcome(UNKNOWN, STREAM, ROUTER)
        if record.content_delta_bytes and not settled.output:
            settled = replace(settled, output=True)
        if record.outcome is None or settled.category == SUCCESS:
            self.settle(settled)
            return False
        rejection = replay_rejection(self, settled, record, body)
        if rejection is None:
            settled = replace(settled, side_effects=False)
        self.settle(settled)
        return self.decide(STREAM_REPLAY, rejection)

    def transition(self, provider, protocol):
        if not self.permits(HELPER_FALLBACK):
            raise RuntimeError('no fallback of a fallback')
        self.transitions += 1
        self.close()
        self.protocol = protocol
        self._enter(provider, HELPER_FALLBACK)
        self.outcome = self.terminal_source = None

    def settle(self, settled):
        self.outcome = settled
        return settled

    def outcome_facts(self):
        final = self.outcome
        return {
            'outcome': None if final is None else final.category,
            'outcome_phase': None if final is None else final.phase,
            'outcome_source': None if final is None else final.source,
            'outcome_code': None if final is None else final.code,
            'outcome_output': None if final is None else final.output,
            'outcome_side_effects': None if final is None else final.side_effects,
        }

    def observe(self, record):
        self.committed = self.committed or record.forwarded_bytes > 0
        self.terminal_source = record.client_terminal

    def mark_committed(self, terminal_source=None):
        """Record that the client received response bytes or headers."""
        self.committed = True
        if terminal_source is not None:
            self.terminal_source = terminal_source

    def close(self):
        for conn in self._owned:
            conn.close()
        self._owned.clear()

    def facts(self):
        return {
            'request_id': self.request_id, 'operation': self.operation,
            'protocol': self.protocol, 'route': self.route,
            'sends': len(self.attempts),
            'attempts': [list(attempt) for attempt in self.attempts],
            'decisions': list(self.decisions), 'transitions': self.transitions,
            'committed': self.committed, 'terminal_source': self.terminal_source,
            **self.outcome_facts(),
        }


def replay_stream(ledger, record, prepared, metrics, started, log_event):
    code = ledger.outcome.code or 'UPSTREAM_STREAM_FAILED'
    record.stream_retry = metrics['stream_retry'] = 1
    metrics['retry_code'] = code
    stream_relay.clear_terminal_fields(metrics)
    log_event('stream_retry', code=code, provider=prepared.provider,
              model=metrics.get('model'), path=metrics.get('path'),
              forwarded_delta_bytes=record.forwarded_bytes)
    response, headers_done = ledger.reopen(prepared, metrics, started)
    upstream.validate_response(response, prepared)
    record.hold.clear()
    record.outcome = None
    return response, headers_done
