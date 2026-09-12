"""One reader contract for the router state document (Plan 131).

Every reader parses the same JSON document but keeps its own tolerance:
`read` degrades, while `read_strict` fails closed for the router boot and the
installer's state check. This leaf owns the shared parse and the required-key
check, so a caller's tolerance stays visible at the call site instead of
hidden in a private copy of the parse.

Python 3.9-safe and stdlib only; the installer loads it by path.
"""
import json
from pathlib import Path

STATE_NAME = 'mixed-router-state.json'


def path(home):
    """The state document under one router home."""
    return Path(home) / STATE_NAME


class StateUnreadable(ValueError):
    """Fail-closed read failure; `reason` is 'missing', 'unreadable' or 'invalid'."""

    def __init__(self, reason, detail=None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def read(path):
    """Parsed state dict, or None when missing, unreadable or not a dict."""
    try:
        doc = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def read_strict(path):
    """Parsed state dict for fail-closed callers; raises StateUnreadable.

    A non-object document counts as invalid: the callers index the result,
    so a list or scalar is corrupt state, not a usable one.
    """
    try:
        doc = json.loads(Path(path).read_text())
    except FileNotFoundError:
        raise StateUnreadable('missing')
    except OSError as exc:
        raise StateUnreadable('unreadable', exc.__class__.__name__)
    except ValueError as exc:
        raise StateUnreadable('invalid', exc.__class__.__name__)
    if not isinstance(doc, dict):
        raise StateUnreadable('invalid', 'not a JSON object')
    return doc


def required_keys(doc, spec):
    """Names whose value is absent or of the wrong type per spec."""
    return [k for k, t in spec.items() if not isinstance(doc.get(k), t)]
