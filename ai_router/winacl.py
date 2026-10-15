"""Windows owner-only file verification (Plan 116 Stage 2). Stdlib only.

SID-based counterpart to the POSIX mode-bit gate in credentials.py.
The check runs wherever a key is read; protection at write time lives in
the Windows platform backend. `run` is injectable for offline contract tests.
"""
import json
import os
import re
import subprocess
import time

VERDICT_TTL_S = 30
_VERDICTS = {}
_OS_SIDS = {'S-1-5-18', 'S-1-5-32-544'}  # SYSTEM and Administrators.
_QUERY = r"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
try {
    $request = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $result = @{user = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value}
    if ($null -ne $request.path) {
        $acl = Get-Acl -LiteralPath $request.path
        $raw = [Security.AccessControl.RawSecurityDescriptor]::new($acl.GetSecurityDescriptorBinaryForm(), 0)
        $result.owner = $raw.Owner.Value
        $result.dacl = ($null -ne $raw.DiscretionaryAcl) -and (($raw.ControlFlags -band 4) -ne 0)
        $result.rules = @(foreach ($ace in $raw.DiscretionaryAcl) {
            @{sid = $ace.SecurityIdentifier.Value; type = [int]$ace.AceType;
              mask = [long]$ace.AccessMask; flags = [int]$ace.AceFlags}
        })
    }
    $result | ConvertTo-Json -Depth 5 -Compress
} catch { exit 1 }
"""


def reset():
    """Drop cached verdicts (tests and diagnostics reruns)."""
    _VERDICTS.clear()


def _run(cmd, **kwargs):
    # The router runs under pythonw.exe (no console): without this flag every
    # PowerShell probe would open a console window on the desktop.
    kwargs.setdefault('creationflags', getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return subprocess.run(cmd, **kwargs)


def check(path, run=None, _now=None, *, fresh=False):
    """Refuse grants outside the current user and trusted Windows accounts.

    The verdict is cached per file for a short interval so one key read does
    not spawn PowerShell every time; the entry expires and re-checks,
    so a permission change is honoured at the next expiry. The key includes
    the runner identity, and the entry holds a reference to it, so two
    different seams probing one path never share a verdict.
    Protection writes pass `fresh=True` to verify their actual result.
    """
    run = run or _run
    key = (str(path), id(run))
    now = time.monotonic() if _now is None else _now
    cached = _VERDICTS.get(key)
    if (not fresh and cached is not None and cached[0] is run
            and now - cached[1] < VERDICT_TTL_S):
        if cached[2] is not None:
            raise SystemExit(cached[2])
        return
    try:
        _verify(path, run)
    except SystemExit as exc:
        _VERDICTS[key] = (run, now, str(exc))
        raise
    _VERDICTS[key] = (run, now, None)


def _sid(value):
    if not isinstance(value, str) or not re.fullmatch(r'S-1-[0-9]+(?:-[0-9]+){1,15}', value):
        raise ValueError('invalid SID')
    fields = [int(part) for part in value.split('-')[2:]]
    if (fields[0] >= 2**48 or any(part >= 2**32 for part in fields[1:])
            or value != 'S-1-' + '-'.join(map(str, fields))):
        raise ValueError('invalid SID')
    return value


def _query(path, run):
    try:
        # PowerShell 7 can pass incompatible module paths through Python.
        # Let Windows PowerShell build its defaults in the child only.
        env = {key: value for key, value in os.environ.items()
               if key.upper() != 'PSMODULEPATH'}
        result = run(['powershell', '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', _QUERY],
                     input=json.dumps({'path': None if path is None else str(path)}),
                     capture_output=True, text=True, timeout=15, env=env)
        if result.returncode != 0:
            raise ValueError('ACL query failed')
        doc = json.loads(result.stdout)
        _sid(doc['user'])
        return doc
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError):
        raise SystemExit('cannot verify Windows permissions for %s' % (path or 'current user'))


def current_sid(run=None):
    """The effective Windows identity; never fall back to a display name."""
    return _query(None, run or _run)['user']


def _verify(path, run):
    doc = _query(path, run)
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
        except SystemExit as exc:
            raise PermissionError(str(exc))
        return
    if not owner_only(path):
        raise PermissionError(f'{path} must be readable by the owner only '
                              '(chmod 600)')
