"""Publish first-install assets to the token-gated feed (Plan 139 follow-up).

Usage: python tools/publish_first_install.py [--bucket B] [--dry-run]

Bundles and channel documents belong to tools/publish_feed.py; this tool
owns the reserved first-install keys a machine needs to install without
repository access: `runtimes.json`, `runtimes/*` (the pinned CPython
builds) and `bootstrap/*` (the two wrapper scripts). It reads
packaging/runtime.lock, downloads each pinned runtime, verifies the sha256
before anything is uploaded, and is idempotent: an artifact whose recorded
sha256 already matches is skipped.

The `runtimes/*` mirrors are immutable (a different sha under a mirror key
is refused). The two `bootstrap/*` wrappers are the one mutable entry
point: they are replaced when they change and cached for five minutes, so
a wrapper fix can still reach new installers. The operator's AWS
credentials do the upload; the feed token gates reads at the edge, not
writes, so this tool never handles it.
"""
import argparse
import hashlib
import importlib.util as _ilu
import json
import subprocess
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUCKET = 'router-feed-publication'
RUNTIMES_DOCUMENT = 'runtimes.json'
BOOTSTRAP_PREFIX = 'bootstrap/'
BOOTSTRAP_FILES = ('bootstrap.sh', 'bootstrap.ps1')
DOCUMENT_CACHE_CONTROL = 'public, max-age=60'
BOOTSTRAP_CACHE_CONTROL = 'public, max-age=300'
IMMUTABLE_CACHE_CONTROL = 'public, max-age=31536000, immutable'

# Subprocess seam: tests replace this with a recorder, never a real AWS call.
run = subprocess.run
# Download seam: tests replace this with local bytes, never a real fetch.
download = urllib.request.urlopen


def _clean(text):
    """One bounded line of CLI error text."""
    return ' '.join((text or '').split())[:300]


def _aws(args):
    """Run one aws CLI command and return its stripped stdout."""
    try:
        result = run(['aws', *args], capture_output=True, text=True)
    except OSError as exc:
        raise SystemExit(f'cannot run the aws CLI: {exc}')
    if result.returncode:
        raise SystemExit(f'aws {args[0]} failed: {_clean(result.stderr)}')
    return (result.stdout or '').strip()


def load_lock():
    """packaging/runtime.lock, loaded and validated the installer's way."""
    spec = _ilu.spec_from_file_location(
        'router_runtime_lock', ROOT / 'packaging' / 'runtime_lock.py')
    module = _ilu.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.validate(module.load())


def runtimes_document(doc):
    """The feed's runtimes.json table, keyed the way bootstrap.sh reads it."""
    return {'cpython': doc['cpython'], 'targets': {
        e['os'] + '/' + e['cpu']: {'mirror': e['mirror'], 'sha256': e['sha256'],
                                   'exec': e['exec']}
        for e in doc['targets']}}


def object_state(bucket, key):
    """Recorded sha256 of an existing object, or None when it is absent."""
    result = run(['aws', 's3api', 'head-object', '--bucket', bucket,
                  '--key', key, '--query', 'Metadata.sha256',
                  '--output', 'text'], capture_output=True, text=True)
    if result.returncode:
        stderr = result.stderr or ''
        if '404' in stderr or 'Not Found' in stderr:
            return None
        raise SystemExit(f'cannot read s3://{bucket}/{key}: {_clean(stderr)}')
    return (result.stdout or '').strip() or None


def _guard(bucket, key, sha256):
    """True when the key already holds these bytes; refuse different bytes."""
    existing = object_state(bucket, key)
    if existing and existing != sha256:
        raise SystemExit(f'{key} holds a different sha256 ({existing[:12]}); '
                         'artifacts are immutable')
    return existing == sha256


def _upload(bucket, key, path, sha256, cache_control, content_type):
    _aws(['s3', 'cp', str(path), f's3://{bucket}/{key}',
          '--cache-control', cache_control, '--content-type', content_type,
          '--metadata', f'sha256={sha256}'])


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_verified(url, sha256, dest):
    """Download one runtime; keep it only when it matches the pinned digest."""
    digest = hashlib.sha256()
    try:
        with download(url) as stream, dest.open('wb') as out:
            for chunk in iter(lambda: stream.read(1 << 20), b''):
                out.write(chunk)
                digest.update(chunk)
    except OSError as exc:
        raise SystemExit(f'cannot download {url}: {_clean(str(exc))}')
    if digest.hexdigest() != sha256:
        raise SystemExit(f'{url} does not match the pinned sha256')


def publish_runtime(bucket, entry, tmp):
    """Verify and publish one pinned runtime; skip or refuse on state."""
    key = entry['mirror']
    if _guard(bucket, key, entry['sha256']):
        return 'already published'
    local = tmp / Path(key).name
    fetch_verified(entry['url'], entry['sha256'], local)
    _upload(bucket, key, local, entry['sha256'], IMMUTABLE_CACHE_CONTROL,
            'application/gzip')
    return 'uploaded'


def publish_bootstrap(bucket, name):
    """Publish one wrapper script; the mutable entry point, so it may change."""
    path = ROOT / 'packaging' / name
    if not path.is_file():
        raise SystemExit(f'missing {path}')
    sha256 = sha256_file(path)
    if object_state(bucket, BOOTSTRAP_PREFIX + name) == sha256:
        return 'already published'
    content_type = 'text/x-shellscript' if name.endswith('.sh') else 'text/plain'
    _upload(bucket, BOOTSTRAP_PREFIX + name, path, sha256,
            BOOTSTRAP_CACHE_CONTROL, content_type)
    return 'uploaded'


def _describe(args):
    """Dry-run plan: no network, no AWS call, nothing written."""
    doc = load_lock()
    print(f'dry run: {len(doc["targets"])} runtimes from the lock '
          f'(cpython {doc["cpython"]})')
    for entry in doc['targets']:
        print(f'dry run: would verify and publish s3://{args.bucket}/{entry["mirror"]}')
    print(f'dry run: would publish s3://{args.bucket}/{RUNTIMES_DOCUMENT}')
    for name in BOOTSTRAP_FILES:
        print(f'dry run: would publish s3://{args.bucket}/{BOOTSTRAP_PREFIX}{name} last')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Publish first-install runtimes and bootstrap to the feed.')
    parser.add_argument('--bucket', default=DEFAULT_BUCKET)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    if args.dry_run:
        return _describe(args)
    doc = load_lock()
    for name in BOOTSTRAP_FILES:
        if not (ROOT / 'packaging' / name).is_file():
            raise SystemExit(f'missing {ROOT / "packaging" / name}')
    # Runtimes first, then the table that names them, then the wrappers:
    # the advertised entry point is written only after everything it
    # fetches exists, and a partial run never leaves it 404ing.
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for entry in doc['targets']:
            print(f'{entry["mirror"]}: '
                  f'{publish_runtime(args.bucket, entry, tmp)}')
        table = tmp / RUNTIMES_DOCUMENT
        table.write_text(json.dumps(runtimes_document(doc), indent=2) + '\n')
        _aws(['s3', 'cp', str(table), f's3://{args.bucket}/{RUNTIMES_DOCUMENT}',
              '--cache-control', DOCUMENT_CACHE_CONTROL,
              '--content-type', 'application/json'])
        print(f'{RUNTIMES_DOCUMENT}: published')
    for name in BOOTSTRAP_FILES:
        print(f'{BOOTSTRAP_PREFIX}{name}: {publish_bootstrap(args.bucket, name)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
