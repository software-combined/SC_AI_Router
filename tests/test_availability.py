"""Key-filtered model availability behind `/models/user` (Plan 145).

Proves: the visibility rule (approved roster intersect key snapshot
intersect local policy intersect client rules); snapshot scoping per
key and region; last-good retention on transient failure; clearing on
auth rejection; fail-closed malformed payloads; region profiles in the
definition table; region-aware adapter hosts; catalogue merge and
prompt visibility honoring the snapshot; request selection refusing
unavailable rows.
"""
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from ai_router import (availability, catalogue, claude, model_prompt,
                       provider_defs, providers)
from ai_router.registry import MODELS, external_slugs


class _Resp:
    def __init__(self, status=200, body=b''):
        self.status = status
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, *args):
        return self._body


def _user_doc(*slugs):
    return json.dumps({'data': [{'id': s} for s in slugs]}).encode()


def _ok(*slugs):
    return lambda req, timeout=None: _Resp(200, _user_doc(*slugs))


class AvailabilityUnitTests(unittest.TestCase):
    def setUp(self):
        self._snap = availability._SNAPSHOT
        self.addCleanup(setattr, availability, '_SNAPSHOT', self._snap)

    def test_validate_accepts_id_list(self):
        ids = availability.validate({'data': [{'id': 'a/b'}, {'id': 'c/d'}]})
        self.assertEqual(ids, frozenset({'a/b', 'c/d'}))

    def test_validate_rejects_malformed(self):
        for bad in ({}, {'data': {}}, {'data': [{'id': 3}]},
                    {'data': [{'name': 'a/b'}]}, [], 'x'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                availability.validate(bad)

    def test_refresh_scopes_snapshot_to_key_and_region(self):
        with tempfile.TemporaryDirectory() as tmp:
            snap = availability.refresh('openrouter.ai', 'key-one', tmp,
                                        'global', _ok('a/b'))
            self.assertEqual(snap['key'], availability.key_fingerprint('key-one'))
            self.assertEqual(snap['region'], 'global')
            self.assertEqual(snap['models'], frozenset({'a/b'}))
            doc = json.loads((Path(tmp) / 'models-availability.json').read_text())
            self.assertEqual(doc['region'], 'global')
            self.assertEqual(doc['models'], ['a/b'])

    def test_transient_failure_keeps_last_good(self):
        def down(req, timeout=None):
            raise OSError('down')
        with tempfile.TemporaryDirectory() as tmp:
            availability.refresh('openrouter.ai', 'k', tmp, 'global', _ok('a/b'))
            kept = availability.refresh('openrouter.ai', 'k', tmp, 'global', down)
            self.assertEqual(kept['models'], frozenset({'a/b'}))

    def test_auth_rejection_clears_snapshot(self):
        def denied(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 401, 'no', {}, None)
        with tempfile.TemporaryDirectory() as tmp:
            availability.refresh('openrouter.ai', 'k', tmp, 'global', _ok('a/b'))
            self.assertIsNone(availability.refresh(
                'openrouter.ai', 'k', tmp, 'global', denied))
            self.assertIsNone(availability.current())
            self.assertFalse((Path(tmp) / 'models-availability.json').exists())

    def test_malformed_payload_keeps_last_good(self):
        with tempfile.TemporaryDirectory() as tmp:
            availability.refresh('openrouter.ai', 'k', tmp, 'global', _ok('a/b'))
            kept = availability.refresh(
                'openrouter.ai', 'k', tmp, 'global',
                lambda req, timeout=None: _Resp(200, b'not json'))
            self.assertEqual(kept['models'], frozenset({'a/b'}))

    def test_transient_failure_after_rotation_drops_old_snapshot(self):
        def down(req, timeout=None):
            raise OSError('down')
        with tempfile.TemporaryDirectory() as tmp:
            availability.refresh('openrouter.ai', 'old-key', tmp, 'global',
                                 _ok('a/b'))
            kept = availability.refresh('openrouter.ai', 'new-key', tmp,
                                        'global', down)
            self.assertIsNone(kept)
            self.assertIsNone(availability.current())

    def test_transient_failure_same_key_keeps_snapshot(self):
        def down(req, timeout=None):
            raise OSError('down')
        with tempfile.TemporaryDirectory() as tmp:
            availability.refresh('openrouter.ai', 'k', tmp, 'global', _ok('a/b'))
            kept = availability.refresh('openrouter.ai', 'k', tmp, 'global', down)
            self.assertEqual(kept['models'], frozenset({'a/b'}))

    def test_claude_listing_hides_rows_outside_the_snapshot(self):
        from ai_router import claude as _claude
        availability._SNAPSHOT = {'key': 'k', 'region': 'global',
                                  'models': frozenset({'z-ai/glm-5.3'}),
                                  'fetched_at': 0}
        ids = {row['id'] for row in _claude.models_listing()['data']}
        self.assertIn(_claude.claude_alias('z-ai/glm-5.3'), ids)
        self.assertNotIn(_claude.claude_alias('moonshotai/kimi-k3'), ids)

    def test_claude_listing_without_snapshot_lists_all(self):
        from ai_router import claude as _claude
        availability._SNAPSHOT = None
        full = {row['id'] for row in _claude.models_listing()['data']}
        self.assertIn(_claude.claude_alias('moonshotai/kimi-k3'), full)

    def test_restore_serves_same_key_and_region_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            availability.refresh('openrouter.ai', 'k', tmp, 'us', _ok('a/b'))
            availability._SNAPSHOT = None
            self.assertIsNotNone(availability.restore(tmp, 'k', 'us'))
            availability._SNAPSHOT = None
            self.assertIsNone(availability.restore(tmp, 'other-key', 'us'))
            availability._SNAPSHOT = None
            self.assertIsNone(availability.restore(tmp, 'k', 'eu'))

class RegionProfileTests(unittest.TestCase):
    def test_known_regions_resolve(self):
        self.assertEqual(provider_defs.region_host('openrouter', 'global'),
                         'openrouter.ai')
        self.assertEqual(provider_defs.region_host('openrouter', 'us'),
                         'us.openrouter.ai')
        self.assertEqual(provider_defs.region_host('openrouter', 'eu'),
                         'eu.openrouter.ai')

    def test_unknown_region_or_provider_fails_closed(self):
        self.assertIsNone(provider_defs.region_host('openrouter', 'xx'))
        self.assertIsNone(provider_defs.region_host('nope', 'us'))
        self.assertFalse(provider_defs.valid_region('xx'))
        self.assertTrue(provider_defs.valid_region('global'))

    def test_adapter_hosts_follow_region(self):
        self.assertEqual(
            providers.ExternalResponsesProvider(provider_defs.OPENROUTER).host,
            'openrouter.ai')
        self.assertEqual(
            providers.ExternalResponsesProvider(provider_defs.OPENROUTER, 'us').host,
            'us.openrouter.ai')
        self.assertEqual(
            providers.ExternalResponsesProvider(provider_defs.OPENROUTER, 'xx').host,
            'openrouter.ai')
        self.assertEqual(
            claude.ExternalMessagesProvider(provider_defs.OPENROUTER, 'eu').host,
            'eu.openrouter.ai')


class VisibilityIntegrationTests(unittest.TestCase):
    def setUp(self):
        self._snap = availability._SNAPSHOT
        self.addCleanup(setattr, availability, '_SNAPSHOT', self._snap)
        availability._SNAPSHOT = None

    def test_catalogue_merge_hides_rows_outside_the_snapshot(self):
        roster = [m.slug for m in MODELS if provider_defs.is_external(m.provider)]
        full = catalogue.merge({'models': []}, roster)
        shown = {m['slug'] for m in full['models']}
        target = 'deepseek/deepseek-v4-pro-0813'
        self.assertIn(target, shown)
        limited = catalogue.merge({'models': []}, roster,
                                  available=frozenset(s for s in roster if s != target))
        self.assertNotIn(target, {m['slug'] for m in limited['models']})

    def test_merge_without_snapshot_preserves_today(self):
        roster = [m.slug for m in MODELS if provider_defs.is_external(m.provider)]
        merged = catalogue.merge({'models': []}, roster)
        self.assertEqual({m['slug'] for m in merged['models']},
                         {m['slug'] for m in catalogue.merge({'models': []}, roster,
                                                             available=None)['models']})

    def test_prompt_visibility_matches_catalogue_merge(self):
        roster = [m.slug for m in MODELS if provider_defs.is_external(m.provider)]
        subset = frozenset(roster[:4])
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(availability, 'current_key',
                                   return_value='k'), mock.patch.object(
                    availability, 'current_region', return_value='global'):
                availability.refresh('openrouter.ai', 'k', tmp, 'global',
                                     _ok(*subset))
                rows = model_prompt.visible_models(tmp)
        merged = catalogue.merge({'models': []}, available=subset)
        self.assertEqual({slug for slug, _ in rows},
                         {m['slug'] for m in merged['models']})

    def test_refresh_rewrites_picker_file_without_blocked_rows(self):
        # The reported defect: routing refused a dashboard-blocked row
        # while the picker file still listed it, because only setup merged
        # the key filter. Refresh must re-merge the file every snapshot.
        target = 'qwen/qwen3.8-max-0902'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'mixed-models.json'
            catalogue.merge_file(path, available=None)
            before = {m['slug'] for m in json.loads(
                path.read_text())['models']}
            self.assertIn(target, before)
            kept = external_slugs() - {target}
            availability.refresh('openrouter.ai', 'k', tmp, 'global',
                                 _ok(*kept))
            after = {m['slug'] for m in json.loads(path.read_text())['models']}
            self.assertNotIn(target, after)
            self.assertTrue(kept <= after)

    def test_auth_rejection_hides_external_rows_from_picker_file(self):
        def denied(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 401, 'denied', {}, None)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'mixed-models.json'
            catalogue.merge_file(path, available=None)
            self.assertIsNone(availability.refresh(
                'openrouter.ai', 'k', tmp, 'global', denied))
            slugs = {m['slug'] for m in json.loads(path.read_text())['models']}
            self.assertFalse(external_slugs() & slugs)

    def test_rotation_transient_hides_picker_rows(self):
        # A rotated key plus a transient failure clears the snapshot; the
        # picker file must follow, not keep the previous key's rows.
        roster = external_slugs()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'mixed-models.json'
            catalogue.merge_file(path, available=None)
            availability.refresh('openrouter.ai', 'old-key', tmp, 'global',
                                 _ok(*roster))
            down = lambda req, timeout=None: (_ for _ in ()).throw(
                OSError('transient'))
            availability.refresh('openrouter.ai', 'new-key', tmp, 'global',
                                 down)
            slugs = {m['slug'] for m in json.loads(path.read_text())['models']}
            self.assertFalse(external_slugs() & slugs)

    def test_refresh_keeps_portco_allowlist(self):
        # The runtime re-merge must not re-reveal rows the portco policy
        # hides: both filters apply at once.
        import json as _json
        roster = external_slugs()
        gated = sorted(roster)[:3]
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'model-policy.json').write_text(_json.dumps(
                {'portco': 'acme', 'allowed_models': gated}))
            os.chmod(Path(tmp) / 'model-policy.json', 0o600)
            path = Path(tmp) / 'mixed-models.json'
            catalogue.merge_file(path, available=None)
            availability.refresh('openrouter.ai', 'k', tmp, 'global',
                                 _ok(*roster))
            slugs = {m['slug'] for m in json.loads(path.read_text())['models']}
            self.assertTrue(set(gated) <= slugs)
            self.assertFalse((external_slugs() - set(gated)) & slugs)

    def test_request_selection_refuses_unavailable_row(self):
        from ai_router.errors import UnknownModel
        target = 'moonshotai/kimi-k3'
        availability._SNAPSHOT = {'key': 'k', 'region': 'global',
                                  'models': frozenset({'z-ai/glm-5.3'}),
                                  'fetched_at': 0}
        with self.assertRaises(UnknownModel):
            providers.select(target, '/responses')
        with self.assertRaises(UnknownModel):
            claude.select('claude/' + target, '/v1/messages')

    def test_request_selection_passes_before_first_snapshot(self):
        availability._SNAPSHOT = None
        provider = providers.select('moonshotai/kimi-k3', '/responses')
        self.assertEqual(provider.name, 'openrouter')
        self.assertEqual(provider.host, 'openrouter.ai')

    def test_request_selection_uses_region_host(self):
        provider = providers.select('moonshotai/kimi-k3', '/responses',
                                    region='us')
        self.assertEqual(provider.host, 'us.openrouter.ai')


if __name__ == '__main__':
    unittest.main()
