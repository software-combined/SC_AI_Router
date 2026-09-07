"""Build a deterministic release bundle. Usage: python3 packaging/release.py --out dist [--url-base URL]"""
import argparse
import gzip
import hashlib
import io
import json
import tarfile
from datetime import datetime, timezone
from pathlib import Path

MIN_PYTHON = '3.14'
REPO = 'software-combined/SC_Codex_openRouter_adapter'


def bundle_files(root):
    return (
        sorted(str(p.relative_to(root)) for p in (root / 'codex_router').rglob('*.py'))
        + sorted(str(p.relative_to(root)) for p in (root / 'codex_router').glob('*.txt'))
        + sorted(str(p.relative_to(root)) for p in (root / 'codex_router').glob('*.json'))
        + sorted(str(p.relative_to(root)) for p in (root / 'tools').glob('*.py'))
        + ['packaging/VERSION', 'packaging/install.py']
    )


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    parser.add_argument('--url-base')
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    version = (root / 'packaging' / 'VERSION').read_text().strip()
    names = bundle_files(root)
    manifest_files = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}
    manifest = {'version': version, 'files': manifest_files,
                'codex_tested': 'unknown', 'min_python': MIN_PYTHON}
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode='w', format=tarfile.PAX_FORMAT) as tar:
        for name in names + ['MANIFEST.json']:
            data = (json.dumps(manifest, indent=2) + '\n').encode() if name == 'MANIFEST.json' else (root / name).read_bytes()
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
    base = args.url_base or f'https://github.com/{REPO}/releases/download/v{version}'
    latest = {'version': version, 'url': f'{base}/{tarball_name}',
              'sha256': hashlib.sha256(tarball).hexdigest(), 'min_python': MIN_PYTHON,
              'published': datetime.now(timezone.utc).isoformat(timespec='seconds')}
    (out_dir / 'latest.json').write_text(json.dumps(latest, indent=2) + '\n')
    print(f'built {tarball_name} {latest["sha256"][:12]}')


if __name__ == '__main__':
    main()
