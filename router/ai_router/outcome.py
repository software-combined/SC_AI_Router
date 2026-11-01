"""How one upstream attempt ended, decided once (Plan 188).

Leaf beside `stream_events.py`: `stream_errors` names a stream's terminal
frame here, `upstream.outcome_of` names an HTTP error status, and the relay
names an exception. `attempt_policy` consumes this record; metrics remain log
facts.

`UNKNOWN` is what the router cannot name (a stream with no terminal frame,
an unreadable error body, an unexpected exception). It is never replayable:
only `TRANSIENT` is, and only a classifier that recognised the failure
assigns it.
"""
import http.client
from dataclasses import dataclass
from . import errors

SUCCESS = 'success'
INCOMPLETE = 'incomplete'
REFUSED = 'refused'  # a refusal or an invalid request
CONTEXT_OVERFLOW = 'context_overflow'
AUTH = 'authentication'
QUOTA = 'quota'
RATE_LIMIT = 'rate_limit'
TRANSIENT = 'transient'
TRANSPORT = 'transport'
CANCELLED = 'cancelled'
UNKNOWN = 'unknown'
CATEGORIES = frozenset((SUCCESS, INCOMPLETE, REFUSED, CONTEXT_OVERFLOW, AUTH, QUOTA,
                        RATE_LIMIT, TRANSIENT, TRANSPORT, CANCELLED, UNKNOWN))

# Canonical provider causes shared by HTTP statuses and terminal stream frames.
# The parser keeps unknown values unknown; only these named causes may drive a
# recovery decision.
_FINAL_ERROR_TYPES = frozenset((
    'invalid_request', 'invalid_request_error', 'refusal', 'moderation', 'insufficient_quota'))
_TRANSIENT_CODES = frozenset((
    'server_error', 'provider_unavailable', 'provider_overloaded',
    'timeout', 'timeout_error', 'api_error', 'server', 'overloaded', 'overloaded_error'))
_RATE_LIMIT_TYPES = frozenset((
    'rate_limit', 'rate_limit_error', 'rate_limit_exceeded', 'too_many_requests'))
_AUTH_TYPES = frozenset((
    'invalid_api_key', 'authentication_error', 'unauthorized',
    'insufficient_permissions', 'permission_error', 'account_deactivated'))
_QUOTA_CODES = frozenset((
    'insufficient_quota', 'billing_hard_limit_reached', 'billing_not_active',
    'credit_balance_too_low'))
_CONTEXT_CODES = frozenset(('context_length_exceeded',))

# Where the attempt was when it ended: before a status arrived, at an error
# status, or inside a stream that opened with a success status.
SEND = 'send'
STATUS = 'status'
STREAM = 'stream'
PHASES = frozenset((SEND, STATUS, STREAM))

# Who decided: the provider's own verdict, the router, or the client leaving.
UPSTREAM = 'upstream'
ROUTER = 'router'
CLIENT = 'client'
SOURCES = frozenset((UPSTREAM, ROUTER, CLIENT))

MAX_CODE_CHARS = 64


def facts(settled):
    return {'outcome': None if settled is None else settled.category,
            **{'outcome_' + field: None if settled is None else getattr(settled, field)
               for field in ('phase', 'source', 'code', 'output', 'side_effects')}}


def raised(exc, sent, response, record, client_abort=False, response_seen=False):
    """Classify a transport or local exception without reading diagnostic facts."""
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
        code = exc.error.code
    elif isinstance(exc, errors.InvalidSize):
        code = ('BODY_TOO_LARGE' if str(exc) == 'Decoded request is too large'
                else 'INVALID_REQUEST_SIZE')
    else:
        code = type(exc).__name__[:64]
    return Outcome(category, phase, source, code, output,
                   side_effects=not isinstance(exc, (errors.OversizeBusy, errors.InvalidSize)))


def _causes(error_type, code):
    values = (error_type,) + ((code,) if isinstance(code, str) else tuple(code or ()))
    return tuple(str(value).strip().lower() for value in values
                 if isinstance(value, str))


def category_for(error_type=None, code=None):
    """Map one bounded provider cause to the shared outcome category.

    The specific deterministic invalid-prompt code wins over a generic
    transient label because replaying an invalid request cannot help. Quota
    causes win over the broad final set, and an unrecognised cause stays
    UNKNOWN so it is never replayed.
    """
    values = _causes(error_type, code)
    if any(value in _CONTEXT_CODES for value in values):
        return CONTEXT_OVERFLOW
    if 'invalid_prompt' in values:
        return REFUSED
    if any(value in _QUOTA_CODES or any(token in value for token in
                                        ('quota', 'billing', 'credit'))
           for value in values):
        return QUOTA
    if any(value in _FINAL_ERROR_TYPES for value in values):
        return REFUSED
    if any(value in _AUTH_TYPES for value in values):
        return AUTH
    if any(value in _RATE_LIMIT_TYPES for value in values):
        return RATE_LIMIT
    if any(value in _TRANSIENT_CODES for value in values):
        return TRANSIENT
    return UNKNOWN


def code_for(category, error_type=None, code=None):
    """The bounded cause that produced `category`, else the first cause."""
    values = _causes(error_type, code)
    if category == CONTEXT_OVERFLOW:
        return next((value for value in values if value in _CONTEXT_CODES),
                    values[0] if values else None)
    return next((value for value in values
                 if category_for(error_type, value) == category),
                values[0] if values else None)


@dataclass(frozen=True, slots=True)
class Outcome:
    """One attempt's ending. Immutable; `dataclasses.replace` derives another.

    `code` is a bounded native code (never prose). `output` is True when the
    attempt produced output the client could keep. `side_effects` is True
    while upstream may have acted (run a hosted tool, billed a turn); only a
    status-phase rejection or a checked replay-safe body clears it.
    """

    category: str
    phase: str
    source: str
    code: str | None = None
    output: bool = False
    side_effects: bool = True

    def __post_init__(self):
        if (self.category not in CATEGORIES or self.phase not in PHASES
                or self.source not in SOURCES):
            raise ValueError('unknown outcome field')
        if self.code is not None and (not isinstance(self.code, str)
                                      or len(self.code) > MAX_CODE_CHARS):
            raise ValueError('outcome code is not bounded')

    @property
    def replayable(self):
        """Only a recognised transient failure may be sent again."""
        return self.category == TRANSIENT

    @property
    def reported_failure(self):
        """True when the turn did not succeed; UNKNOWN is never success."""
        return self.category != SUCCESS
