"""Validate and retain a native installer's files before using its Python.

The download is disposable. Services and the installed setup shortcut must
only refer to the retained copy, never a disk image or temporary mount.
"""
import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import tempfile
import uuid
from pathlib import Path


def load(name):
    spec = importlib.util.spec_from_file_location(
        'router_native_' + name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def target():
    system = {'Darwin': 'darwin', 'Windows': 'windows', 'Linux': 'linux'}.get(
        platform.system())
    cpu = {'AMD64': 'x86_64', 'aarch64': 'arm64'}.get(
        platform.machine(), platform.machine())
    return '%s/%s' % (system, cpu)


def metadata(resources, expected_target=None):
    resources = Path(resources).resolve()
    doc = json.loads((resources / 'installer.json').read_text())
    if (not isinstance(doc, dict) or
            not re.fullmatch(r'\d+(?:\.\d+){2,3}', str(doc.get('version', ''))) or
            doc.get('channel') not in ('stable', 'beta') or
            doc.get('target') != (expected_target or target())):
        raise ValueError('This installer is not for this computer.')
    executable = Path(doc.get('runtime_exec', ''))
    if (not executable.parts or executable.is_absolute() or
            '..' in executable.parts or
            not (resources / 'runtime' / executable).is_file()):
        raise ValueError('The bundled Python is missing.')
    blob = resources / 'payload' / 'bundle.tar.gz'
    digest = hashlib.sha256(blob.read_bytes()).hexdigest()
    feed = json.loads((resources / 'payload' / 'latest.json').read_text())
    if (digest != doc.get('sha256') or digest != feed.get('sha256') or
            feed.get('version') != doc['version']):
        raise ValueError('The installer files did not pass verification.')
    for name in ('install.py', 'native_setup.py'):
        if not (resources / 'router' / 'packaging' / name).is_file():
            raise ValueError('The installer is incomplete.')
    if 'menu_sha256' in doc:
        helper = resources / 'control' / ('scg-router-menu.exe' if doc['target'].startswith('windows/') else 'scg-router-menu')
        if (not re.fullmatch('[0-9a-f]{64}', str(doc['menu_sha256'])) or not helper.is_file()
                or hashlib.sha256(helper.read_bytes()).hexdigest() != doc['menu_sha256']):
            raise ValueError('The menu files did not pass verification.')
    return doc


def retained(resources, home, expected_target=None, *, repair=False):
    """Stage and atomically retain one immutable package; returns its path."""
    resources, home = Path(resources).resolve(), Path(home).expanduser()
    doc = metadata(resources, expected_target)
    for entry in resources.rglob('*'):
        if entry.is_symlink() and resources not in entry.resolve().parents:
            raise ValueError('The installer contains an unsafe file link.')
    if home.is_symlink() or (home / 'setup').is_symlink():
        raise ValueError('The setup folder is not safe to use.')
    home.mkdir(parents=True, mode=0o700, exist_ok=True)
    service = load('service')
    # The backend protects Windows ACLs as well as POSIX permissions.
    spec = importlib.util.spec_from_file_location(
        'router_native_platforms', Path(__file__).parent / 'platforms' / '__init__.py')
    platforms = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(platforms)
    backend = platforms.select(os.sys.platform, service, service.run)
    if backend is None:
        raise ValueError('This computer is not supported.')
    backend.protect_secret(home)
    base = home / 'setup'
    base.mkdir(mode=0o700, exist_ok=True)
    destination = base / (doc['version'] + '-' + doc['sha256'][:16])
    if destination.is_symlink():
        raise ValueError('The setup folder is not safe to use.')
    if destination.exists():
        try:
            matches = metadata(destination, expected_target) == doc
        except (OSError, ValueError):
            matches = False
        if matches:
            return destination
        if not repair:
            raise ValueError('The installed setup files have changed.')
        destination = base / (destination.name + '-repair-' + uuid.uuid4().hex[:12])
    with tempfile.TemporaryDirectory(dir=base) as temporary:
        staged = Path(temporary) / 'Resources'
        shutil.copytree(resources, staged)
        metadata(staged, expected_target)
        staged.rename(destination)
    return destination


def install_arguments(resources, home, state=None, *, choose=False, key=False):
    """Use permanent Python and a local bundle, preserving existing clients."""
    resources, home = Path(resources), Path(home)
    doc = metadata(resources)
    python = resources / 'runtime' / doc['runtime_exec']
    args = [str(python), str(resources / 'router' / 'packaging' / 'install.py'),
            '--python', str(python), '--home', str(home),
            '--feed', 'file://' + str(resources / 'payload' / 'latest.json')]
    if key:
        args.append('--setup')
    elif choose or not state:
        args.append('--choose-clients')
    else:
        args += ['--clients', state.get('clients', 'codex')]
    return args
