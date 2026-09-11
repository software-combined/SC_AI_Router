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
from unittest import mock

from ai_router import (capabilities, claude, model_refresh, provider_defs,
                       providers, registry)


def _external_responses():
    """The OpenRouter Codes adapter; Plan 141 makes adapters per-provider."""
    return providers.ExternalResponsesProvider(provider_defs.OPENROUTER)


def _row(slug='z-ai/glm-5.3'):
    return {'slug': slug, 'provider': 'openrouter', 'display_name': 'X',
            'vendor': 'V', 'reasoning': ['low'], 'default_reasoning': 'low',
            'modalities': ['text'], 'excluded_efforts': [], 'schema_mode': 'native',
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
        self.addCleanup(setattr, registry, 'MODELS', self._models)
        self.addCleanup(setattr, registry, 'BY_SLUG', self._by_slug)
        self.addCleanup(setattr, capabilities, 'EXTERNAL_MODELS', self._openrouter)
        self.addCleanup(setattr, capabilities, 'IMAGE_INPUT_MODELS', self._image)
        self.addCleanup(setattr, capabilities, 'EXCLUDED_EFFORTS', self._excluded)
        self.addCleanup(setattr, capabilities, 'REASONING_LEVELS', self._levels)

    def _summarize(self, model, seen):
        from types import SimpleNamespace

        class FakeConn:
            def __init__(self, *a, **k):
                pass
            def request(self, method, path, body=None, headers=None):
                seen.update(json.loads(body))
            def getresponse(self):
                payload = {'output': [{'type': 'message', 'content': [
                    {'type': 'output_text', 'text': 's'}]}]}
                return SimpleNamespace(status=200, read=lambda: json.dumps(payload).encode())
            def close(self):
                pass
        with mock.patch.object(providers.http.client, 'HTTPSConnection', FakeConn):
            return _external_responses().summarize(model, 'key', [])

    def test_valid_payload_swaps_atomically_and_rebuilds_derived(self):
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
            # and drops removed ones, and summarize pins the new levels.
            ids = {row['id'] for row in claude.models_listing()['data']}
            self.assertIn('claude/qwen/qwen-1', ids)
            self.assertNotIn('claude/deepseek/deepseek-v4.1-flash', ids)
            seen = {}
            self.assertEqual(self._summarize('qwen/qwen-1', seen), 's')
            self.assertEqual(seen.get('reasoning'), {'effort': 'low'})
            cache = json.loads((Path(tmp) / 'models-cache.json').read_text())
            self.assertEqual(len(cache), 2)

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


if __name__ == '__main__':
    unittest.main()
