"""Copy Zenity and its Linux GUI dependency closure into Resources/gui."""

import json
import re
import shutil
import subprocess
from pathlib import Path

from native_stage import sha256_file


HERE = Path(__file__).resolve().parent
SYSTEM_ABI = ('libc.so.', 'libm.so.', 'libpthread.so.', 'libdl.so.',
              'librt.so.', 'libresolv.so.', 'ld-linux', 'ld-musl')


def _machine(path):
    with Path(path).open('rb') as stream:
        header = stream.read(20)
    if header[:4] != b'\x7fELF' or len(header) < 20:
        raise ValueError('Zenity must be an ELF executable')
    return int.from_bytes(header[18:20], 'little')


def _dependencies(binary):
    result = subprocess.run(['ldd', str(binary)], capture_output=True,
                            text=True, check=True)
    if 'not found' in result.stdout or 'not found' in result.stderr:
        raise ValueError('Zenity has unresolved shared libraries')
    paths = []
    for line in result.stdout.splitlines():
        match = re.search(r'(?:=>\s+)?(/\S+)\s+\(', line)
        if match:
            paths.append(Path(match.group(1)))
    return paths


def _copy_libs(binaries, libdir):
    copied = {}
    for binary in binaries:
        for source in _dependencies(binary):
            if source.name.startswith(SYSTEM_ABI):
                continue
            destination = libdir / source.name
            digest = sha256_file(source)
            if destination.name in copied and copied[destination.name] != digest:
                raise ValueError('conflicting Zenity shared library: ' + source.name)
            if destination.name not in copied:
                shutil.copyfile(source, destination)
                copied[destination.name] = digest
    return copied


def _matching_dirs(anchor, subpath):
    """Find matching multiarch data near a resolved system library."""
    candidates = [anchor / subpath, anchor.parent / subpath,
                  Path('/usr/lib') / subpath]
    return [path for path in candidates if path.is_dir()]


def bundle(zenity, resources, target):
    """Build from an Ubuntu runner with Zenity installed; no runtime apt need."""
    zenity = Path(zenity).resolve()
    if not zenity.is_file():
        raise ValueError('Zenity executable is missing')
    expected = {'linux/x86_64': 62, 'linux/arm64': 183}[target]
    if _machine(zenity) != expected:
        raise ValueError('Zenity architecture does not match target')
    gui = Path(resources) / 'gui'
    if gui.exists():
        raise ValueError('GUI payload already exists')
    bindir = gui / 'bin'
    libexec = gui / 'libexec'
    libdir = gui / 'lib'
    for path in (bindir, libexec, libdir):
        path.mkdir(parents=True)
    shutil.copyfile(zenity, libexec / 'zenity')
    (libexec / 'zenity').chmod(0o755)
    wrapper = bindir / 'zenity'
    shutil.copyfile(HERE / 'zenity-wrapper.sh', wrapper)
    wrapper.chmod(0o755)

    direct = _dependencies(zenity)
    copied = _copy_libs([zenity], libdir)
    anchors = sorted({path.parent for path in direct})
    typelib_dir = gui / 'lib' / 'girepository-1.0'
    typelib_dir.mkdir()
    for anchor in anchors:
        for directory in _matching_dirs(anchor, 'girepository-1.0'):
            for source in directory.glob('*.typelib'):
                shutil.copyfile(source, typelib_dir / source.name)
    schema = Path('/usr/share/glib-2.0/schemas/gschemas.compiled')
    if not schema.is_file():
        raise ValueError('compiled GTK settings schemas are missing')
    schema_dir = gui / 'share' / 'glib-2.0' / 'schemas'
    schema_dir.mkdir(parents=True)
    shutil.copyfile(schema, schema_dir / schema.name)

    loaders = []
    for anchor in anchors:
        for directory in _matching_dirs(anchor, 'gdk-pixbuf-2.0'):
            for source in directory.glob('*/loaders/*.so'):
                if source.name not in {item.name for item in loaders}:
                    loaders.append(source)
    if loaders:
        loader_dir = libdir / 'gdk-pixbuf' / 'loaders'
        loader_dir.mkdir(parents=True)
        for source in loaders:
            shutil.copyfile(source, loader_dir / source.name)
        copied.update(_copy_libs(loaders, libdir))
        query = shutil.which('gdk-pixbuf-query-loaders')
        if query is None:
            for anchor in anchors:
                found = (list(anchor.glob('gdk-pixbuf-2.0/gdk-pixbuf-query-loaders'))
                         + list(anchor.glob('gdk-pixbuf-2.0/*/gdk-pixbuf-query-loaders')))
                if found:
                    query = str(found[0])
                    break
        if query is None:
            raise ValueError('gdk-pixbuf-query-loaders is missing')
        shutil.copyfile(query, libexec / 'gdk-pixbuf-query-loaders')
        (libexec / 'gdk-pixbuf-query-loaders').chmod(0o755)
        copied.update(_copy_libs([query], libdir))
    manifest = {'zenity_sha256': sha256_file(zenity),
                'shared_libraries': copied,
                'typelibs': sorted(path.name for path in typelib_dir.iterdir()),
                'pixbuf_loaders': sorted(path.name for path in loaders),
                'schema_sha256': sha256_file(schema)}
    (gui / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest
