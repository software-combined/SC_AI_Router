"""Publish one built release to the public update feed (Plan 139).

Usage: python tools/publish_feed.py --dist dist --channel stable
       [--bucket B] [--distribution-id D] [--dry-run]

The release workflow runs this before it creates the GitHub Release, so the
feed always serves a release before the release page advertises it. The
feed and its bundles are public: readers need no credential.
"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

FEED_ORIGIN = 'https://dist.softwarecombined.com'
DEFAULT_BUCKET = 'router-feed-publication'
FEED_DOCUMENT = 'feed-latest.json'
RELEASE_DOCUMENT = 'release-latest.json'
BUNDLE_PREFIX = 'bundles/'
FEED_CACHE_CONTROL = 'public, max-age=60'
BUNDLE_CACHE_CONTROL = 'public, max-age=31536000, immutable'
CHANNELS = ('stable', 'beta')

# Subprocess seam: tests replace this with a recorder, never a real AWS call.
run = subprocess.run


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


def bundle_name(latest):
    """Bundle file name for a feed document, after checking its shape."""
    for field in ('version', 'url', 'sha256', 'serial', 'min_python'):
        if latest.get(field) in (None, ''):
            raise SystemExit(f'dist/latest.json is missing {field}')
    bundle = f"ai-router-{latest['version']}.tar.gz"
    if not str(latest['url']).endswith('/' + bundle):
        raise SystemExit("dist/latest.json url does not name this version's bundle")
    return bundle


def documents(latest, bundle):
    """Feed copy and release copy of the feed document.

    The feed copy points at the feed origin; the release copy keeps the URL
    packaging/release.py built (the GitHub Release asset). Both are public.
    """
    feed = dict(latest)
    feed['url'] = f'{FEED_ORIGIN}/{BUNDLE_PREFIX}{bundle}'
    feed.pop('feed_token', None)
    release = dict(latest)
    release.pop('feed_token', None)
    return feed, release


def bundle_state(bucket, key):
    """Recorded sha256 of an existing bundle, or None when it is absent.

    Only an explicit not-found counts as absent: any other head-object
    failure is fatal, because skipping the immutability check on a
    transient error could replace already-published bytes.
    """
    try:
        result = run(['aws', 's3api', 'head-object', '--bucket', bucket,
                      '--key', key, '--query', 'Metadata.sha256',
                      '--output', 'text'], capture_output=True, text=True)
    except OSError as exc:
        raise SystemExit(f'cannot run the aws CLI: {exc}')
    if result.returncode:
        stderr = result.stderr or ''
        if '404' in stderr or 'Not Found' in stderr:
            return None
        raise SystemExit(f'cannot read s3://{bucket}/{key}: {_clean(stderr)}')
    return (result.stdout or '').strip() or None


def publish_bundle(bucket, key, path, sha256):
    """Upload an immutable bundle once; refuse to replace different bytes."""
    existing = bundle_state(bucket, key)
    if existing == sha256:
        return 'already published'
    if existing:
        raise SystemExit(f'{key} holds a different sha256 ({existing[:12]}); '
                         'bundles are immutable')
    _aws(['s3', 'cp', str(path), f's3://{bucket}/{key}',
          '--cache-control', BUNDLE_CACHE_CONTROL,
          '--content-type', 'application/gzip',
          '--metadata', f'sha256={sha256}'])
    return 'uploaded'


def publish_document(bucket, key, path, cache_control):
    """Upload a cacheable feed document; the edge cache owns its freshness."""
    _aws(['s3', 'cp', str(path), f's3://{bucket}/{key}',
          '--cache-control', cache_control, '--content-type', 'application/json'])


def invalidate(distribution_id, path):
    """Drop one feed document from the edge cache; returns the request id."""
    return _aws(['cloudfront', 'create-invalidation', '--distribution-id',
                 distribution_id, '--paths', path, '--query', 'Invalidation.Id',
                 '--output', 'text'])


def _load_latest(dist):
    path = dist / 'latest.json'
    try:
        latest = json.loads(path.read_text())
    except FileNotFoundError:
        raise SystemExit(f'no {path}: run packaging/release.py first')
    except (OSError, ValueError):
        raise SystemExit(f'cannot read {path}')
    if not isinstance(latest, dict):
        raise SystemExit(f'{path} is not a feed document')
    return latest


def _check_bundle(dist, bundle, sha256):
    """The local bundle must be present and match the document checksum."""
    path = dist / bundle
    if not path.is_file():
        raise SystemExit(f'missing bundle {path}')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            digest.update(chunk)
    if digest.hexdigest() != sha256:
        raise SystemExit(f'{bundle} does not match the sha256 in latest.json')
    return path


def _describe(args, latest, bundle):
    """Dry-run plan: no AWS call, no file written."""
    print(f'dry run: channel={args.channel} version={latest["version"]}')
    print(f'dry run: bundle {bundle} sha256 {latest["sha256"][:12]}')
    print(f'dry run: would publish s3://{args.bucket}/{BUNDLE_PREFIX}{bundle} when absent')
    print(f'dry run: would publish s3://{args.bucket}/{args.channel}/latest.json')
    print(f'dry run: would publish s3://{args.bucket}/{args.channel}/models.json')
    print(f'dry run: would write {FEED_DOCUMENT} and {RELEASE_DOCUMENT} under {args.dist}')
    if args.distribution_id:
        print('dry run: would invalidate the channel feed document')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description='Publish a built release to the feed.')
    parser.add_argument('--dist', default='dist', help='directory packaging/release.py wrote')
    parser.add_argument('--channel', required=True, choices=CHANNELS)
    parser.add_argument('--bucket', default=DEFAULT_BUCKET)
    parser.add_argument('--distribution-id', default='')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    dist = Path(args.dist)
    latest = _load_latest(dist)
    bundle = bundle_name(latest)
    path = _check_bundle(dist, bundle, latest['sha256'])
    if args.dry_run:
        return _describe(args, latest, bundle)
    feed_doc, release_doc = documents(latest, bundle)
    (dist / FEED_DOCUMENT).write_text(json.dumps(feed_doc, indent=2) + '\n')
    (dist / RELEASE_DOCUMENT).write_text(json.dumps(release_doc, indent=2) + '\n')
    outcome = publish_bundle(args.bucket, BUNDLE_PREFIX + bundle, path, latest['sha256'])
    publish_document(args.bucket, f'{args.channel}/latest.json',
                     dist / FEED_DOCUMENT, FEED_CACHE_CONTROL)
    models_src = Path('ai_router/models.json')
    if models_src.is_file():
        publish_document(args.bucket, f'{args.channel}/models.json',
                         models_src, FEED_CACHE_CONTROL)
        print(f'published {args.channel} models.json')
    print(f'published {args.channel} {latest["version"]}: bundle {outcome}')
    if args.distribution_id:
        target = f'/{args.channel}/latest.json'
        print(f'invalidated {target} ({invalidate(args.distribution_id, target)})')
    else:
        print('no distribution id given; skipped invalidation, the 60 s cache expires on its own')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
