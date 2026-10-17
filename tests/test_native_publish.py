"""Native publication is complete, immutable and protected before advertising."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.test_download_auth import load

publish = load('native_publish_under_test', 'tools/publish_native_installers.py')


def artifacts(directory):
    for index, target in enumerate(sorted(publish.TARGETS)):
        name = 'SCG-Router-Installer-1.2.3.4-' + str(index) + '.dmg'
        body = ('native package ' + target).encode()
        (directory / name).write_bytes(body)
        (directory / (name + '.json')).write_text(json.dumps({
            'artifact': name, 'target': target, 'version': '1.2.3.4', 'channel': 'beta',
            'native_signature': 'unsigned', 'sha256': 'a' * 64,
            'artifact_sha256': hashlib.sha256(body).hexdigest()}))


def distribution(protected=False):
    group = {'Enabled': protected, 'Items': ['reviewed-key-group'] if protected else []}
    return json.dumps({'DistributionConfig': {
        'Aliases': {'Items': ['dist.softwarecombined.com']},
        'CacheBehaviors': {'Items': [
            {'PathPattern': '/installers/*', 'TrustedKeyGroups': group},
            {'PathPattern': '/install/*.json', 'TrustedKeyGroups': group},
            {'PathPattern': '/download-access', 'TargetOriginId': 'exchange'}]},
        'Origins': {'Items': [{'Id': 'exchange',
            'DomainName': 'abc123.execute-api.ap-southeast-2.amazonaws.com'}]}}})


class NativePublishTests(unittest.TestCase):
    def test_unaccepted_builds_cannot_be_downloaded_through_cloudfront(self):
        template = (publish.ROOT / 'infra/feed.yaml').read_text()
        deny = template.split('Sid: NativeBuildsNeverThroughCloudFront', 1)[1].split('- Sid:', 1)[0]
        for required in ('Effect: Deny', 'Service: cloudfront.amazonaws.com',
                         'Action: s3:GetObject', '${FeedBucket.Arn}/native-builds/*'):
            self.assertIn(required, deny)

    def test_publisher_can_check_protection_on_only_its_distribution(self):
        template = (publish.ROOT / 'infra/feed.yaml').read_text()
        grant = template.split('- cloudfront:CreateInvalidation', 1)[1].split('- Effect:', 1)[0]
        self.assertIn('cloudfront:GetDistributionConfig', grant)
        self.assertIn('Resource: !Sub arn:aws:cloudfront::${AWS::AccountId}:distribution/${Distribution}', grant)

    def test_download_access_is_public_and_origin_storage_stays_private(self):
        text = (publish.ROOT / 'infra/feed.yaml').read_text()
        self.assertNotIn('TrustedKeyGroups:', text)
        for guard in ('BlockPublicAcls: true', 'BlockPublicPolicy: true',
                      'IgnorePublicAcls: true', 'RestrictPublicBuckets: true',
                      'OriginAccessControlId:', 'NativeBuildsNeverThroughCloudFront'):
            self.assertIn(guard, text)

    def test_missing_platform_and_tampered_bytes_block_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifacts(root)
            result = publish.packages(root, 'beta')
            self.assertEqual({row['target'] for row in result['packages']}, publish.TARGETS)
            first = root / result['packages'][0]['name']
            first.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                publish.packages(root, 'beta')
            first.with_suffix(first.suffix + '.json').unlink()
            with self.assertRaisesRegex(ValueError, 'five packages'):
                publish.packages(root, 'beta')

    def test_private_edge_blocks_public_release_before_any_upload(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifacts(root)
            args = SimpleNamespace(pilot_macos_arm64=False, artifacts=root, channel='beta',
                                   dry_run=False, sign=root / 'absent-secret',
                                   bucket='test-bucket', distribution_id='test-distribution')
            with mock.patch.object(publish.publisher, '_aws', return_value=distribution(True)), \
                    mock.patch.object(publish.publisher, 'publish_bundle') as upload:
                with self.assertRaisesRegex(ValueError, 'sign-in requirement'):
                    publish.publish(args)
                upload.assert_not_called()

    def test_packages_and_signed_checksums_precede_the_channel_switch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifacts(root)
            seed, public = publish.verify.generate_keypair()
            secret = root / 'ephemeral-test-key'
            secret.write_text(seed)
            args = SimpleNamespace(pilot_macos_arm64=False, artifacts=root, channel='beta',
                                   dry_run=False, sign=secret, bucket='test-bucket',
                                   distribution_id='test-distribution')
            writes, contents = [], {}
            def upload(bucket, key, path, *unused):
                writes.append(key)
                contents[key] = Path(path).read_bytes()
            with mock.patch.object(publish.publisher, '_aws', return_value=distribution()), \
                    mock.patch.object(publish.publisher, 'publish_bundle', side_effect=upload), \
                    mock.patch.object(publish.publisher, 'publish_document', side_effect=upload), \
                    mock.patch.object(publish.publisher, 'invalidate'), \
                    mock.patch.object(publish.verify, 'FEED_PUBLIC_KEY', public):
                self.assertEqual(publish.publish(args), 0)
            self.assertEqual(writes[-1], 'install/beta.json')
            base = 'installers/1.2.3.4/'
            self.assertEqual(len([name for name in writes if name.endswith('.dmg')]), 5)
            self.assertTrue(publish.verify.verify_hex(public, contents[base + 'SHA256SUMS'],
                                                     contents[base + 'SHA256SUMS.sig'].decode().strip()))
            writes.clear()
            args.pilot_macos_arm64 = True
            with mock.patch.object(publish.publisher, '_aws', return_value=distribution()), \
                    mock.patch.object(publish.publisher, 'publish_bundle', side_effect=upload), \
                    mock.patch.object(publish.publisher, 'publish_document', side_effect=upload), \
                    mock.patch.object(publish.publisher, 'invalidate'), \
                    mock.patch.object(publish.verify, 'FEED_PUBLIC_KEY', public):
                self.assertEqual(publish.publish(args), 0)
            advertised = json.loads(contents['install/beta.json'])
            self.assertTrue(advertised['pilot'])
            self.assertEqual([row['target'] for row in advertised['packages']], ['darwin/arm64'])
            self.assertEqual(len([name for name in writes if name.endswith('.dmg')]), 1)
            self.assertEqual(writes[-1], 'install/beta.json')


if __name__ == '__main__':
    unittest.main()
