"""Build unsigned native wrappers around an already validated Resources tree."""

import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from native_stage import sha256_file


HERE = Path(__file__).resolve().parent


def run(argv, **kwargs):
    subprocess.run([str(part) for part in argv], check=True, **kwargs)


def _new_output(out, name):
    artifact = Path(out) / name
    if artifact.exists() or artifact.is_symlink():
        raise ValueError('refusing to overwrite native artifact: ' + str(artifact))
    return artifact


def _make_icns(icon, destination):
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / 'router.iconset'
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            run(['sips', '-z', size, size, icon,
                 '--out', iconset / f'icon_{size}x{size}.png'])
            run(['sips', '-z', size * 2, size * 2, icon,
                 '--out', iconset / f'icon_{size}x{size}@2x.png'])
        run(['iconutil', '-c', 'icns', iconset, '-o', destination])


def mac(resources, out, version, cpu):
    if sys.platform != 'darwin':
        raise ValueError('macOS DMG build requires macOS')
    out = Path(out)
    name = f'SCG-Router-Installer-{version}-macOS-{cpu}.dmg'
    final = _new_output(out, name)
    with tempfile.TemporaryDirectory(dir=out) as tmp:
        tmp = Path(tmp)
        app = tmp / 'Install SCG Router.app'
        contents = app / 'Contents'
        (contents / 'MacOS').mkdir(parents=True)
        shutil.copytree(resources, contents / 'Resources')
        launcher = contents / 'MacOS' / 'Install SCG Router'
        shutil.copyfile(HERE / 'mac-launcher.sh', launcher)
        launcher.chmod(0o755)
        info = {
            'CFBundleName': 'Install SCG Router',
            'CFBundleDisplayName': 'Install SCG Router',
            'CFBundleExecutable': 'Install SCG Router',
            'CFBundleIdentifier': 'com.softwarecombined.scg-router-installer',
            'CFBundlePackageType': 'APPL',
            'CFBundleShortVersionString': '.'.join(version.split('.')[:3]),
            'CFBundleVersion': version,
            'CFBundleIconFile': 'router.icns',
            'NSHighResolutionCapable': True,
        }
        (contents / 'Info.plist').write_bytes(plistlib.dumps(info))
        icon = resources / 'router' / 'packaging' / 'assets' / 'router-icon.png'
        if not icon.is_file():
            raise ValueError('bundle lacks product icon')
        _make_icns(icon, contents / 'Resources' / 'router.icns')
        temp_dmg = tmp / name
        run(['hdiutil', 'create', '-format', 'UDZO', '-volname',
             'Install SCG Router', '-srcfolder', app, temp_dmg])
        if not temp_dmg.is_file():
            raise ValueError('hdiutil did not produce a DMG')
        shutil.move(temp_dmg, final)
    return final


def windows(resources, out, version, *, iscc='ISCC.exe'):
    if sys.platform != 'win32':
        raise ValueError('Windows EXE build requires Windows')
    out = Path(out)
    name = f'SCG-Router-Installer-{version}-Windows.exe'
    final = _new_output(out, name)
    _make_ico(resources / 'router/packaging/assets/router-icon.png', resources / 'router-icon.ico')
    with tempfile.TemporaryDirectory(dir=out) as tmp:
        tmp = Path(tmp)
        script = (HERE / 'windows.iss').read_text()
        fields = {
            '@RESOURCES@': str(resources.resolve()),
            '@OUTPUT@': str(tmp.resolve()),
            '@VERSION@': version,
            '@ICON@': str((resources / 'router-icon.ico').resolve()),
        }
        for token, value in fields.items():
            if '"' in value or '\n' in value:
                raise ValueError('unsupported Inno Setup path or version')
            script = script.replace(token, value)
        iss = tmp / 'installer.iss'
        iss.write_text(script)
        run([iscc, iss])
        artifact = tmp / name
        if not artifact.is_file():
            raise ValueError('Inno Setup did not produce an EXE')
        shutil.move(artifact, final)
    return final


def _make_ico(source, destination):
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    script = ("$ErrorActionPreference='Stop';Add-Type -AssemblyName System.Drawing;"
              "$source=[Drawing.Image]::FromFile(%s);"
              "$bitmap=New-Object Drawing.Bitmap($source,256,256);"
              "$icon=[Drawing.Icon]::FromHandle($bitmap.GetHicon());"
              "$stream=[IO.File]::Create(%s);"
              "try{$icon.Save($stream)}finally{$stream.Dispose();$icon.Dispose();"
              "$bitmap.Dispose();$source.Dispose()}" % (quote(source), quote(destination)))
    run(['powershell', '-NoProfile', '-Command', script], capture_output=True, timeout=30)
    if not Path(destination).is_file():
        raise ValueError('product icon could not be prepared')


def _pinned(path, sha, what):
    path = Path(path).resolve()
    if not path.is_file() or sha256_file(path) != sha:
        raise ValueError(what + ' does not match its pinned sha256')
    return path


def _uruntime(runtime, sha, cpu, destination):
    runtime = _pinned(runtime, sha, 'uruntime')
    data = runtime.read_bytes()
    machine = {'x86_64': 62, 'arm64': 183}[cpu]
    if (data[:4] != b'\x7fELF' or len(data) < 20 or data[4] != 2
            or data[5] != 1 or int.from_bytes(data[18:20], 'little') != machine):
        raise ValueError('uruntime architecture does not match target')
    old = b'URUNTIME_EXTRACT=3'
    enabled = b'URUNTIME_EXTRACT=2'
    if data.count(old) == 1:
        data = data.replace(old, enabled)
    elif data.count(enabled) != 1:
        raise ValueError('uruntime has no verifiable automatic extract fallback')
    destination.write_bytes(data)
    destination.chmod(0o755)


def linux(resources, out, version, cpu, *, appimagetool, appimagetool_sha256,
          uruntime, uruntime_sha256):
    if not sys.platform.startswith('linux'):
        raise ValueError('AppImage build requires Linux')
    tool = _pinned(appimagetool, appimagetool_sha256, 'appimagetool')
    out = Path(out)
    arch = 'aarch64' if cpu == 'arm64' else 'x86_64'
    name = f'SCG-Router-Installer-{version}-Linux-{arch}.AppImage'
    final = _new_output(out, name)
    with tempfile.TemporaryDirectory(dir=out) as tmp:
        tmp = Path(tmp)
        appdir = tmp / 'SCG-Router.AppDir'
        appdir.mkdir()
        shutil.copytree(resources, appdir / 'Resources')
        launcher = appdir / 'AppRun'
        shutil.copyfile(HERE / 'linux-AppRun', launcher)
        launcher.chmod(0o755)
        icon = resources / 'router' / 'packaging' / 'assets' / 'router-icon.png'
        if not icon.is_file():
            raise ValueError('bundle lacks product icon')
        shutil.copyfile(icon, appdir / 'router.png')
        shutil.copyfile(HERE / 'router.desktop', appdir / 'router.desktop')
        embedded = tmp / 'uruntime'
        _uruntime(uruntime, uruntime_sha256, cpu, embedded)
        artifact = tmp / name
        env = dict(os.environ, ARCH=arch, APPIMAGE_EXTRACT_AND_RUN='1')
        run([tool, '--runtime-file', embedded, '-n', appdir, artifact], env=env)
        if not artifact.is_file():
            raise ValueError('appimagetool did not produce an AppImage')
        artifact.chmod(0o755)
        shutil.move(artifact, final)
    return final


def receipt(artifact, metadata):
    """Keep unsigned provenance beside the user-facing artifact."""
    artifact = Path(artifact)
    path = artifact.with_suffix(artifact.suffix + '.json')
    doc = {'artifact': artifact.name, 'artifact_sha256': sha256_file(artifact),
           'native_signature': 'unsigned', **metadata}
    path.write_text(json.dumps(doc, indent=2) + '\n')
    return path
