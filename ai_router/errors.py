"""One catalog for every defined router failure.

HTTP keeps its current message text and gains a stable code; logs record the
same code. Callers select a case, never invent wording. Never include keys,
tokens, paths carrying tokens, or request content in a message.
"""

ROUTER_TYPE = 'router_error'


class RouterError(Exception):
    """Defined HTTP failure: status, stable code, user-facing message."""

    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message

    def body(self):
        return {'error': {'message': self.message, 'type': ROUTER_TYPE,
                          'code': self.code}}


class PreparationError(ValueError):
    """A well-formed request the provider cannot serve; maps to 409."""


class LocalAnswer(RouterError):
    """A native path answered locally; never guess an upstream shape."""


class InvalidSize(ValueError):
    """Request body rejected on size grounds; maps to 413."""


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
                         'use an OpenRouter model')


def _error(status, code, message):
    return RouterError(status, code, message)


# Loopback boundary.
def forbidden():
    return _error(403, 'FORBIDDEN', 'Forbidden')


def websocket_rejected():
    return _error(426, 'WEBSOCKET_REJECTED',
                  'Use HTTP streaming for this local trial')


def unsupported_route():
    return _error(404, 'UNSUPPORTED_ROUTE', 'Unsupported route')


# Request shape.
def missing_model():
    return _error(400, 'MISSING_MODEL', 'Missing model')


def invalid_size(message):
    if message == 'Decoded request is too large':
        return _error(413, 'BODY_TOO_LARGE', message)
    return _error(413, 'INVALID_REQUEST_SIZE', 'Invalid request size')


# Auth and catalog membership.
def bearer_for_no_subscription_only():
    return _error(401, 'BEARER_NO_SUBSCRIPTION_ONLY',
                  'Bearer auth is for no-subscription mode only')


class _UnknownModelError(RouterError):
    """UNKNOWN_MODEL body also naming the id and its tilde candidate."""

    def __init__(self, model, candidates=()):
        listed = tuple(s for s in candidates if isinstance(s, str) and s)[:1]
        hint = f" (did you mean '{listed[0]}'?)" if listed else ''
        super().__init__(400, 'UNKNOWN_MODEL',
                         f'Model is not in the configured catalog: {model}' + hint
                         if model else 'Model is not in the configured catalog')
        self.details = {'model': model, 'candidates': list(listed)} if model else {}

    def body(self):
        payload = super().body()
        if self.details:
            payload['error'].update(self.details)
        return payload


def unknown_model(model, candidates=()):
    return _UnknownModelError(model, candidates)


def subscription_required(model=None):
    return _error(400, 'SUBSCRIPTION_REQUIRED',
                  'Model is not available without a ChatGPT subscription')


def claude_subscription_required():
    return _error(400, 'CLAUDE_SUBSCRIPTION_REQUIRED',
                  'Model is not available without a Claude subscription; '
                  'use an OpenRouter model')


def credential_problem(detail):
    return _error(400, 'CREDENTIAL_PROBLEM',
                  f'Invalid model, payload, or local authentication configuration: {detail}'
                  if detail else
                  'Invalid model, payload, or local authentication configuration')


def invalid_payload():
    return _error(400, 'INVALID_PAYLOAD',
                  'Invalid model, payload, or local authentication configuration')


def internal_error():
    return _error(500, 'INTERNAL_ERROR', 'Internal router error')


# Provider preparation (409): keep the provider's actionable message.
def preparation(message):
    return _error(409, 'PROVIDER_REJECTED', message)


def context_window(message='The model context window is full; compact or shorten the turn.'):
    return _error(400, 'context_length_exceeded', message)


# Local services (no-subscription mode answers).
def guardian_needs_subscription():
    return LocalAnswer(404, 'GUARDIAN_NEEDS_SUBSCRIPTION',
                       'Approvals reviewer needs a subscription; '
                       'set approvals_reviewer = "user"')


def native_unavailable():
    return LocalAnswer(404, 'NATIVE_UNAVAILABLE',
                       'Native service unavailable without a ChatGPT subscription')


# Retryable states.
def draining():
    return _error(503, 'SERVER_DRAINING', 'Server draining')


def upstream_rate_limited():
    return _error(503, 'UPSTREAM_RATE_LIMITED', 'Upstream rate limited')


# Upstream transport.
def compaction_unavailable():
    return _error(502, 'COMPACTION_UNAVAILABLE',
                  'Compaction summarizer unavailable')


def upstream_failed():
    return _error(502, 'UPSTREAM_FAILED', 'Upstream request failed')


def upstream_described(message):
    """502 with a named failure; detail keeps model, wait, and retry action."""
    return _error(502, 'UPSTREAM_FAILED', message)


def map_client_error(exc):
    """Split the old vague catch-all: bugs 500, credentials 400/401, else payload/model 400.

    The caller logs request_failed with a traceback for INTERNAL_ERROR;
    the traceback never leaves the log.
    """
    if isinstance(exc, (AttributeError, TypeError)):
        return internal_error()
    if isinstance(exc, PermissionError):
        return _error(401, 'CREDENTIAL_PERMISSION', str(exc) or
                      'Invalid model, payload, or local authentication configuration')
    if isinstance(exc, LookupError):
        return credential_problem(str(exc))
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
            return credential_problem(text)
        return invalid_payload()
    return invalid_payload()
