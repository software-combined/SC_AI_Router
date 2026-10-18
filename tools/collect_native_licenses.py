"""Regenerate Linux helper notices from the checksum-pinned crate archives."""
import hashlib
import io
import tarfile
import tomllib
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'packaging/native/menu/linux'


def notices(package):
    name, version = package['name'], package['version']
    url = 'https://static.crates.io/crates/%s/%s-%s.crate' % (name, name, version)
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != package['checksum']:
        raise ValueError('Crate checksum mismatch: ' + name)
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        prefix = name + '-' + version + '/'
        manifest = tomllib.loads(archive.extractfile(prefix + 'Cargo.toml').read().decode())
        texts = []
        for member in archive.getmembers():
            relative = member.name.removeprefix(prefix)
            if member.isfile() and (('/' not in relative and relative.upper().startswith(
                    ('LICENSE', 'LICENCE', 'UNLICENSE', 'COPYING', 'COPYRIGHT', 'AUTHORS')))
                    or relative.upper().startswith('LICENSES/')):
                texts.append(archive.extractfile(member).read().decode().strip())
        if not texts:
            raise ValueError('No bundled licence text: ' + name)
        return name + ' ' + version + ' (' + manifest['package']['license'] + ')', texts


def main():
    packages = [p for p in tomllib.loads((ROOT / 'Cargo.lock').read_text())['package'] if 'source' in p]
    grouped = {}
    with ThreadPoolExecutor(max_workers=8) as worker:
        for identity, texts in worker.map(notices, packages):
            for content in texts:
                grouped.setdefault(content, []).append(identity)
    document = ['Third-party licences for SCG Router Linux menu helper.',
                'Generated from Cargo.lock; every downloaded archive checksum was verified.',
                'Both offered licences are retained for dual-licensed dependencies.']
    for content, identities in grouped.items():
        document += ['\n' + '=' * 72, '\n'.join(identities), '\n' + content]
    (ROOT / 'NOTICES.txt').write_text('\n'.join(document) + '\n')
    print('Retained licence notices for %d pinned crates.' % len(packages))


if __name__ == '__main__':
    main()
