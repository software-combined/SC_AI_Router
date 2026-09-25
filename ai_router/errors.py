"""One catalog for every defined router failure.

Callers select a case, never invent wording; no key, token, path or request
content enters a message or a log line. Status and code stay the wire
contract, the message is plain language, and detail rides the log line.
"""
from .redaction import redact  # noqa: F401 (re-exported: errors.redact)

ROUTER_TYPE = 'router_error'


class RouterError(Exception):
    """Defined HTTP failure: status, stable code, user-facing message.

    `detail` is log-only, path-redacted evidence: the person reads the plain
    message while the log keeps the technical reason.
    """

    def __init__(self, status, code, message, detail=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.detail = redact(detail) if detail else None

    def body(self):
        return {'error': {'message': self.message, 'type': ROUTER_TYPE,
                          'code': self.code}}


class PreparationError(ValueError):
    """A well-formed request the provider cannot serve; maps to 400."""


class LocalAnswer(RouterError):
    """A native path answered locally; never guess an upstream shape."""


class InvalidSize(ValueError):
    """Request body rejected on size grounds; maps to 400."""


class UnknownModel(ValueError):
    """Catalog miss with the requested id and at most one tilde candidate."""

    def __init__(self, model, candidates=()):
        super().__init__('Model is not in the configured catalog'
                         + (f': {model}' if model else ''))
        self.model = model
        self.candidates = tuple(candidates)


class SubscriptionRequired(ValueError):
    """A model only the ChatGPT subscription serves; maps to 400."""

    def __init__(self):
        super().__init__('Model is not available without a ChatGPT subscription')


class ClaudeSubscriptionRequired(ValueError):
    """The Claude twin; maps to 400 with the Claude-specific code."""

    def __init__(self):
        super().__init__('Model is not available without a Claude subscription; '
                         'select a routed model instead')


def _error(status, code, message, detail=None):
    return RouterError(status, code, message, detail)


# Loopback boundary.
def forbidden():
    return _error(403, 'FORBIDDEN', 'The router refused this request. If this app has '
                  'stopped working, re-run the router installer to attach it again.')


def websocket_rejected():
    return _error(426, 'WEBSOCKET_REJECTED',
                  'This connection type is not supported. Reopen the app and retry.')


def unsupported_route():
    return _error(404, 'UNSUPPORTED_ROUTE', 'The router does not serve this request.')


# Request shape.
def missing_model():
    return _error(400, 'MISSING_MODEL',
                  'The request did not name a model. Select a model in the app and retry.')


def invalid_size(message):
    if message == 'Decoded request is too large':
        return _error(400, 'BODY_TOO_LARGE', "This turn is larger than this router's local 96 MiB request ceiling (a resource limit on this machine, not a provider limit); start a new thread, or trim large tool outputs and images before continuing.")
    return _error(400, 'INVALID_REQUEST_SIZE', 'Invalid request size')


# Auth and catalog membership.
def bearer_for_no_subscription_only():
    return _error(401, 'BEARER_NO_SUBSCRIPTION_ONLY', 'This app is signed in a way this router does not accept. Re-run the router installer to attach it again.')


def subscription_auth_rejected():
    return _error(401, 'SUBSCRIPTION_AUTH_REJECTED', 'ChatGPT could not authorise the model list. Sign in again and retry.')


class _UnknownModelError(RouterError):
    """UNKNOWN_MODEL body; never echoes the caller-supplied id back."""

    def __init__(self, model, candidates=()):
        listed = tuple(s for s in candidates if isinstance(s, str) and s)[:1]
        hint = f" Did you mean '{listed[0]}'?" if listed else ''
        super().__init__(400, 'UNKNOWN_MODEL',
                         'That model is not available on this machine. '
                         'Select another model and retry.' + hint)
        # Shape minus the caller's id: named gets candidates, unnamed nothing.
        self.details = {'candidates': list(listed)} if model else {}

    def body(self):
        payload = super().body()
        if self.details:
            payload['error'].update(self.details)
        return payload


def unknown_model(model, candidates=()):
    return _UnknownModelError(model, candidates)


def subscription_required(model=None):
    return _error(400, 'SUBSCRIPTION_REQUIRED',
                  'That model needs a ChatGPT subscription, and this machine is in '
                  'no-subscription mode. Select a routed model instead.')


def claude_subscription_required():
    return _error(400, 'CLAUDE_SUBSCRIPTION_REQUIRED',
                  'That model needs a Claude subscription. '
                  'Select a routed model instead.')


CREDENTIAL_MESSAGE = ('The router could not use your key for this turn. '
                      'Open the key window and enter a working key, then retry.')


def credential_problem(message='', detail=''):
    """Key trouble. `message` is the caller's plain sentence, `detail` the log's."""
    return _error(400, 'CREDENTIAL_PROBLEM', redact(message) or CREDENTIAL_MESSAGE, detail)


def credential_permission(detail=''):
    return _error(401, 'CREDENTIAL_PERMISSION',
                  'The router could not read its stored key. Open the key window '
                  'and enter your key again.', detail)


def too_many_inflight():
    return _error(429, 'TOO_MANY_REQUESTS',
                  'The router is busy with other turns; retry shortly.')


def oversize_busy():
    return _error(503, 'OVERSIZE_BUSY',
                  'The router is still serving another very large turn; retry shortly')


class OversizeBusy(Exception):
    """Another turn already holds the single large-request slot."""


def unsupported_media_type():
    return _error(415, 'UNSUPPORTED_MEDIA_TYPE',
                  'The router could not read this request. Reopen the app and retry.')


def invalid_payload():
    return _error(400, 'INVALID_PAYLOAD',
                  'The router could not send this turn. Start a new thread, or '
                  'switch models and retry.')


def internal_error():
    return _error(500, 'INTERNAL_ERROR',
                  'The router hit an unexpected error and did not send this turn. '
                  'Retry once; if it fails again, re-run the router installer.')


# Provider preparation: only 400 ends a Responses turn at once (Codex
# retries every other 4xx as `UnexpectedStatus`); the Messages path keeps
# its retryable answer through retryable_preparation.
def preparation(message):
    return _error(400, 'PROVIDER_REJECTED', message)


def retryable_preparation(message):
    """Only for a failure a repeat can cure: the compaction summariser."""
    return _error(409, 'PROVIDER_REJECTED', message)


def upstream_invalid_request(message):
    return _error(400, 'PROVIDER_REJECTED', message)


def key_no_credit(message):
    return _error(400, 'KEY_NO_CREDIT', message)


def context_window(message='The model context window is full; compact or shorten the turn.'):
    return _error(400, 'context_length_exceeded', message)


def upstream_invalid_prompt(message=('The model refused this request before answering. '
                                     'Retrying it unchanged will fail again; switch models '
                                     'or start a new thread.'), code='UPSTREAM_INVALID_PROMPT'):
    """A provider 400 raised after the stream opened, replayable only as a new turn."""
    return _error(400, code, message)


# Local services (no-subscription mode answers).
def guardian_needs_subscription():
    return LocalAnswer(404, 'GUARDIAN_NEEDS_SUBSCRIPTION',
                       'Approvals reviewer needs a subscription; '
                       'set approvals_reviewer = "user"')


def native_unavailable():
    return LocalAnswer(404, 'NATIVE_UNAVAILABLE',
                       'This feature needs a ChatGPT subscription and is not '
                       'available in no-subscription mode.')


# Retryable states.
def upstream_unavailable(message):
    return _error(503, 'UPSTREAM_UNAVAILABLE', message)


def draining():
    return _error(503, 'SERVER_DRAINING',
                  'The router is restarting for an update and did not send this '
                  'turn. Retry in a moment.')


def upstream_rate_limited(message=('The model is rate limited right now and the turn '
                                   'was not served. Retry shortly.')):
    return _error(503, 'UPSTREAM_RATE_LIMITED', message)


# Upstream transport.
def compaction_unavailable():
    return _error(502, 'COMPACTION_UNAVAILABLE',
                  'The thread could not be compacted right now. Retry in a moment, '
                  'or start a new thread.')


def upstream_failed():
    return _error(502, 'UPSTREAM_FAILED',
                  'The model stopped responding and this turn was not sent. Retry.')


def upstream_described(message):
    """502 with a named failure; detail keeps model, wait, and retry action."""
    return _error(502, 'UPSTREAM_FAILED', message)


def map_client_error(exc):
    """Split the old vague catch-all: bugs 500, credentials 400/401, else payload/model 400.

    The caller logs request_failed with a traceback for INTERNAL_ERROR;
    the traceback never leaves the log. Credential detail is log-only.
    """
    if isinstance(exc, (AttributeError, TypeError)):
        return internal_error()
    if isinstance(exc, PermissionError):
        return credential_permission(str(exc))
    if isinstance(exc, LookupError):
        return credential_problem(detail=str(exc))
    if isinstance(exc, UnknownModel):
        return unknown_model(exc.model, exc.candidates)
    if isinstance(exc, ClaudeSubscriptionRequired):
        return claude_subscription_required()
    if isinstance(exc, SubscriptionRequired):
        return subscription_required()
    if isinstance(exc, (ValueError, KeyError)):
        text = str(exc)
        lowered = text.lower()
        if 'not in the configured catalog' in text or 'unknown model:' in lowered:
            return unknown_model(None)
        if 'api key' in lowered:
            return credential_problem(detail=text)
        return invalid_payload()
    return invalid_payload()
