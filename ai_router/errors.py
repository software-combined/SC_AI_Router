"""One catalog for every defined router failure.

HTTP keeps its current message text and gains a stable code; logs record the
same code. Callers select a case, never invent wording. Never include keys,
tokens, paths carrying tokens, or request content in a message.
"""
import re

ROUTER_TYPE = 'router_error'

_PART = r"[^\\/\s,;:'\"]+"        # one path segment, no separator or delimiter
_SPACED = rf"{_PART}(?:\s+{_PART})*"   # a segment that may contain spaces
_TAIL = rf"{_SPACED}?"
_PATH = re.compile(
    rf"(?<![\w:./])"                            # not inside a word, URL or path
    rf"(?:"
    rf"\\\\\?\\[A-Za-z]:\\(?:{_SPACED}\\)*{_TAIL}"      # \\?\C:\dir\file
    rf"|(?:\\\\|//)(?:{_SPACED}[\\/])+{_TAIL}"          # \\server\share or //server/share
    rf"|[A-Za-z]:\\(?:{_SPACED}\\)*{_TAIL}"             # C:\dir\file
    rf"|~?/(?:{_SPACED}/)*{_TAIL}"                      # /dir/file or ~/dir/file
    rf")")


def redact(text):
    """Replace filesystem paths in a diagnostic with a fixed marker.

    Error bodies and logs must stay useful without naming where a key or
    credential file lives. Path components may contain spaces; a trailing
    explanation after the path is kept.
    """
    if not isinstance(text, str):
        return text
    return _PATH.sub('[path]', text)


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
        return _error(400, 'BODY_TOO_LARGE', "This turn is larger than the router's "
                      '16 MiB request limit; start a new thread, or trim large tool '
                      'outputs and images before continuing.')
    return _error(400, 'INVALID_REQUEST_SIZE', 'Invalid request size')


# Auth and catalog membership.
def bearer_for_no_subscription_only():
    return _error(401, 'BEARER_NO_SUBSCRIPTION_ONLY',
                  'Bearer auth is for no-subscription mode only')


class _UnknownModelError(RouterError):
    """UNKNOWN_MODEL body; never echoes the caller-supplied id back."""

    def __init__(self, model, candidates=()):
        listed = tuple(s for s in candidates if isinstance(s, str) and s)[:1]
        hint = f" (did you mean '{listed[0]}'?)" if listed else ''
        super().__init__(400, 'UNKNOWN_MODEL',
                         'Model is not in the configured catalog' + hint)
        # The shape stays as it was minus the caller's id: a named model gets
        # a candidates list (possibly empty), an unnamed one gets nothing.
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
                  'Model is not available without a ChatGPT subscription')


def claude_subscription_required():
    return _error(400, 'CLAUDE_SUBSCRIPTION_REQUIRED',
                  'Model is not available without a Claude subscription; '
                  'use an OpenRouter model')


def credential_problem(detail):
    detail = redact(detail)
    return _error(400, 'CREDENTIAL_PROBLEM',
                  f'Invalid model, payload, or local authentication configuration: {detail}'
                  if detail else
                  'Invalid model, payload, or local authentication configuration')


def too_many_inflight():
    return _error(429, 'TOO_MANY_REQUESTS',
                  'Too many concurrent requests; retry shortly')


def unsupported_media_type():
    return _error(415, 'UNSUPPORTED_MEDIA_TYPE',
                  'Content-Type must be application/json')


def invalid_payload():
    return _error(400, 'INVALID_PAYLOAD',
                  'Invalid model, payload, or local authentication configuration')


def internal_error():
    return _error(500, 'INTERNAL_ERROR', 'Internal router error')


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


def upstream_invalid_prompt(message=('OpenRouter refused this request before answering. '
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
                       'Native service unavailable without a ChatGPT subscription')


# Retryable states.
def upstream_unavailable(message):
    return _error(503, 'UPSTREAM_UNAVAILABLE', message)


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
        return _error(401, 'CREDENTIAL_PERMISSION', redact(str(exc)) or
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
