"""Cache metadata proves one exact channel/source/version and cannot erase failures."""
import unittest

from tests.test_native_setup import module

status = module('update_status')
FEED = 'https://dist.softwarecombined.com/beta/latest.json'
NOW = '2026-10-18T13:05:00Z'


class UpdateStatusTests(unittest.TestCase):
    def test_cached_identity_is_bound_to_verified_version_channel_and_source(self):
        state = {}
        status.verified(state, {'version': '1.3.2.185'}, FEED, 'beta', 'etag', NOW)
        self.assertEqual(status.cache_tag(state, '1.3.2.185', FEED, 'beta', 'etag'), 'etag')
        for current, feed, channel, tag in (('1.2.6.174', FEED, 'beta', 'etag'),
                ('1.3.2.185', FEED, 'stable', 'etag'), ('1.3.2.185', FEED + '?other', 'beta', 'etag'),
                ('1.3.2.185', FEED, 'beta', 'different')):
            self.assertIsNone(status.cache_tag(state, current, feed, channel, tag))

    def test_failure_and_component_warnings_are_not_cached_away(self):
        for extra in ({'last_error': 'installer_failed'}, {'update_failures': {'1.3.2.185': 3}},
                      {'component_repairs': {'controls': 'failed'}}):
            with self.subTest(extra=extra):
                state = dict(extra)
                status.verified(state, {'version': '1.3.2.185'}, FEED, 'beta', 'etag', NOW)
                self.assertIsNone(status.cache_tag(state, '1.3.2.185', FEED, 'beta', 'etag'))

    def test_feed_success_and_completed_repair_clear_only_their_own_failure(self):
        state = dict(component_repairs={'controls': 'failed'})
        status.record(state, 'installer_failed', now=NOW)
        status.record(state, '', now=NOW)
        self.assertEqual(state['last_error'], 'installer_failed')
        status.record(state, '', applied='1.3.2.185', repaired=True, now=NOW)
        self.assertNotIn('last_error', state)
        self.assertEqual(state['component_repairs'], {'controls': 'failed'})

    def test_summary_redacts_poisoned_values_and_ignores_other_channel_history(self):
        state = dict(last_check_at='/private', last_error='/private',
            component_repairs={'private': 'failed', 'controls': '/private'},
            update_failures={'/private': 3})
        status.verified(state, {'version': '1.3.2.185'}, FEED, 'beta', 'etag', NOW)
        doc = status.summary(state, '1.2.6.174', FEED, 'stable')
        self.assertIsNone(doc['latest_known_version'])
        self.assertIsNone(doc['last_successful_check_at'])
        self.assertNotIn('/private', str(doc))

    def test_a_verified_newer_release_supersedes_an_older_parked_release(self):
        state = dict(update_failures={'1.3.1.184': 3})
        status.verified(state, {'version': '1.3.2.185'}, FEED, 'beta', 'etag', NOW)
        self.assertEqual(status.cache_tag(state, '1.3.2.185', FEED, 'beta', 'etag'), 'etag')
        self.assertIsNone(status.summary(state, '1.3.2.185', FEED, 'beta')['required_action'])
        self.assertEqual(state['update_failures'], {'1.3.1.184': 3})

    def test_parked_counts_from_another_channel_do_not_park_this_channel(self):
        state = dict(update_failures={'1.3.2.185': 3}, update_failure_context={
            '1.3.2.185': dict(channel='beta', source=status.source(FEED))})
        self.assertEqual(status.failures(state, FEED, 'beta'), {'1.3.2.185': 3})
        self.assertEqual(status.failures(state, FEED, 'stable'), {})
        self.assertEqual(status.failures(state, FEED + '?other', 'beta'), {})
        self.assertEqual(state['update_failures']['1.3.2.185'], 3)

    def test_an_intervening_feed_failure_cannot_erase_pending_install_repair(self):
        state = {}
        status.verified(state, {'version': '1.3.2.185'}, FEED, 'beta', 'etag', NOW)
        status.record(state, 'installer_failed', applied='1.3.2.185', now=NOW)
        status.record(state, 'feed_unreachable', now=NOW)
        status.record(state, '', now=NOW)
        self.assertEqual(status.summary(state, '1.3.2.185', FEED, 'beta')['required_action'], 'repair')
        self.assertIsNone(status.cache_tag(state, '1.3.2.185', FEED, 'beta', 'etag'))
        status.record(state, '', applied='1.3.2.185', repaired=True, now=NOW)
        self.assertIsNone(status.summary(state, '1.3.2.185', FEED, 'beta')['required_action'])
        self.assertEqual(status.cache_tag(state, '1.3.2.185', FEED, 'beta', 'etag'), 'etag')

    def test_known_newer_metadata_still_offers_update_after_a_pointer_rollback(self):
        state = {}
        status.verified(state, {'version': '1.3.2.185'}, FEED, 'beta', 'etag', NOW)
        self.assertEqual(status.summary(state, '1.2.6.174', FEED, 'beta')['required_action'], 'update')
        self.assertIsNone(status.cache_tag(state, '1.2.6.174', FEED, 'beta', 'etag'))
