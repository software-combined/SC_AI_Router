"""Per-portco model allowlist as resolved data (Plan 068).

The router holds no group truth: the central grant row resolves membership
to a slug list, and the machine stores and enforces that list only. Absent
file means no policy provisioned (today's behavior). Anything unreadable
or invalid fails closed to an empty OpenRouter set (subscription rows
unaffected) and logs a token-free event. Mirrors the credentials.py
owner-only file contract.
"""
import json
import os
from pathlib import Path

from .events import log_event

POLICY_FILE = 'model-policy.json'

# Per-module flag so tests can drive the Windows branch without patching
# global os.name (which pathlib itself reads).
_ON_WINDOWS = os.name == 'nt'


def load(home):
    """Resolved (portco, department, allowed) or (None, None, None).

    Absent file means no policy provisioned (None: today's behavior).
    Anything else unreadable or invalid fails closed to an empty
    OpenRouter set (subscription rows unaffected). Unknown slugs are
    ignored by the caller at merge time, never fatal here. Never logs
    content.
    """
    path = Path(home) / POLICY_FILE
    try:
        raw = path.read_text()
    except FileNotFoundError:
        return None, None, None
    except OSError:
        log_event('model_policy_rejected', reason='unreadable')
        return None, None, ()
    try:
        doc = json.loads(raw)
    except ValueError:
        log_event('model_policy_rejected', reason='invalid_json')
        return None, None, ()
    if (not isinstance(doc, dict)
            or not isinstance(doc.get('portco'), str)
            or not doc.get('portco')
            or ('department' in doc
                and doc['department'] is not None
                and not isinstance(doc['department'], str))
            or not isinstance(doc.get('allowed_models'), list)
            or any(not isinstance(s, str) for s in doc['allowed_models'])):
        log_event('model_policy_rejected', reason='invalid_shape')
        return None, None, ()
    if os.name != 'nt' and path.stat().st_mode & 0o077:
        log_event('model_policy_rejected', reason='permissions')
        return None, None, ()
    if _ON_WINDOWS:
        from . import winacl as _winacl
        try:
            _winacl.check(path)
        except SystemExit:
            log_event('model_policy_rejected', reason='permissions')
            return None, None, ()
    return (doc['portco'], doc.get('department'),
            tuple(doc['allowed_models']))
