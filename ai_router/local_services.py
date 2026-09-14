"""Local answers for native service calls in no-subscription mode.

Recorded upstream shapes do not exist for any native path (the spike saw
no native traffic for custom providers), so every path answers 404 rather
than guessing a response shape Codex might misread. Guardian paths name the
setting that unblocks approvals instead. Native paths are a prefix rule on
the OpenAI definition (`provider_defs.native_service_path`), not a list.
"""
from . import errors
from .runtime import log_event

GUARDIAN_PATHS = {'/guardian', '/guardian-classifier'}

LocalAnswer = errors.LocalAnswer


def answer(path):
    """Raise LocalAnswer for a native path; never guess a response shape."""
    log_event('local_service', path=path)
    if path in GUARDIAN_PATHS:
        raise errors.guardian_needs_subscription()
    raise errors.native_unavailable()
