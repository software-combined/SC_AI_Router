"""One catalog for every defined router failure.

HTTP keeps its current message text and gains a stable code; CLI and tool
exits print CODE: message; logs record the same code. Callers select a
case, never invent wording. Never include keys, tokens, paths carrying
tokens, or request content in a message.
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


def fail(code, message):
    """CLI/tool failure: SystemExit carrying CODE: message."""
    raise SystemExit(f'{code}: {message}')


# CLI/tool codes. Area-level: the code names the failing step, the message
# keeps the full detail. Every raise below stays a SystemExit whose text
# starts with CODE so terminal output, logs and tests match.
STATE_MISSING = 'STATE_MISSING'
STATE_INVALID = 'STATE_INVALID'
STARTUP_CREDENTIAL = 'STARTUP_CREDENTIAL'
REGISTRY_INVALID = 'REGISTRY_INVALID'
SETUP_LINK_INVALID = 'SETUP_LINK_INVALID'
SETUP_KEY_MISSING = 'SETUP_KEY_MISSING'
SETUP_BAD_MODE = 'SETUP_BAD_MODE'
SETUP_KEY_REJECTED = 'SETUP_KEY_REJECTED'
SETUP_KEY_UNREACHABLE = 'SETUP_KEY_UNREACHABLE'
SETUP_KEY_EXISTS = 'SETUP_KEY_EXISTS'
SETUP_STORE_FAILED = 'SETUP_STORE_FAILED'
SETUP_CLOSE_FAILED = 'SETUP_CLOSE_FAILED'
FEED_NO_KEY = 'FEED_NO_KEY'
FEED_BAD_SIGNATURE = 'FEED_BAD_SIGNATURE'
FEED_SIGNATURE_REJECTED = 'FEED_SIGNATURE_REJECTED'
FEED_MISSING_SIGNATURE = 'FEED_MISSING_SIGNATURE'
FEED_BAD_URL = 'FEED_BAD_URL'
MODELS_NO_LEVELS = 'MODELS_NO_LEVELS'
MODELS_NOT_LIVE = 'MODELS_NOT_LIVE'
MODELS_DUPLICATE = 'MODELS_DUPLICATE'
MODELS_BAD_TIER = 'MODELS_BAD_TIER'
MODELS_NOT_FOUND = 'MODELS_NOT_FOUND'
CATALOGUE_USAGE = 'CATALOGUE_USAGE'
LIVE_REFRESH_USAGE = 'LIVE_REFRESH_USAGE'
CATALOG_CONCURRENT = 'CATALOG_CONCURRENT'
PROBE_NO_CREDENTIAL = 'PROBE_NO_CREDENTIAL'
PROBE_MERGE_FAILED = 'PROBE_MERGE_FAILED'
PROBE_START_FAILED = 'PROBE_START_FAILED'
BUNDLE_CHECKSUM = 'BUNDLE_CHECKSUM'
BUNDLE_MANIFEST = 'BUNDLE_MANIFEST'
RELEASE_IDENTITY = 'RELEASE_IDENTITY'
BUNDLE_SELF_TEST = 'BUNDLE_SELF_TEST'
KEY_SETUP_REQUIRED = 'KEY_SETUP_REQUIRED'
CATALOGUE_MERGE_FAILED = 'CATALOGUE_MERGE_FAILED'
CONFIG_EDITED = 'CONFIG_EDITED'
VERSION_NOT_INSTALLED = 'VERSION_NOT_INSTALLED'
ROLLBACK_STATE_UNREADABLE = 'ROLLBACK_STATE_UNREADABLE'
INSTALL_FAILED = 'INSTALL_FAILED'
NO_PYTHON = 'NO_PYTHON'
NO_MANIFEST = 'NO_MANIFEST'
BAD_MODE_ARG = 'BAD_MODE_ARG'
NO_INSTALLER = 'NO_INSTALLER'
RESTORE_FAILED = 'RESTORE_FAILED'
UNSUPPORTED_RELEASE_URL = 'UNSUPPORTED_RELEASE_URL'
BAD_ASSET_NAME = 'BAD_ASSET_NAME'
NO_GH_CLI = 'NO_GH_CLI'
GH_AUTH_FAILED = 'GH_AUTH_FAILED'
NON_ABSOLUTE_PYTHON = 'NON_ABSOLUTE_PYTHON'
UNSAFE_BUNDLE_PATH = 'UNSAFE_BUNDLE_PATH'
BUNDLE_NOT_FILE = 'BUNDLE_NOT_FILE'
BOOTSTRAP_FAILED = 'BOOTSTRAP_FAILED'
NO_LAUNCHER = 'NO_LAUNCHER'
SERIAL_CORRUPT = 'SERIAL_CORRUPT'
SERIAL_BAD = 'SERIAL_BAD'
SERIAL_STALE = 'SERIAL_STALE'
SYSTEMD_NO_MANAGER = 'SYSTEMD_NO_MANAGER'
INSTALL_BUSY = 'INSTALL_BUSY'
SYSTEMD_BAD_PYTHON = 'SYSTEMD_BAD_PYTHON'
LAUNCHER_NO_POINTER = 'LAUNCHER_NO_POINTER'
LAUNCHER_NO_RELEASE = 'LAUNCHER_NO_RELEASE'
SEED_EXISTS = 'SEED_EXISTS'
BAD_BUILD_ARG = 'BAD_BUILD_ARG'
SEED_UNREADABLE = 'SEED_UNREADABLE'
CONFIG_CONCURRENT = 'CONFIG_CONCURRENT'
GLOBAL_RULES_CHANGED = 'GLOBAL_RULES_CHANGED'
GLOBAL_RULES_UNOWNED = 'GLOBAL_RULES_UNOWNED'


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
    if isinstance(exc, (ValueError, KeyError)):
        text = str(exc)
        lowered = text.lower()
        if 'not in the configured catalog' in text or 'unknown model:' in lowered:
            return unknown_model(None)
        if 'without a ChatGPT subscription' in text:
            return subscription_required()
        if 'without a Claude subscription' in text:
            return claude_subscription_required()
        if 'openrouter' in lowered and 'key' in lowered:
            return credential_problem(text)
        return invalid_payload()
    return invalid_payload()
