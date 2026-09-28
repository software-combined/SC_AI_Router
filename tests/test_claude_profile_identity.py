"""Native identity sources, distinct from task transfer and historical folders."""
import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.claude_profile_sync_fixtures import fingerprint, load_helper

identity = load_helper('claude_profile_identity')
ACCOUNT = '12345678-1234-4567-8123-123456789abc'
ORGANIZATION = 'abcdefab-1234-4567-8123-123456789abc'


class NativeIdentityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.profile = Path(temp.name).resolve() / 'custom-third'
        library = self.profile / 'configLibrary'
        library.mkdir(parents=True)
        (library / '_meta.json').write_text(json.dumps({'appliedId': ACCOUNT}))
        self.entry = library / (ACCOUNT + '.json')
        self.entry.write_text(json.dumps({
            'inferenceProvider': 'gateway', 'inferenceCredentialKind': 'static',
            'inferenceGatewayApiKey': 'synthetic-key',
            'deploymentOrganizationUuid': ORGANIZATION}))
        self.device = self.profile / 'ant-did'
        self.device.write_bytes(base64.b64encode(ACCOUNT.encode()))
        (self.profile / 'config.json').write_text(json.dumps({
            'lastKnownAccountUuid': ORGANIZATION, 'lastKnownOrganizationUuid': ACCOUNT}))
        patcher = mock.patch.object(identity._policy, 'managed_connection', return_value=False)
        self.managed = patcher.start()
        self.addCleanup(patcher.stop)

    def change_entry(self, **fields):
        doc = json.loads(self.entry.read_bytes())
        doc.update(fields)
        self.entry.write_text(json.dumps(doc))

    def test_third_party_identity_uses_device_not_cached_subscription_identity(self):
        self.assertEqual(identity.third_party(self.profile), (ACCOUNT, ORGANIZATION))

    def test_cached_subscription_fields_and_history_are_not_identity_authority(self):
        for store in ('local-agent-mode-sessions', 'claude-code-sessions'):
            (self.profile / store / ORGANIZATION / ACCOUNT).mkdir(parents=True)
            before = fingerprint(self.profile)
            self.assertIsNone(identity.subscription(self.profile))
            self.assertEqual(fingerprint(self.profile), before)

    def test_static_gateway_uses_vendor_default_when_org_is_unset(self):
        self.change_entry(deploymentOrganizationUuid=None)
        self.assertEqual(identity.third_party(self.profile), (ACCOUNT, identity.STATIC_ORGANIZATION))
        self.change_entry(deploymentOrganizationUuid='not-a-uuid')
        self.assertIsNone(identity.third_party(self.profile))

    def test_managed_bootstrap_and_nonstatic_connections_are_not_guessed(self):
        original = self.entry.read_bytes()
        for fields in ({'bootstrapUrl': 'https://bootstrap.example'},
                       {'inferenceCredentialKind': 'interactive'},
                       {'inferenceProvider': 'anthropic'}, {'inferenceGatewayApiKey': ''},
                       {'selfHostedUrl': 'https://host.example'},
                       {'inferenceCredentialHelper': '/helper'}):
            self.entry.write_bytes(original)
            self.change_entry(**fields)
            self.assertIsNone(identity.third_party(self.profile))
        self.entry.write_bytes(original)
        self.managed.return_value = True
        self.assertIsNone(identity.third_party(self.profile))
        self.managed.side_effect = OSError('private detail')
        self.assertIsNone(identity.third_party(self.profile))

    def test_missing_invalid_or_redirected_device_id_is_never_initialized(self):
        for data in (b'bad base64!', base64.b64encode(b'not-a-uuid')):
            self.device.write_bytes(data)
            before = fingerprint(self.profile)
            self.assertIsNone(identity.third_party(self.profile))
            self.assertEqual(fingerprint(self.profile), before)
        self.device.unlink()
        self.assertIsNone(identity.third_party(self.profile))
        self.assertFalse(self.device.exists())
        target = self.profile / 'other'
        target.write_bytes(base64.b64encode(ACCOUNT.encode()))
        self.device.symlink_to(target)
        self.assertIsNone(identity.third_party(self.profile))


if __name__ == '__main__':
    unittest.main()
