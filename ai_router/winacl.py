"""Windows owner-only file verification (Plan 057 Stage 2). Stdlib only.

icacls-based counterpart to the POSIX mode-bit gate in credentials.py.
The check runs wherever a key is read; protection at write time lives in
the Windows platform backend. `run` is injectable so tests never touch a
real ACL.
"""
import subprocess
import time

VERDICT_TTL_S = 30
_VERDICTS = {}


def reset():
    """Drop cached verdicts (tests and diagnostics reruns)."""
    _VERDICTS.clear()


def _run(cmd, **kwargs):
    # The router runs under pythonw.exe (no console): without this flag every
    # icacls/whoami probe would open a console window on the desktop.
    kwargs.setdefault('creationflags', getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return subprocess.run(cmd, **kwargs)


def check(path, run=None, _now=None):
    """Refuse a file whose ACL grants anyone but the current user.

    The verdict is cached per file for a short interval so one key read does
    not spawn icacls and whoami every time; the entry expires and re-checks,
    so a permission change is honoured at the next expiry. The key includes
    the runner identity, and the entry holds a reference to it, so two
    different seams probing one path never share a verdict.
    """
    run = run or _run
    key = (str(path), id(run))
    now = time.monotonic() if _now is None else _now
    cached = _VERDICTS.get(key)
    if (cached is not None and cached[0] is run
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


def _verify(path, run):
    result = run(['icacls', str(path)], capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit('cannot verify %s: %s'
                         % (path, (result.stderr or '').strip()[-500:]))
    whoami = run(['whoami'], capture_output=True, text=True)
    me = (whoami.stdout or '').strip().lower()
    owner = me.split('\\')[-1] if me else ''
    for line in (result.stdout or '').splitlines():
        stripped = line.strip()
        if not stripped or 'successfully processed' in stripped.lower():
            continue
        if stripped.lower().startswith(str(path).lower()):
            # Real icacls prints the first ACE on the filename line itself;
            # parse what follows it instead of discarding the entry.
            stripped = stripped[len(str(path)):].strip()
            if not stripped:
                continue
        account = stripped.split(':')[0].strip()
        lowered = account.lower()
        if lowered in ('', 'processed', 'successfully'):
            continue
        if owner and (lowered == me or lowered == owner):
            continue
        if lowered in ('nt authority\\system', 'builtin\\administrators',
                       'owner rights'):
            # The OS itself (SYSTEM/Administrators act as root does with
            # POSIX 0600) and OWNER RIGHTS (S-1-3-4, rights scoped to the
            # object's current owner, nobody else). The threat is other
            # users, and every default profile/temp dir inherits these
            # ACEs; refusing them would fail closed into unusable on every
            # real machine.
            continue
        raise SystemExit('%s is readable by %s; fix with icacls' % (path, account))


def owner_only(path):
    """True when one key file is readable by its owner only.

    POSIX checks mode bits; Windows defers to the icacls owner-only check
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
