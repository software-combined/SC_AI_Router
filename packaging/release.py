"""Build a deterministic release bundle. Usage: python3 packaging/release.py --out dist [--build N] [--sha SHA] [--channel NAME] [--url-base URL] [--gen-key FILE] [--sign SEEDFILE]"""
import argparse
import gzip
import hashlib
import io
import json
import os
import sys
import tarfile
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_router import feed_verify

MIN_PYTHON = '3.14'
REPO = 'software-combined/SC_OpenRouter_adapter'


# Single release inventory (Plan 123): every non-globbed bundle member lives
# here. tests/test_packaging.py derives its expected bundle from
# bundle_files() and keeps an explicit required-files assertion, so a member
# dropped from this list still fails the gate.
PACKAGING_FILES = (
    'packaging/VERSION', 'packaging/install.py', 'packaging/launchd.py',
    'packaging/router_launch.py', 'packaging/service.py',
    'packaging/feed.py', 'packaging/atomic_write.py',
    'packaging/notice.py',
    'packaging/assets/router-icon.png',
    'packaging/systemd.py', 'packaging/update_launch.py',
    'packaging/updater.py', 'packaging/codex_config.py',
    'packaging/claude_config.py',
    'packaging/claude_desktop_config.py',
    'packaging/diagnostics.py', 'packaging/provider_keys.py',
    'packaging/runtime.lock', 'packaging/runtime_lock.py',
    'packaging/platforms/__init__.py',
    'packaging/platforms/darwin.py', 'packaging/platforms/linux.py',
    'packaging/platforms/windows.py',
    'packaging/install.sh', 'packaging/install.ps1',
    # Every installed release is a copy of the software delivered to a
    # user, so the licence terms and the Required Notice travel with it
    # (PolyForm Shield 1.0.0, Notices).
    'LICENSE', 'COMMERCIAL_LICENSE.md', 'THIRD_PARTY_NOTICES.md',
)


def bundle_files(root):
    return (
        sorted(p.relative_to(root).as_posix() for p in (root / 'ai_router').rglob('*.py'))
        + sorted(p.relative_to(root).as_posix() for p in (root / 'ai_router').glob('*.txt'))
        + sorted(p.relative_to(root).as_posix() for p in (root / 'ai_router').glob('*.json'))
        + sorted(p.relative_to(root).as_posix() for p in (root / 'tools').glob('*.py'))
        + list(PACKAGING_FILES)
    )


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    parser.add_argument('--build', type=int, default=0)
    parser.add_argument('--sha', default='')
    parser.add_argument('--channel', default='stable')
    parser.add_argument('--url-base')
    parser.add_argument('--feed-token-file', metavar='FILE',
                        help='read the feed read-token and embed it as latest.json feed_token '
                             '(publish-time only; never commit the file)')
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
    # The runtime lock must validate before any bundle ships: a broken pin
    # table must never reach a release artifact.
    _lock_spec = importlib.util.spec_from_file_location(
        'router_runtime_lock', root / 'packaging' / 'runtime_lock.py')
    _lock_mod = importlib.util.module_from_spec(_lock_spec)
    _lock_spec.loader.exec_module(_lock_mod)
    _lock_mod.validate(_lock_mod.load())
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
    tarball_name = f'ai-router-{version}.tar.gz'
    (out_dir / tarball_name).write_bytes(tarball)
    tag = f'v{version}' if args.channel == 'stable' else f'v{version}-beta'
    base = args.url_base or f'https://github.com/{REPO}/releases/download/{tag}'
    latest = {'version': version, 'url': f'{base}/{tarball_name}',
              'sha256': hashlib.sha256(tarball).hexdigest(), 'min_python': MIN_PYTHON,
              'serial': args.build,
              'published': datetime.now(timezone.utc).isoformat(timespec='seconds')}
    if args.feed_token_file:
        try:
            token = Path(args.feed_token_file).read_text().strip()
        except OSError:
            raise SystemExit('cannot read feed token file')
        if not token:
            raise SystemExit('feed token file is empty')
        latest['feed_token'] = token
    (out_dir / 'latest.json').write_text(json.dumps(latest, indent=2) + '\n')
    # The bootstrap resolves its runtime from this table, never from a
    # hardcoded filename: pins land only through reviewed lock changes.
    _lock_doc = _lock_mod.load()
    _lock_table = {e['os'] + '/' + e['cpu']: {
        'mirror': e['mirror'], 'sha256': e['sha256'], 'exec': e['exec']}
        for e in _lock_doc['targets']}
    (out_dir / 'runtimes.json').write_text(json.dumps(
        {'cpython': _lock_doc['cpython'], 'targets': _lock_table},
        indent=2) + '\n')
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
