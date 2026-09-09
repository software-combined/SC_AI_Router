"""Windows owner-only file verification (Plan 057 Stage 2). Stdlib only.

icacls-based counterpart to the POSIX mode-bit gate in credentials.py.
The check runs wherever a key is read; protection at write time lives in
the Windows platform backend. `run` is injectable so tests never touch a
real ACL.
"""
import subprocess


def _run(cmd, **kwargs):
    return subprocess.run(cmd, **kwargs)


def check(path, run=None):
    """Refuse a file whose ACL grants anyone but the current user."""
    run = run or _run
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
        if lowered in ('nt authority\\system', 'builtin\\administrators'):
            # The OS itself: like root with POSIX 0600, these can read
            # everything already. The threat is other users, and every
            # default profile/temp dir inherits these ACEs; refusing them
            # would fail closed into unusable on every real machine.
            continue
        raise SystemExit('%s is readable by %s; fix with icacls' % (path, account))
