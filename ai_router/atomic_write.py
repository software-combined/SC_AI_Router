"""One atomic writer for runtime and installer state files (Plan 131).

Owner-only (0600) by default. Callers that must keep a deterministic temp
name for concurrent-edit detection pass `tmp_name` and pick the leftover
policy: `reuse` clears a stale temp once and retries, `refuse` raises
`StaleTmp` so the caller can speak in its own domain.

`mode` only chmods after the write: the temp is always created 0600 (and so
is the installed file when `mode` is None, up to the process umask).

Python 3.9-safe and stdlib only: the installer loads this leaf by path
(`packaging/atomic_write.py` re-exports it) and the runtime imports it.

The final rename is `os.replace`, which is atomic on POSIX and Windows
alike. Windows differs in two ways POSIX does not: `MoveFileExW` refuses to
overwrite a destination carrying the read-only attribute, and it can fail
transiently with a sharing violation while another process holds the
destination open (an antivirus scan, a reader). `_replace` clears the
read-only attribute and retries the sharing violation briefly on Windows;
on POSIX it is a plain `os.replace`.
"""
import json
import os
import stat as _stat
import time
import tempfile
from pathlib import Path

# Errors Windows raises for a destination that is momentarily unavailable:
# ERROR_ACCESS_DENIED (5) and ERROR_SHARING_VIOLATION (32).
_WINDOWS_TRANSIENT_REPLACE = frozenset((5, 32))
_ANY = object()


class StaleTmp(OSError):
    """A deterministic temp file was left behind and could not be cleared."""


class ConcurrentChange(OSError):
    """The saved file no longer matches the caller's preflight."""


def check_unchanged(path, expected):
    if expected is _ANY:
        return
    try:
        with Path(path).open(newline='') as stream:
            actual = stream.read()
    except FileNotFoundError:
        actual = None
    if actual != expected:
        raise ConcurrentChange('Settings changed concurrently; retry the operation.')


def remove(path, *, expected):
    """Remove a receipt only after its current bytes match the saved evidence."""
    check_unchanged(path, expected)
    Path(path).unlink(missing_ok=True)


def _replace(tmp, path, expected=_ANY):
    """os.replace, made robust against Windows read-only and lock races.

    POSIX takes the first os.replace and returns. Windows clears a read-only
    destination and retries a sharing violation for up to ~1s before giving
    the caller the original OSError.
    """
    if os.name != 'nt':
        check_unchanged(path, expected)
        os.replace(tmp, path)
        return
    deadline = time.monotonic() + 1.0
    while True:
        check_unchanged(path, expected)
        try:
            os.replace(tmp, path)
            return
        except PermissionError as exc:
            # A read-only destination blocks the overwrite; drop the bit and
            # retry once before treating it as a genuine transient race.
            if os.path.exists(path):
                try:
                    os.chmod(path, _stat.S_IWRITE | _stat.S_IREAD)
                except OSError:
                    pass
            if exc.winerror not in _WINDOWS_TRANSIENT_REPLACE \
                    or time.monotonic() >= deadline:
                raise
            time.sleep(0.02)


def _open_tmp(path, tmp_name, stale_tmp):
    if tmp_name is None:
        fd, tmp = tempfile.mkstemp(dir=str(path.parent),
                                   prefix=path.name + '.', suffix='.tmp')
        return fd, tmp
    tmp = path.with_name(tmp_name)
    for attempt in (0, 1):
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            return fd, str(tmp)
        except FileExistsError:
            if attempt or stale_tmp == 'refuse':
                raise StaleTmp(str(tmp))
            try:
                tmp.unlink()
            except OSError:
                raise StaleTmp(str(tmp))
    raise StaleTmp(str(tmp))  # unreachable; keeps the contract explicit


def replace_text(path, text, mode=0o600, tmp_name=None, stale_tmp='reuse', *, newline=None, expected=_ANY):
    """Atomically replace text; newline='' preserves saved line endings."""
    path = Path(path)
    fd, tmp = _open_tmp(path, tmp_name, stale_tmp)
    stream = None
    try:
        stream = os.fdopen(fd, 'w', newline=newline)
        fd = None  # the stream owns the descriptor now
        stream.write(text)
        stream.close()
        stream = None
        if mode is not None:
            os.chmod(tmp, mode)
        _replace(tmp, path, expected)
    except BaseException:
        # Close the descriptor before unlinking: Windows refuses to remove a
        # file that still has an open handle, which would strand the temp.
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass
        elif fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def replace_json(path, doc, mode=0o600, tmp_name=None, stale_tmp='reuse', *, expected=_ANY):
    """Atomically replace path with one JSON document plus a newline."""
    return replace_text(path, json.dumps(doc, indent=2) + '\n',
                        mode=mode, tmp_name=tmp_name, stale_tmp=stale_tmp, expected=expected)
