"""Pinned summary rows fail closed before any secondary-vendor request."""
from types import SimpleNamespace
import unittest
from unittest import mock

from ai_router import availability, compaction_summary, providers


def _snapshot(key='key', region='global'):
    return {'key': availability.key_fingerprint(key), 'region': region,
            'models': frozenset(compaction_summary.SUMMARY_MODEL_SLUGS)}


class MissingSummaryRowTests(unittest.TestCase):
    def test_missing_primary_row_fails_closed_before_http(self):
        rows = {
            slug: SimpleNamespace(
                slug=slug, provider='openrouter', upstream_id=slug,
                provider_prefs=None, max_output_tokens=100000,
                reasoning=('low', 'high', 'max'))
            for slug in compaction_summary.SUMMARY_MODEL_SLUGS[1:]
        }
        with mock.patch.object(availability, 'current',
                               return_value=_snapshot()), \
                mock.patch.object(providers, 'by_slug', side_effect=rows.get), \
                mock.patch.object(compaction_summary.http.client,
                                  'HTTPSConnection') as conn:
            with self.assertRaisesRegex(ValueError, 'registry row missing'):
                providers.ExternalResponsesProvider(
                    providers.provider_defs.OPENROUTER).summarize(
                        'z-ai/glm-5.3', 'key',
                        [{'type': 'message', 'role': 'user', 'content': 'marker'}])
        conn.assert_not_called()

    def test_missing_availability_snapshot_fails_closed_before_http(self):
        with mock.patch.object(availability, 'current', return_value=None), \
                mock.patch.object(compaction_summary.http.client,
                                  'HTTPSConnection') as conn:
            with self.assertRaisesRegex(ValueError, 'models unavailable'):
                providers.ExternalResponsesProvider(
                    providers.provider_defs.OPENROUTER).summarize(
                        'z-ai/glm-5.3', 'key', [],
                        allowed=compaction_summary.SUMMARY_MODEL_SLUGS)
        conn.assert_not_called()

    def test_stale_key_or_region_fails_closed_before_http(self):
        for snapshot in (dict(_snapshot(), key='stale'),
                         dict(_snapshot(), region='eu')):
            with self.subTest(snapshot=snapshot), \
                    mock.patch.object(availability, 'current',
                                      return_value=snapshot), \
                    mock.patch.object(compaction_summary.http.client,
                                      'HTTPSConnection') as conn:
                with self.assertRaisesRegex(ValueError, 'models unavailable'):
                    providers.ExternalResponsesProvider(
                        providers.provider_defs.OPENROUTER).summarize(
                            'z-ai/glm-5.3', 'key', [])
                conn.assert_not_called()

    def test_jev_and_summary_never_run_without_snapshot(self):
        provider = providers.ExternalResponsesProvider(
            providers.provider_defs.OPENROUTER)
        payload = {'input': [{'type': 'message', 'role': 'user',
                              'content': 'marker'}]}
        for method in (provider.compact, provider.compact_trigger):
            with self.subTest(method=method.__name__), \
                    mock.patch.object(availability, 'current', return_value=None), \
                    mock.patch.object(providers.jev_compaction, 'state',
                                      return_value='on'), \
                    mock.patch.object(providers.jev_compaction, 'summary') as jev, \
                    mock.patch.object(providers.jev_compaction.decisions, 'ask') as ask, \
                    mock.patch.object(compaction_summary.http.client,
                                      'HTTPSConnection') as conn:
                with self.assertRaises(providers.PreparationError):
                    method('z-ai/glm-5.3', payload, 'key')
                jev.assert_not_called()
                ask.assert_not_called()
                conn.assert_not_called()

    def test_policy_without_summary_rows_fails_closed_before_jev(self):
        provider = providers.ExternalResponsesProvider(
            providers.provider_defs.OPENROUTER)
        payload = {'input': [{'type': 'message', 'role': 'user',
                              'content': 'marker'}]}
        states = (
            ('empty snapshot', dict(_snapshot(), models=frozenset()), None),
            ('allowlist excludes summary rows', _snapshot(),
             {'z-ai/glm-5.3'}),
        )
        for label, snapshot, allowed in states:
            for method in (provider.compact, provider.compact_trigger):
                with self.subTest(state=label, method=method.__name__), \
                        mock.patch.object(availability, 'current',
                                          return_value=snapshot), \
                        mock.patch.object(providers.jev_compaction, 'state',
                                          return_value='on'), \
                        mock.patch.object(providers.jev_compaction,
                                          'summary') as jev, \
                        mock.patch.object(providers.jev_compaction.decisions,
                                          'ask') as ask, \
                        mock.patch.object(compaction_summary.http.client,
                                          'HTTPSConnection') as conn:
                    with self.assertRaisesRegex(providers.PreparationError,
                                                'models unavailable'):
                        method('z-ai/glm-5.3', payload, 'key',
                               allowed=allowed)
                    jev.assert_not_called()
                    ask.assert_not_called()
                    conn.assert_not_called()

    def test_non_global_jev_is_skipped_for_regional_summary(self):
        provider = providers.ExternalResponsesProvider(
            providers.provider_defs.OPENROUTER, region='eu')
        payload = {'input': [{'type': 'message', 'role': 'user',
                              'content': 'marker'}]}
        with mock.patch.object(availability, 'current',
                               return_value=_snapshot(region='eu')), \
                mock.patch.object(providers.jev_compaction, 'state',
                                  return_value='on'), \
                mock.patch.object(providers.jev_compaction, 'summary') as jev, \
                mock.patch.object(providers.jev_compaction.decisions, 'ask') as ask, \
                mock.patch.object(provider, 'summarize',
                                  return_value='regional summary') as summarize:
            output = provider.compact('z-ai/glm-5.3', payload, 'key')
        jev.assert_not_called()
        ask.assert_not_called()
        summarize.assert_called_once()
        self.assertEqual(provider.host, 'eu.openrouter.ai')
        self.assertIn('regional summary', str(output))

    def test_summary_rows_use_one_catalogue_and_policy_snapshot(self):
        rows = {slug: SimpleNamespace(
            slug=slug, provider='openrouter', upstream_id=slug,
            provider_prefs=None, max_output_tokens=100000,
            reasoning=('low', 'high', 'max'))
            for slug in compaction_summary.SUMMARY_MODEL_SLUGS}
        lookup = mock.Mock(side_effect=AssertionError('live lookup'))
        entries = compaction_summary.summary_entries(
            providers.provider_defs.OPENROUTER.id, catalogue=rows,
            allowed={'deepseek/deepseek-v4.1-flash'},
            availability_snapshot={'models': {'deepseek/deepseek-v4.1-flash'}},
            lookup=lookup)
        self.assertEqual([entry.slug for entry in entries],
                         ['deepseek/deepseek-v4.1-flash'])
        lookup.assert_not_called()


if __name__ == '__main__':
    unittest.main()
