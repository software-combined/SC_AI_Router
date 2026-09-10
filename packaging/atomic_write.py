"""One atomic text writer for installer-side state and config files.

Python 3.9-safe, stdlib only. Loaded through service.load() (Plan 123),
never a package import, so installed bundles keep working.
"""
import os
import tempfile
from pathlib import Path


def replace_text(path, text, mode=0o600):
    """Atomically replace path with text; unique tmp, fsync-free."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + '.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
