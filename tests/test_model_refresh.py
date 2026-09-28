"""Plan 099 residual: hourly model-data refresh (isolated, no network).

Proves: bundled-first with valid-cache overlay; 304 keeps current; a valid
payload swaps atomically with the cache written and derived maps rebuilt;
malformed/offline payloads keep last-good with a models_refresh_failed log;
over-200 and bad-slug payloads refuse; serial acceptance is untouched.
"""
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path

from ai_router import (capabilities, catalogue, claude, model_refresh, registry)


def _row(slug='z-ai/glm-5.3'):
    return {'slug': slug, 'provider': 'openrouter', 'display_name': 'X',
            'vendor': 'V', 'reasoning': ['low'], 'default_reasoning': 'low',
            'modalities': ['text'], 'excluded_efforts': [], 'schema_mode': 'native', 'history_mode': 'native',
            'max_tools': None, 'drop_images': False, 'context_window': 1,
            'priority': 100, 'max_output_tokens': 100, 'reasoning_summary': 'none',
            'apply_patch': 'none', 'experimental_tools': [], 'web_search': True,
            'tier': 'verified'}


class _Resp:
    def __init__(self, status=200, body=b'', etag=None):
        self.status = status
        self._body = body
        self.headers = {'ETag': etag} if etag else {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, *args):
        return self._body


class ModelRefreshTests(unittest.TestCase):
    def setUp(self):
        self._models = registry.MODELS
        self._by_slug = registry.BY_SLUG
        self._openrouter = capabilities.EXTERNAL_MODELS
        self._image = capabilities.IMAGE_INPUT_MODELS
        self._excluded = capabilities.EXCLUDED_EFFORTS
        self._levels = capabilities.REASONING_LEVELS
        self._catalogue = catalogue.MODELS
        self.addCleanup(setattr, registry, 'MODELS', self._models)
        self.addCleanup(setattr, registry, 'BY_SLUG', self._by_slug)
        self.addCleanup(setattr, catalogue, 'MODELS', self._catalogue)
        self.addCleanup(setattr, capabilities, 'EXTERNAL_MODELS', self._openrouter)
        self.addCleanup(setattr, capabilities, 'IMAGE_INPUT_MODELS', self._image)
        self.addCleanup(setattr, capabilities, 'EXCLUDED_EFFORTS', self._excluded)
        self.addCleanup(setattr, capabilities, 'REASONING_LEVELS', self._levels)

    def test_valid_payload_swaps_atomically_and_rebuilds_derived(self):
        old_alias = claude.claude_alias('deepseek/deepseek-v4.1-flash')
        body = json.dumps([_row(), _row('qwen/qwen-1')]).encode()
        with tempfile.TemporaryDirectory() as tmp:
            models, etag = model_refresh.poll_once('https://m.invalid/models', tmp, None,
                                                   lambda req, timeout=None: _Resp(200, body, 'e9'))
            self.assertEqual(etag, 'e9')
            self.assertIsNotNone(models)
            model_refresh.apply(models)
            self.assertIsNotNone(registry.by_slug('qwen/qwen-1'))
            self.assertIn('qwen/qwen-1', capabilities.REASONING_LEVELS)
            # Dynamic consumers see the swap: the listing gains the new slug
            # and drops removed ones.
            ids = {row['id'] for row in claude.models_listing()['data']}
            self.assertIn(claude.claude_alias('qwen/qwen-1'), ids)
            self.assertNotIn(old_alias, ids)
            cache = json.loads((Path(tmp) / 'models-cache.json').read_text())
            self.assertEqual(len(cache), 2)

    def test_refresh_keeps_the_new_model_snapshot_current(self):
        # Plans 099 and 135: a row that arrives through the refresh must read
        # as pending for the updater's offer, not be seeded away silently by
        # the first query. check_pending seeds on the first call and diffs
        # afterwards, and it never raises into the refresh loop.
        from ai_router import model_prompt
        with tempfile.TemporaryDirectory() as tmp:
            model_refresh.check_pending(tmp)
            self.assertEqual(model_prompt.pending(tmp), [])
            model_refresh.check_pending(tmp + '/missing')  # guarded, no raise
            added = model_refresh.validate(json.dumps([_row(), _row('qwen/qwen-1')]))
            model_refresh.apply(added)
            model_refresh.check_pending(tmp)
            self.assertEqual([slug for slug, _ in model_prompt.pending(tmp)],
                             ['qwen/qwen-1'])

    def test_304_and_offline_keep_current_with_failure_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            before = registry.MODELS
            models, _ = model_refresh.poll_once(
                'https://m.invalid/models', tmp,
                lambda req, timeout=None: (_ for _ in ()).throw(
                    urllib.error.HTTPError(req.full_url, 304, 'Not Modified', {}, None)))
            self.assertIsNone(models)
            self.assertIs(registry.MODELS, before)
            with self.assertLogs('codex_router', level='INFO') as logs:
                models, _ = model_refresh.poll_once(
                    'https://m.invalid/models', tmp,
                    lambda req, timeout=None: (_ for _ in ()).throw(OSError('down')))
            self.assertIsNone(models)
            self.assertTrue(any('models_refresh_failed' in line for line in logs.output))

    def test_malformed_payload_keeps_last_good(self):
        with tempfile.TemporaryDirectory() as tmp:
            before = registry.MODELS
            with self.assertLogs('codex_router', level='INFO') as logs:
                models, _ = model_refresh.poll_once(
                    'https://m.invalid/models', tmp,
                    lambda req, timeout=None: _Resp(200, b'not json'))
            self.assertIsNone(models)
            self.assertIs(registry.MODELS, before)
            self.assertTrue(any('models_refresh_failed' in line for line in logs.output))
            self.assertFalse((Path(tmp) / 'models-cache.json').exists())

    def test_oversize_and_bad_slug_refuse(self):
        with self.assertRaises(SystemExit):
            model_refresh.validate(json.dumps([_row('s/%d' % i) for i in range(201)]))
        bad = _row('no-slash-here!')
        with self.assertRaises(SystemExit):
            model_refresh.validate(json.dumps([bad]))

    def test_valid_cache_overlays_at_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'models-cache.json').write_text(json.dumps([_row('qwen/cached-1')]))
            cached = model_refresh.cached_models(tmp)
            self.assertIsNotNone(cached)
            model_refresh.apply(cached)
            self.assertIsNotNone(registry.by_slug('qwen/cached-1'))
            (Path(tmp) / 'models-cache.json').write_text('garbage')
            self.assertIsNone(model_refresh.cached_models(tmp))

    def test_stale_cache_cannot_resurrect_a_retired_row_or_hide_a_pinned_one(self):
        # A cache written by the release before a pinned-id move still names
        # the superseded id and knows nothing about the new one. Applying it
        # whole put the retired row back in the picker and hid the row the
        # router actually serves, so every Grok request was refused.
        superseded, pinned = 'x-ai/grok-4.6', 'x-ai/grok-4.7'
        self.assertIn(superseded, catalogue.RETIRED_SLUGS)
        self.assertIsNotNone(registry.by_slug(pinned))
        bundled = registry.MODELS
        cached = model_refresh.validate(json.dumps([_row(superseded),
                                                    _row('qwen/cached-1')]))
        merged = model_refresh.overlay(bundled, cached)
        slugs = {row.slug for row in merged}
        self.assertNotIn(superseded, slugs)
        self.assertIn(pinned, slugs)
        self.assertIn('qwen/cached-1', slugs)
        self.assertEqual(len(merged), len(bundled) + 1)

    def test_fetched_roster_goes_through_the_same_overlay(self):
        # The hourly fetch lands through apply_fetched, so a feed that lags
        # the release cannot hide a pinned row or bring a retired one back
        # either; both paths must agree with the bundled roster.
        superseded, pinned = 'x-ai/grok-4.6', 'x-ai/grok-4.7'
        fetched = model_refresh.validate(json.dumps([_row(superseded)]))
        model_refresh.apply_fetched(fetched)
        self.assertIsNone(registry.by_slug(superseded))
        self.assertIsNotNone(registry.by_slug(pinned))
        self.assertIsNotNone(registry.by_slug('z-ai/glm-5.3'))

    def test_older_feed_cannot_shrink_or_widen_bundled_reasoning(self):
        # The beta feed kept publishing ["none"] after the release pinned six
        # levels. A restart then refused xhigh with "use one of none".
        slug = 'xiaomi/mimo-v2.6-pro'
        levels = ('none', 'minimal', 'low', 'medium', 'high', 'xhigh')
        bundled = model_refresh.validate(json.dumps([
            _row(slug) | {'reasoning': list(levels), 'default_reasoning': 'none'}]))
        cached = model_refresh.validate(json.dumps([
            _row(slug) | {'reasoning': ['none', 'ultra'],
                          'default_reasoning': 'none'}]))
        merged = {row.slug: row for row in model_refresh.overlay(bundled, cached)}
        self.assertEqual(merged[slug].reasoning, levels)
        self.assertEqual(merged[slug].default_reasoning, 'none')
        self.assertNotIn('ultra', merged[slug].reasoning)

    def test_older_feed_cannot_drop_the_bundled_compaction_limit(self):
        # A cache written before the 0.6.124 update has no limit for MiMo
        # Pro. Taken as is, it would let threads grow toward 942,000 tokens
        # again until the next hourly fetch. Live data such as the window
        # still comes from the feed.
        slug = 'xiaomi/mimo-v2.6-pro'
        bundled = model_refresh.validate(json.dumps([
            _row(slug) | {'auto_compact_token_limit': 400000}]))
        cached = model_refresh.validate(json.dumps([
            _row(slug) | {'context_window': 2097152}]))
        merged = {row.slug: row for row in model_refresh.overlay(bundled, cached)}
        self.assertEqual(merged[slug].auto_compact_token_limit, 400000)
        self.assertEqual(merged[slug].context_window, 2097152)


if __name__ == '__main__':
    unittest.main()
