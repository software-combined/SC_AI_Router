"""Shared synthetic fixtures for Claude profile session sync tests."""
import hashlib
import importlib.util
import stat
from pathlib import Path


def fingerprint(root):
    values = []
    for path in sorted(Path(root).rglob('*')):
        if path.is_symlink():
            values.append((path.relative_to(root).as_posix(), 'symlink'))
        elif path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            values.append((path.relative_to(root).as_posix(), digest,
                           stat.S_IMODE(path.stat().st_mode)))
    return tuple(values)


def load_helper(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] /
                                                'packaging' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
