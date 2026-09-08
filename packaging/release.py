"""Build a deterministic release bundle. Usage: python3 packaging/release.py --out dist [--build N] [--sha SHA] [--channel NAME] [--url-base URL] [--gen-key FILE] [--sign SEEDFILE]"""
import argparse
import gzip
import hashlib
import io
import json
import os
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codex_router import feed_verify

MIN_PYTHON = '3.14'
REPO = 'software-combined/SC_OpenRouter_adapter'


def bundle_files(root):
    return (
        sorted(str(p.relative_to(root)) for p in (root / 'codex_router').rglob('*.py'))
        + sorted(str(p.relative_to(root)) for p in (root / 'codex_router').glob('*.txt'))
        + sorted(str(p.relative_to(root)) for p in (root / 'codex_router').glob('*.json'))
        + sorted(str(p.relative_to(root)) for p in (root / 'tools').glob('*.py'))
        + ['packaging/VERSION', 'packaging/install.py', 'packaging/router_launch.py']
    )


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    parser.add_argument('--build', type=int, default=0)
    parser.add_argument('--sha', default='')
    parser.add_argument('--channel', default='stable')
    parser.add_argument('--url-base')
    parser.add_argument('--gen-key', metavar='OUT',
                        help='write a fresh 32-byte hex release signing seed (owner-only file) and exit')
    parser.add_argument('--sign', metavar='SEEDFILE',
                        help='write latest.json.sig (hex detached signature) for this build')
    args = parser.parse_args(argv)
    if args.gen_key:
        out = Path(args.gen_key)
        try:
            fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            raise SystemExit(f'refusing to overwrite release seed {out}')
        with os.fdopen(fd, 'w') as stream:
            stream.write(feed_verify.generate_keypair()[0] + '\n')
        print(f'wrote release signing seed to {out}; compile its public key into feed_verify.FEED_PUBLIC_KEY')
        return
    root = Path(__file__).resolve().parents[1]
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    base_version = (root / 'packaging' / 'VERSION').read_text().strip()
    if args.build < 0:
        raise SystemExit('--build must be >= 0')
    version = f'{base_version}.{args.build}'
    names = bundle_files(root)
    # Stamp the composed version into the bundled marker so installed
    # releases report what the updater compares (current_version, /health).
    payloads = {name: (version + '\n').encode() if name == 'packaging/VERSION'
                else (root / name).read_bytes() for name in names}
    manifest_files = {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()}
    manifest = {'version': version, 'files': manifest_files,
                'codex_tested': 'unknown', 'min_python': MIN_PYTHON,
                'git_sha': args.sha, 'channel': args.channel}
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode='w', format=tarfile.PAX_FORMAT) as tar:
        for name in names + ['MANIFEST.json']:
            data = (json.dumps(manifest, indent=2) + '\n').encode() if name == 'MANIFEST.json' else payloads[name]
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = ''
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    tarball = gzip.compress(tar_buffer.getvalue(), mtime=0)
    tarball_name = f'codex-model-router-{version}.tar.gz'
    (out_dir / tarball_name).write_bytes(tarball)
    tag = f'v{version}' if args.channel == 'stable' else f'v{version}-beta'
    base = args.url_base or f'https://github.com/{REPO}/releases/download/{tag}'
    latest = {'version': version, 'url': f'{base}/{tarball_name}',
              'sha256': hashlib.sha256(tarball).hexdigest(), 'min_python': MIN_PYTHON,
              'serial': args.build,
              'published': datetime.now(timezone.utc).isoformat(timespec='seconds')}
    (out_dir / 'latest.json').write_text(json.dumps(latest, indent=2) + '\n')
    if args.sign:
        try:
            seed = Path(args.sign).read_text().strip()
        except OSError:
            raise SystemExit('cannot read release signing seed')
        (out_dir / 'latest.json.sig').write_text(
            feed_verify.sign_hex(seed, (out_dir / 'latest.json').read_bytes()) + '\n')
    print(f'built {tarball_name} {latest["sha256"][:12]}')


if __name__ == '__main__':
    main()
