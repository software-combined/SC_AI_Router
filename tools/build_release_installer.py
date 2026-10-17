"""Native runner entry point: fetch pinned build inputs, then build one package."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def download(spec, destination):
    if not spec['url'].startswith('https://github.com/'):
        raise ValueError('build input is not a pinned upstream release')
    digest = hashlib.sha256()
    size = 0
    with urllib.request.urlopen(spec['url'], timeout=60) as response, destination.open('wb') as stream:
        while chunk := response.read(1024 * 1024):
            size += len(chunk)
            if size > 250 * 1024 * 1024:
                raise ValueError('build input exceeds size limit')
            stream.write(chunk)
            digest.update(chunk)
    if digest.hexdigest() != spec['sha256']:
        raise ValueError('build input checksum mismatch')
    destination.chmod(0o755)
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', required=True)
    parser.add_argument('--dist', type=Path, default=Path('dist'))
    parser.add_argument('--out', type=Path, default=Path('native-artifacts'))
    parser.add_argument('--download-config', type=Path)
    args = parser.parse_args(argv)
    latest = json.loads((args.dist / 'latest.json').read_text())
    if not args.download_config and (args.dist / 'download-auth.json').is_file():
        args.download_config = args.dist / 'download-auth.json'
    system, cpu = args.target.split('/')
    lock = json.loads((ROOT / 'packaging/runtime.lock').read_text())
    entries = [row for row in lock['targets'] if (row['os'], row['cpu']) == (system, cpu)]
    if len(entries) != 1:
        raise ValueError('unsupported native build target')
    with tempfile.TemporaryDirectory() as temporary:
        folder = Path(temporary)
        if not args.download_config and latest.get('download_auth'):
            args.download_config = folder / 'download-auth.json'
            args.download_config.write_text(json.dumps(latest['download_auth']))
        runtime = download(entries[0], folder / 'runtime.tar.gz')
        bundle = args.dist / ('ai-router-' + latest['version'] + '.tar.gz')
        with bundle.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != latest['sha256']:
                raise ValueError('release bundle checksum mismatch')
        command = [sys.executable, str(ROOT / 'tools/build_native_installer.py'),
                   '--bundle', str(bundle), '--runtime', str(runtime), '--target', args.target,
                   '--channel', latest['channel'], '--out', str(args.out)]
        if args.download_config:
            command += ['--download-config', str(args.download_config)]
        if system == 'windows':
            compiler = Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Inno Setup 6/ISCC.exe'
            command += ['--windows-iscc', str(compiler)]
        if system == 'linux':
            tools = json.loads((ROOT / 'packaging/native/build-tools.json').read_text())[args.target]
            command += ['--linux-zenity', shutil.which('zenity') or '/usr/bin/zenity']
            for name, spec in tools.items():
                path = download(spec, folder / name)
                command += ['--linux-' + name, str(path), '--linux-' + name + '-sha256', spec['sha256']]
        subprocess.run(command, check=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
