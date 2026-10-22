"""Windows owner-only file verification (Plan 116 Stage 2). Stdlib only.

SID-based counterpart to the POSIX mode-bit gate in credentials.py.
The check runs wherever a key is read; protection at write time lives in
the Windows platform backend. `query` is injectable for offline contract tests.
"""
import json
import importlib.util
import logging
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

_OS_SIDS = {'S-1-5-18', 'S-1-5-32-544'}  # SYSTEM and Administrators.
_spec = importlib.util.spec_from_file_location('router_winsecurity', Path(__file__).with_name('winsecurity.py'))
_native = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_native)


class VerificationUnavailable(PermissionError):
    """The OS could not supply permission facts; never a usable key verdict."""


class _QueryUnavailable(SystemExit):
    """Keep direct native checks compatible with installer refusal handling."""


def _run(cmd, **kwargs):
    # The router runs under pythonw.exe (no console): without this flag every
    # PowerShell probe would open a console window on the desktop.
    kwargs.setdefault('creationflags', getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return subprocess.run(cmd, **kwargs)


def check(path, query=None, *, fresh=False):
    """Refuse unsafe permissions; every check reads current native facts."""
    _verify(path, query)


def _sid(value):
    if not isinstance(value, str) or not re.fullmatch(r'S-1-[0-9]+(?:-[0-9]+){1,15}', value):
        raise ValueError('invalid SID')
    fields = [int(part) for part in value.split('-')[2:]]
    if (fields[0] >= 2**48 or any(part >= 2**32 for part in fields[1:])
            or value != 'S-1-' + '-'.join(map(str, fields))):
        raise ValueError('invalid SID')
    return value


def _query(path, query=None):
    started = time.monotonic()
    for attempt in range(2):
        try:
            doc = (query or _native.query)(path)
            _sid(doc['user'])
            return doc
        except OSError as exc:
            logging.getLogger('codex_router').info(json.dumps(dict(
                ts=datetime.now(timezone.utc).isoformat(), event='permission_query_failed',
                operation=getattr(exc, 'operation', 'query'), winerror=exc.errno,
                attempt=attempt + 1, elapsed_ms=round((time.monotonic() - started) * 1000, 1))))
            if attempt:
                raise _QueryUnavailable('Windows permission check is temporarily unavailable') from None
        except (ValueError, TypeError, KeyError):
            raise SystemExit('cannot verify Windows permissions for %s' % (path or 'current user')) from None


def current_sid(query=None):
    """The effective Windows identity; never fall back to a display name."""
    return _query(None, query)['user']


def _verify(path, query):
    doc = _query(path, query)
    try:
        allowed = _OS_SIDS | {doc['user']}
        owner = _sid(doc['owner'])
        if owner not in allowed:
            raise SystemExit('%s has a foreign owner; repair its Windows permissions' % path)
        if doc['dacl'] is not True or not isinstance(doc['rules'], list) or not doc['rules']:
            raise ValueError('missing ACL')
        # OWNER RIGHTS acts as the object's owner, whose identity was checked above.
        allowed.add('S-1-3-4')
        for rule in doc['rules']:
            sid, kind, mask, flags = (_sid(rule['sid']), rule['type'], rule['mask'], rule['flags'])
            if (type(kind) is not int or kind not in (0, 1) or type(mask) is not int
                    or mask == 0 or not -(2**31) <= mask < 2**32
                    or (mask & 0xffffffff) & ~0xf31f01ff
                    or type(flags) is not int or not 0 <= flags <= 31):
                raise ValueError('unsupported ACL rule')
            if kind == 0 and sid not in allowed:
                raise SystemExit('%s is readable by %s; fix with icacls' % (path, sid))
    except (ValueError, TypeError, KeyError):
        raise SystemExit('cannot verify Windows permissions for %s' % path)


def owner_only(path):
    """True when one key file is readable by its owner only.

    POSIX checks mode bits; Windows defers to the SID-based owner-only check
    (st_mode carries no ACL meaning on NTFS). Never raises: a failed check
    means not usable. Single owner for the key-privacy gate (Plan 131).
    """
    import os as _os
    if _os.name == 'nt':
        try:
            check(path)
            return True
        except SystemExit:
            return False
    try:
        return not (path.stat().st_mode & 0o077)
    except OSError:
        return False


def require_owner_only(path, windows=None):
    """Raise PermissionError unless this key file is owner-only (Plan 131).

    Keeps each platform's own message: POSIX names `chmod 600`, Windows keeps
    the `icacls` line from `check`. `owner_only` is the boolean form for
    callers that only report presence. `windows` lets a caller pass its own
    per-module flag (credentials._ON_WINDOWS) so tests can drive the branch
    without patching os.name.
    """
    import os as _os
    on_windows = _os.name == 'nt' if windows is None else windows
    if on_windows:
        try:
            check(path)
        except _QueryUnavailable as exc:
            raise VerificationUnavailable(str(exc)) from None
        except SystemExit as exc:
            raise PermissionError(str(exc))
        return
    if not owner_only(path):
        raise PermissionError(f'{path} must be readable by the owner only '
                              '(chmod 600)')
