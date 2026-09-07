"""Local answers for native service calls in no-subscription mode.

Recorded upstream shapes do not exist for any native path (the spike saw
no native traffic for custom providers), so every path answers 404 rather
than guessing a response shape Codex might misread. Guardian paths name the
setting that unblocks approvals instead.
"""
from .runtime import log_event

GUARDIAN_PATHS = {'/guardian', '/guardian-classifier'}


class LocalAnswer(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def answer(path):
    """Raise LocalAnswer for a native path; never guess a response shape."""
    log_event('local_service', path=path)
    if path in GUARDIAN_PATHS:
        raise LocalAnswer(404, 'Approvals reviewer needs a subscription; set approvals_reviewer = "user"')
    raise LocalAnswer(404, 'Native service unavailable without a ChatGPT subscription')
