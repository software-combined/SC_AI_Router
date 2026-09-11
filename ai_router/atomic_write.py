"""One atomic writer for runtime and installer state files (Plan 131).

Owner-only (0600) by default. Callers that must keep a deterministic temp
name for concurrent-edit detection pass `tmp_name` and pick the leftover
policy: `reuse` clears a stale temp once and retries, `refuse` raises
`StaleTmp` so the caller can speak in its own domain.

`mode` only chmods after the write: the temp is always created 0600 (and so
is the installed file when `mode` is None, up to the process umask).

Python 3.9-safe and stdlib only: the installer loads this leaf by path
(`packaging/atomic_write.py` re-exports it) and the runtime imports it.
"""
import json
import os
import tempfile
from pathlib import Path


class StaleTmp(OSError):
    """A deterministic temp file was left behind and could not be cleared."""


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


def replace_text(path, text, mode=0o600, tmp_name=None, stale_tmp='reuse'):
    """Atomically replace path with text; unique tmp unless tmp_name is set."""
    path = Path(path)
    fd, tmp = _open_tmp(path, tmp_name, stale_tmp)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(text)
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def replace_json(path, doc, mode=0o600, tmp_name=None, stale_tmp='reuse'):
    """Atomically replace path with one JSON document plus a newline."""
    return replace_text(path, json.dumps(doc, indent=2) + '\n',
                        mode=mode, tmp_name=tmp_name, stale_tmp=stale_tmp)
