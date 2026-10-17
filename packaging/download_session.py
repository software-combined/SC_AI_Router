"""Private download session storage; use the shared atomic writer and ACL gate."""
import importlib.util
import json
import os
import stat
from pathlib import Path

SESSION_FILE = 'download-session.json'


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parent / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_atomic = _load('router_download_atomic', 'atomic_write.py')
_acl = _load('router_download_acl', '../ai_router/winacl.py')


def _regular(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise PermissionError('unsafe download session')
    if os.name != 'nt' and info.st_uid != os.geteuid():
        raise PermissionError('unowned download session')
    _acl.require_owner_only(path)


def read(home):
    path = Path(home) / SESSION_FILE
    try:
        _regular(path)
    except FileNotFoundError:
        return {}
    with path.open('rb') as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError('invalid download session')
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError('invalid download session')
    return result


def write(home, session):
    home = Path(home)
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    if home.is_symlink() or not home.is_dir():
        raise PermissionError('unsafe download home')
    if os.name == 'nt':
        # Protect the directory before the atomic writer creates its temp file.
        windows = _load('router_download_windows', 'platforms/windows.py')
        try:
            windows.protect_file(home, _acl._run)
        except SystemExit:
            raise PermissionError('cannot protect download home') from None
    else:
        if home.stat().st_uid != os.geteuid():
            raise PermissionError('unowned download home')
        home.chmod(0o700)
    path = home / SESSION_FILE
    if path.exists() or path.is_symlink():
        _regular(path)
    _atomic.replace_json(path, session)
    _regular(path)
