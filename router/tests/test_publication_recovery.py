"""Public setup ships without native acceptance and follows the stable installer."""
import unittest

from tests import test_publish_feed as fixtures


class PublicSetupPublicationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PublishFeedTests()
        self.addCleanup(self.fixture.doCleanups)

    def test_public_repair_page_does_not_need_native_acceptance_or_artifacts(self):
        dist, runner = self.fixture._dist(channel='stable'), fixtures._Aws()
        self.assertEqual(self.fixture._run(dist, runner, channel='stable')[0], 0)
        uploads = [call[4] for call in runner.calls if call[1:3] == ['s3', 'cp']]
        for name in ('index.html', 'downloads.js', 'bootstrap.sh', 'bootstrap.ps1'):
            key = 's3://feed-bucket/install/' + name
            self.assertIn(key, uploads)
            self.assertGreater(uploads.index(key), uploads.index('s3://feed-bucket/stable/latest.json.sig'))
        self.assertNotIn('s3://feed-bucket/install/stable.json', uploads)

    def test_beta_release_cannot_replace_shared_setup_before_stable_supports_its_flags(self):
        runner = fixtures._Aws()
        self.assertEqual(self.fixture._run(self.fixture._dist(), runner)[0], 0)
        uploads = [call[4] for call in runner.calls if call[1:3] == ['s3', 'cp']]
        self.assertFalse(any('/install/' in key for key in uploads))
