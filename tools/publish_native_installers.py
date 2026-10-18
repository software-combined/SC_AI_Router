"""Publish five verified native packages, then switch the public download page."""
import argparse
import hashlib
import importlib.util
import json
import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {'darwin/arm64', 'darwin/x86_64', 'windows/x86_64',
           'linux/arm64', 'linux/x86_64'}
ORIGIN = 'https://dist.softwarecombined.com'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


publisher = load('native_feed_publisher', ROOT / 'tools/publish_feed.py')
verify = load('native_feed_signatures', ROOT / 'packaging/feed_verify.py')


def packages(directory, channel):
    """Require one untampered artifact per target, all from the same bundle."""
    records, versions, bundles = {}, set(), set()
    for receipt in sorted(Path(directory).glob('*.json')):
        doc = json.loads(receipt.read_text())
        if not isinstance(doc, dict) or 'artifact_sha256' not in doc:
            continue
        name, target = doc.get('artifact'), doc.get('target')
        if (not isinstance(name, str) or Path(name).name != name or
                not re.fullmatch(r'SCG-Router-Installer-[A-Za-z0-9._-]+', name) or
                target not in TARGETS or target in records or
                not re.fullmatch(r'\d+(?:\.\d+){2,3}', str(doc.get('version', ''))) or
                doc.get('channel') != channel or doc.get('native_signature') != 'unsigned'):
            raise ValueError('invalid or duplicate native package receipt')
        artifact = Path(directory) / name
        if artifact.is_symlink():
            raise ValueError('unsafe native package link')
        with artifact.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != doc['artifact_sha256']:
            raise ValueError('native package checksum mismatch')
        if not re.fullmatch('[0-9a-f]{64}', str(doc.get('sha256', ''))):
            raise ValueError('native package bundle identity missing')
        versions.add(doc['version'])
        bundles.add(doc['sha256'])
        records[target] = {'target': target, 'name': name, 'sha256': doc['artifact_sha256']}
    if set(records) != TARGETS or len(versions) != 1 or len(bundles) != 1:
        raise ValueError('five packages from one exact release are required')
    version = versions.pop()
    rows = [records[target] for target in sorted(records)]
    for row in rows:
        row['url'] = ORIGIN + '/installers/' + version + '/' + row['name']
    return {'version': version, 'channel': channel, 'packages': rows}


def public_distribution(distribution):
    """Require the approved public software distribution before advertising it."""
    doc = json.loads(publisher._aws(['cloudfront', 'get-distribution-config',
                                   '--id', distribution, '--output', 'json']))['DistributionConfig']
    if ORIGIN.split('//')[1] not in doc.get('Aliases', {}).get('Items', []):
        raise ValueError('distribution does not serve the expected download origin')
    behaviors = {row['PathPattern']: row for row in doc.get('CacheBehaviors', {}).get('Items', [])}
    for path in ('/installers/*', '/install/*.json'):
        if path not in behaviors:
            raise ValueError('public download behavior is missing')
        trust = behaviors.get(path, {}).get('TrustedKeyGroups', {})
        if trust.get('Enabled') or trust.get('Items'):
            raise ValueError('download sign-in requirement is still active')
    if doc.get('DefaultCacheBehavior', {}).get('TrustedKeyGroups', {}).get('Enabled'):
        raise ValueError('update sign-in requirement is still active')


def publish(args):
    if args.channel != 'stable':
        raise ValueError('public native downloads use the stable channel only')
    directory = Path(args.artifacts)
    manifest = packages(directory, args.channel)
    # ponytail: published scope needs a new version; checksum inventories are immutable.
    if args.macos_arm64_only:
        manifest['scope'] = 'macos-arm64'
        manifest['packages'] = [row for row in manifest['packages'] if row['target'] == 'darwin/arm64']
    with tempfile.TemporaryDirectory() as temporary:
        stage = Path(temporary)
        version = manifest['version']
        prefix = 'installers/' + version + '/'
        checksums = ''.join(row['sha256'] + '  ' + row['name'] + '\n' for row in manifest['packages']).encode()
        if args.dry_run:
            print(json.dumps({'version': version, 'channel': args.channel,
                              'packages': len(manifest['packages']), 'public_downloads': True}))
            return 0
        public_distribution(args.distribution_id)
        seed = Path(args.sign).read_text().strip()
        signature = verify.sign_hex(seed, checksums)
        if not verify.verify_hex(verify.FEED_PUBLIC_KEY, checksums, signature):
            raise ValueError('checksum signer is not the trusted release signer')
        (stage / 'SHA256SUMS').write_bytes(checksums)
        (stage / 'SHA256SUMS.sig').write_text(signature + '\n')
        for row in manifest['packages']:
            publisher.publish_bundle(args.bucket, prefix + row['name'], directory / row['name'],
                                     row['sha256'], 'application/octet-stream')
        for name in ('SHA256SUMS', 'SHA256SUMS.sig'):
            body = stage / name
            publisher.publish_bundle(args.bucket, prefix + name, body,
                                     hashlib.sha256(body.read_bytes()).hexdigest(), 'text/plain')
        publisher.publish_setup_page(args.bucket)
        target = stage / 'downloads.json'
        target.write_text(json.dumps(manifest, indent=2) + '\n')
        publisher.publish_document(args.bucket, 'install/' + args.channel + '.json', target, 'no-store')
        publisher.invalidate(args.distribution_id, '/install/*')
        print('Published ' + args.channel + ' native installers ' + version)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', required=True)
    parser.add_argument('--channel', choices=('stable',), required=True)
    parser.add_argument('--bucket', required=True)
    parser.add_argument('--distribution-id', required=True)
    parser.add_argument('--sign', required=True)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--macos-arm64-only', action='store_true')
    return publish(parser.parse_args(argv))


if __name__ == '__main__':
    raise SystemExit(main())
