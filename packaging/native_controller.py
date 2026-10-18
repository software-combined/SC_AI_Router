"""Keep installer and download access available across runtime rollbacks.

Only manifest-verified release files enter the controller. A rollback changes
the serving release, never the updater's independent version pointer.
"""
import hashlib
import importlib.util
import json
import re
import shutil
import tempfile
from pathlib import Path


def _version(text):
    if not re.fullmatch(r'\d+(?:\.\d+){2,3}', text):
        raise ValueError('invalid controller version')
    return tuple(map(int, text.split('.')))


def installer(home):
    home = Path(home)
    try:
        version = (home / 'control-version').read_text().strip()
        _version(version)
    except (OSError, ValueError):
        return None
    path = home / 'control' / version / 'packaging' / 'install.py'
    return path if path.is_file() else None


def launcher_source(home, source):
    """A runtime install cannot downgrade a newer retained update launcher."""
    selected = installer(home)
    if selected:
        try:
            if _version(selected.parent.parent.name) >= _version(
                    (Path(source) / 'packaging/VERSION').read_text().strip()):
                return selected.parent.parent
        except (OSError, ValueError):
            return selected.parent.parent  # Unknown source identity cannot downgrade verified maintenance.
    return Path(source)


def install(home, source):
    """Install a verified, non-downgrading controller; never import its code."""
    home, source = Path(home), Path(source).resolve()
    manifest = json.loads((source / 'MANIFEST.json').read_text())
    version = (source / 'packaging' / 'VERSION').read_text().strip()
    candidate = _version(version)
    if manifest.get('version') != version:
        raise ValueError('controller identity mismatch')
    previous = installer(home)
    if previous and _version(previous.parent.parent.name) > candidate:
        return previous
    destination = home / 'control' / version
    if source == destination.resolve():
        return destination / 'packaging' / 'install.py'
    destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if destination.is_symlink():
        raise ValueError('unsafe controller folder')
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        stage = Path(temporary) / 'release'
        stage.mkdir()
        for name, digest in manifest['files'].items():
            relative = Path(name)
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError('unsafe controller member')
            member = source / relative
            if source not in member.resolve().parents:
                raise ValueError('unsafe controller file link')
            if hashlib.sha256(member.read_bytes()).hexdigest() != digest:
                raise ValueError('controller checksum mismatch')
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(member, target)
        shutil.copy2(source / 'MANIFEST.json', stage / 'MANIFEST.json')
        if destination.exists():
            # Identical versions are immutable. Verify before reusing one.
            for name, digest in manifest['files'].items():
                if hashlib.sha256((destination / name).read_bytes()).hexdigest() != digest:
                    raise ValueError('installed controller files changed')
        else:
            stage.rename(destination)
    spec = importlib.util.spec_from_file_location(
        'router_controller_atomic', Path(__file__).with_name('atomic_write.py'))
    atomic = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(atomic)
    atomic.replace_text(home / 'control-version', version + '\n')
    return destination / 'packaging' / 'install.py'
