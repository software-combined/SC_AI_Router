import json
import unittest
from types import SimpleNamespace
from unittest import mock
from ai_router import availability, compaction_summary, provider_defs, providers, registry, tool_runs, wire_shape
from ai_router.image_items import IMAGE_NOTE
from tests.harness import (
    isolated_home as _isolated_home,
    stub_credentials as _stub_credentials,
)


def _external_responses():
    """The OpenRouter Codes adapter; Plan 141 makes adapters per-provider."""
    return providers.ExternalResponsesProvider(provider_defs.OPENROUTER)


def _summary_snapshot():
    return {'key': availability.key_fingerprint('key'), 'region': 'global',
            'models': frozenset(compaction_summary.SUMMARY_MODEL_SLUGS)}


class SelectTests(unittest.TestCase):
    def test_select_prefers_native_paths_regardless_of_model(self):
        provider = providers.select('z-ai/glm-5.3', '/alpha/search', [])
        self.assertIsInstance(provider, providers.SubscriptionProvider); self.assertEqual(providers.select('gpt-5.6-luna', '/responses', []).name, 'openai')

    def test_none_mode_names_subscription_for_openai_models(self):
        with self.assertRaisesRegex(ValueError, 'without a ChatGPT subscription'):
            providers.select('gpt-6-astra', '/responses', ['gpt-6-astra'], 'none')

    def test_select_rejects_unknown_model(self):
        with self.assertRaisesRegex(ValueError, 'not in the configured catalog'):
            providers.select('unknown/model', '/responses', ['gpt-6-astra'])

    def test_select_unknown_carries_id_and_no_alias_candidate(self):
        # The retired Claude aliases are gone from the registry, so there is
        # no tilde candidate to offer; the requested id still travels.
        from ai_router.errors import UnknownModel
        with self.assertRaises(UnknownModel) as caught:
            providers.select('anthropic/claude-opus-latest', '/responses',
                             ['gpt-6-astra'])
        self.assertEqual(caught.exception.model,
                         'anthropic/claude-opus-latest')
        self.assertEqual(caught.exception.candidates, ())
        with self.assertRaises(UnknownModel) as caught:
            providers.select('unknown/model', '/responses', ['gpt-6-astra'])
        self.assertEqual(caught.exception.candidates, ())

    def test_openrouter_prepare_emits_router_key_only(self):
        # Picker visibility never gates routing: hidden GPT slugs still route.
        hidden = providers.select('openai/gpt-6-astra', '/responses', [])
        self.assertIsInstance(hidden, providers.ExternalResponsesProvider)
        provider = providers.select('z-ai/glm-5.3', '/responses', [])
        prepared = provider.prepare('z-ai/glm-5.3', '/responses',
            {'model': 'z-ai/glm-5.3', 'input': []}, b'raw',
            {'Authorization': 'Bearer subscription-secret', 'Cookie': 'c=1',
             'ChatGPT-Account-ID': 'acct'}, _stub_credentials())
        self.assertEqual(prepared.headers,
                         {'Authorization': 'Bearer router-secret',
                          'Content-Type': 'application/json', 'Accept-Encoding': 'identity',
                          'X-OpenRouter-Metadata': 'enabled'})

    def test_subscription_prepare_forwards_bearer_and_strips_hop_headers(self):
        provider = providers.select('gpt-6-astra', '/responses', ['gpt-6-astra'])
        prepared = provider.prepare('gpt-6-astra', '/responses', {'model': 'x'}, b'raw',
            {'Authorization': 'Bearer subscription-secret', 'ChatGPT-Account-ID': 'acct',
             'Connection': 'keep-alive', 'Host': 'h', 'Content-Length': '3',
             'Cookie': 'c=1'}, None)
        self.assertEqual(prepared.headers,
                         {'Authorization': 'Bearer subscription-secret',
                          'ChatGPT-Account-ID': 'acct'})

    def test_subscription_prepare_forwards_headers_unchanged(self):
        # No Bearer header (Codex >=0.153.4 path-token auth) must forward, not 401.
        provider = providers.select('gpt-6-astra', '/responses', ['gpt-6-astra'])
        prepared = provider.prepare('gpt-6-astra', '/responses', {'model': 'x'}, b'raw',
            {'ChatGPT-Account-ID': 'acct', 'Host': 'h'}, None)
        self.assertEqual(prepared.host, 'chatgpt.com')
        self.assertNotIn('Authorization', prepared.headers)

class DefinitionHeaderTests(unittest.TestCase):
    def test_openrouter_turn_carries_the_metadata_header(self):
        provider = providers.select('z-ai/glm-5.3', '/responses', [])
        prepared = provider.prepare('z-ai/glm-5.3', '/responses',
            {'model': 'z-ai/glm-5.3', 'input': []}, b'raw', {}, _stub_credentials())
        self.assertEqual(prepared.headers.get('X-OpenRouter-Metadata'), 'enabled')

    def test_definition_headers_cannot_override_credentials(self):
        defn = provider_defs.ProviderDef(
            id='x', label='X', kind='external', host='example.invalid',
            responses_path='/r', dialect=provider_defs.DIALECT_OPENAI_COMPATIBLE,
            key=provider_defs.KeySpec('X_KEY', 'x.key'),
            request_headers=(('Authorization', 'Bearer spoof'),
                             ('Content-Type', 'text/plain'),
                             ('X-Custom', 'yes')))
        provider = providers.ExternalResponsesProvider(defn)
        with mock.patch.object(providers, 'by_slug',
                               return_value=SimpleNamespace(
                                   max_output_tokens=1000, context_window=0,
                                   provider_prefs=None, drop_images=False)):
            prepared = provider.prepare(
                SimpleNamespace(slug='x/m', provider='x', max_output_tokens=1000,
                                context_window=0, provider_prefs=None, drop_images=False),
                '/responses', {'model': 'x/m', 'input': []}, b'raw', {},
                _stub_credentials())
        self.assertEqual(prepared.headers['Authorization'], 'Bearer router-secret')
        self.assertEqual(prepared.headers['Content-Type'], 'application/json')
        self.assertEqual(prepared.headers['X-Custom'], 'yes')

    def test_summarizer_carries_the_metadata_header(self):
        seen = {}

        class FakeConn:
            def __init__(self, *a, **k):
                pass
            def connect(self):
                pass
            def request(self, method, path, body=None, headers=None):
                seen.update(headers)
                seen['body'] = json.loads(body)
            def getresponse(self):
                payload = {'model': seen['body'].get('model'),
                           'output': [{'type': 'message', 'content': [
                    {'type': 'output_text', 'text': 's'}]}]}
                return SimpleNamespace(status=200,
                                        read=lambda: json.dumps(payload).encode())
            def close(self):
                pass
        with mock.patch.object(compaction_summary.availability, 'current',
                               return_value=_summary_snapshot()), \
                mock.patch.object(compaction_summary.http.client,
                                  'HTTPSConnection', FakeConn):
            _external_responses().summarize('z-ai/glm-5.3', 'key', [])
        self.assertEqual(seen.get('X-OpenRouter-Metadata'), 'enabled')
        self.assertEqual(seen.get('Authorization'), 'Bearer key')
        self.assertNotIn('x-api-key', {key.lower() for key in seen})
        self.assertNotIn('chatgpt-account-id', {key.lower() for key in seen})
        self.assertNotIn('provider', seen['body'])


class ProviderPrefsTests(unittest.TestCase):
    def _entry(self, prefs, slug='xiaomi/mimo-v2.6-flash'):
        return SimpleNamespace(slug=slug, provider='openrouter',
                               max_output_tokens=1000, context_window=0,
                               provider_prefs=prefs, drop_images=False,
                               reasoning=('none', 'low'), upstream_id=slug)

    def test_wire_body_has_no_provider_without_prefs(self):
        prepared = _external_responses().prepare(
            self._entry(None), '/responses', {'model': 'x/m', 'input': []},
            b'raw', {}, _stub_credentials())
        self.assertNotIn('provider', json.loads(prepared.body))

    def test_wire_body_carries_provider_exactly_when_set(self):
        prefs = {'ignore': ['DeepSeek'], 'allow_fallbacks': True}
        prepared = _external_responses().prepare(
            self._entry(prefs), '/responses', {'model': 'x/m', 'input': []},
            b'raw', {}, _stub_credentials())
        self.assertEqual(json.loads(prepared.body)['provider'], prefs)

    def test_summarizer_rejects_provider_routing_overrides(self):
        seen = {}

        class FakeConn:
            def __init__(self, *a, **k):
                pass
            def connect(self):
                pass
            def request(self, method, path, body=None, headers=None):
                seen.update(json.loads(body))
            def getresponse(self):
                payload = {'output': [{'type': 'message', 'content': [
                    {'type': 'output_text', 'text': 's'}]}]}
                return SimpleNamespace(status=200,
                                        read=lambda: json.dumps(payload).encode())
            def close(self):
                pass
        prefs = {'require_parameters': True}
        rows = {slug: self._entry(prefs, slug)
                for slug in compaction_summary.SUMMARY_MODEL_SLUGS}
        with mock.patch.object(compaction_summary.availability, 'current',
                               return_value=_summary_snapshot()), \
                mock.patch.object(compaction_summary.http.client,
                                  'HTTPSConnection', FakeConn), \
                mock.patch.object(providers, 'by_slug',
                                   side_effect=lambda slug: rows.get(slug)):
            with self.assertRaisesRegex(ValueError, 'failed pin'):
                _external_responses().summarize('x/m', 'key', [])
        self.assertNotIn('model', seen)


class OutputCapTests(unittest.TestCase):
    def test_output_cap_follows_registry(self):
        provider = _external_responses()
        fake = SimpleNamespace(max_output_tokens=1000, context_window=100000, slug='fake/model')
        payload = {'model': 'fake/model', 'input': [], 'max_output_tokens': 5000}
        prepared = provider.prepare(fake, '/responses', payload, b'raw', {}, _stub_credentials())
        sent = json.loads(prepared.body)['max_output_tokens']
        self.assertEqual(sent, 1000)
        self.assertEqual(prepared.output_cap, sent)
        payload = {'model': 'fake/model', 'input': []}
        prepared = provider.prepare(fake, '/responses', payload, b'raw', {}, _stub_credentials())
        sent = json.loads(prepared.body)['max_output_tokens']
        self.assertEqual(sent, 1000)
        self.assertEqual(prepared.output_cap, sent)

    def test_output_cap_leaves_room_for_input(self):
        # Regression: a 943718 reservation on a 1048576 window leaves ~105k
        # for input, so a ~105k-input request blows the context. The router
        # must reserve at most half the window for output.
        from ai_router.registry import by_slug
        provider = _external_responses()
        entry = by_slug('meta/muse-spark-1.3-contributor')
        payload = {'model': 'meta/muse-spark-1.3-contributor', 'input': []}
        prepared = provider.prepare(entry, '/responses', payload, b'raw', {},
                                    _stub_credentials())
        sent = json.loads(prepared.body)['max_output_tokens']
        self.assertLessEqual(sent, entry.context_window // 2)

    def test_unknown_model_is_rejected(self):
        provider = _external_responses()
        with self.assertRaises(providers.PreparationError):
            provider.prepare('unknown/model', '/responses',
                             {'model': 'unknown/model', 'input': []},
                             b'raw', {}, _stub_credentials())

    def test_request_within_context_window_still_passes(self):
        from ai_router.registry import by_slug
        provider = _external_responses()
        entry = by_slug('meta/muse-spark-1.3-contributor')
        payload = {'model': 'meta/muse-spark-1.3-contributor',
                   'input': [{'type': 'message', 'role': 'user',
                              'content': 'y' * 400000}],
                   'max_output_tokens': 524288}
        prepared = provider.prepare(entry, '/responses', payload, b'raw', {},
                                    _stub_credentials())
        self.assertEqual(json.loads(prepared.body)['max_output_tokens'], 524288)

    def test_unknown_window_keeps_default_output(self):
        # Registry default context_window=0: the default output still clamps
        # to the provider ceiling, and the endpoint enforces context.
        provider = _external_responses()
        fake = SimpleNamespace(max_output_tokens=1000, context_window=0,
                               slug='fake/model')
        payload = {'model': 'fake/model',
                   'input': [{'type': 'message', 'role': 'user',
                              'content': 'z' * 2000000}]}
        prepared = provider.prepare(fake, '/responses', payload, b'raw', {},
                                    _stub_credentials())
        self.assertEqual(json.loads(prepared.body)['max_output_tokens'], 1000)

    def test_non_list_input_never_escapes_as_500(self):
        # Wire input of any JSON shape is measured, never a TypeError leak.
        from ai_router.registry import by_slug
        provider = _external_responses()
        entry = by_slug('meta/muse-spark-1.3-contributor')
        for shape in ('do the task', {'text': 'do the task'}, None):
            payload = {'model': entry.slug, 'input': shape}
            try:
                provider.prepare(entry, '/responses', dict(payload), b'raw', {},
                                 _stub_credentials())
            except providers.PreparationError as exc:
                self.assertNotIn('Bearer', str(exc))
                self.assertNotIn('router-secret', str(exc))


class SummarizerTests(unittest.TestCase):
    def _summarize(self, model, seen):
        class FakeConn:
            def __init__(self, *a, **k):
                pass
            def connect(self):
                pass
            def request(self, method, path, body=None, headers=None):
                seen.update(json.loads(body))
            def getresponse(self):
                payload = {'model': seen.get('model'), 'output': [{'type': 'message', 'content': [
                    {'type': 'output_text', 'text': 's'}]}]}
                return SimpleNamespace(status=200, read=lambda: json.dumps(payload).encode())
            def close(self):
                pass
        with mock.patch.object(compaction_summary.availability, 'current',
                               return_value=_summary_snapshot()), \
                mock.patch.object(compaction_summary.http.client,
                                  'HTTPSConnection', FakeConn):
            return _external_responses().summarize(model, 'key', [])

    def test_summary_rows_resolve_in_primary_fallback_order(self):
        entries = compaction_summary.summary_entries(
            provider_defs.OPENROUTER.id,
            availability_snapshot=_summary_snapshot())
        self.assertEqual([entry.slug for entry in entries],
                         list(compaction_summary.SUMMARY_MODEL_SLUGS))

    def test_summary_rows_fail_closed_on_changed_pin(self):
        for changed in ('slug', 'provider', 'upstream_id', 'provider_prefs',
                        'max_output_tokens'):
            with self.subTest(changed=changed):
                rows = {slug: SimpleNamespace(
                    slug=slug, provider='openrouter', upstream_id=slug,
                    provider_prefs=None, max_output_tokens=100000)
                    for slug in compaction_summary.SUMMARY_MODEL_SLUGS}
                primary = compaction_summary.SUMMARY_MODEL_SLUGS[0]
                values = {'slug': 'other/model', 'provider': 'other',
                          'upstream_id': 'other/model',
                          'provider_prefs': {'order': ['other']},
                          'max_output_tokens': 4000}
                rows[primary] = SimpleNamespace(
                    **{**vars(rows[primary]), changed: values[changed]})
                with mock.patch.object(compaction_summary.availability, 'current',
                                       return_value=_summary_snapshot()), \
                        mock.patch.object(compaction_summary.http.client,
                                          'HTTPSConnection') as conn, \
                        mock.patch.object(providers, 'by_slug',
                                          side_effect=lambda slug: rows.get(slug)):
                    with self.assertRaisesRegex(ValueError, 'failed pin'):
                        _external_responses().summarize('z-ai/glm-5.3', 'key', [])
                conn.assert_not_called()

    def test_summarizer_uses_pinned_fast_row(self):
        seen = {}
        self.assertEqual(self._summarize('z-ai/glm-5.3', seen), 's')
        self.assertEqual(seen['model'], 'xiaomi/mimo-v2.6-flash')
        self.assertEqual(seen['reasoning'], {'effort': 'none'})
        self.assertEqual(seen['max_output_tokens'], 4000)

    def test_missing_summary_rows_fail_cleanly(self):
        with mock.patch.object(compaction_summary.availability, 'current',
                               return_value=_summary_snapshot()), \
                mock.patch.object(providers, 'by_slug', return_value=None), \
                mock.patch.object(compaction_summary.http.client,
                                  'HTTPSConnection') as conn:
            with self.assertRaisesRegex(ValueError, 'models unavailable'):
                _external_responses().summarize('unknown-model-xyz', 'key', [])
        conn.assert_not_called()

    def test_compact_remembers_discovered_tools(self):
        from tests.tool_stages import prepare_tools
        _isolated_home(self)
        items = [{'type': 'message', 'role': 'user', 'content': 'do it'},
                 {'type': 'tool_search_output', 'call_id': 's1', 'status': 'completed',
                  'execution': 'client', 'tools': [
                      {'type': 'function', 'name': 'echo', 'description': 'Echo',
                       'parameters': {'type': 'object'}}]}]
        with mock.patch.object(providers.ExternalResponsesProvider, 'summarize', lambda *a: 'did stuff'), \
                mock.patch.object(providers.ExternalResponsesProvider,
                                  '_require_summary_rows', return_value={}):
            out = _external_responses().compact('z-ai/glm-5.3', {'input': items}, 'key')
        payload = {'tools': [], 'input': out}
        payload = prepare_tools(payload)[0]
        self.assertEqual(len(payload['tools']), 1)
        self.assertEqual(payload['tools'][0]['parameters'], {'type': 'object'})


class ImageProjectionTests(unittest.TestCase):
    def test_current_turn_image_is_noted_on_text_only_rows(self):
        payload = {'model': 'z-ai/glm-5.3', 'input': [
            {'type': 'message', 'role': 'user', 'content': [
                {'type': 'input_text', 'text': 'look'},
                {'type': 'input_image', 'image_url': 'data:image/png;base64,AAA'}]}]}
        prepared = _external_responses().prepare(
            'z-ai/glm-5.3', '/responses', payload, b'raw', {}, _stub_credentials())
        body = json.dumps(json.loads(prepared.body)['input'])
        self.assertIn('Cannot read image', body)
        self.assertIn('Inform the user', body)
        self.assertNotIn('input_image', body)

    def test_historical_image_is_noted_on_text_only_rows(self):
        payload = {'model': 'z-ai/glm-5.3', 'input': [
            {'type': 'message', 'role': 'user', 'content': [
                {'type': 'input_image', 'image_url': 'data:image/png;base64,AAA'}]},
            {'type': 'message', 'role': 'user', 'content': 'next turn'}]}
        prepared = _external_responses().prepare(
            'z-ai/glm-5.3', '/responses', payload, b'raw', {}, _stub_credentials())
        body = json.dumps(json.loads(prepared.body)['input'])
        self.assertIn('Cannot read image', body)
        self.assertNotIn('input_image', body)

    def test_image_capable_models_keep_image_blocks(self):
        payload = {'model': 'moonshotai/kimi-k3', 'input': [
            {'type': 'message', 'role': 'user', 'content': [
                {'type': 'input_text', 'text': 'look'},
                {'type': 'input_image', 'image_url': 'data:image/png;base64,AAA'}]}]}
        prepared = _external_responses().prepare(
            'moonshotai/kimi-k3', '/responses', payload, b'raw', {}, _stub_credentials())
        kept = json.loads(prepared.body)['input'][0]['content']
        self.assertEqual(len(kept), 2)
        grok_payload = {'model': 'x-ai/grok-4.7', 'input': [
            {'type': 'message', 'role': 'user', 'content': [
                {'type': 'input_text', 'text': 'look'},
                {'type': 'input_image', 'image_url': 'data:image/png;base64,AAA'}]}]}
        grok_prepared = _external_responses().prepare(
            'x-ai/grok-4.7', '/responses', grok_payload, b'raw', {}, _stub_credentials())
        self.assertEqual(json.loads(grok_prepared.body)['input'][0]['content'],
            [{'type': 'input_text', 'text': 'look'},
             {'type': 'input_text', 'text': IMAGE_NOTE}])

    def test_text_only_models_pass_without_images(self):
        payload = {'model': 'z-ai/glm-5.3', 'input': [
            {'type': 'message', 'role': 'user', 'content': 'look'}]}
        prepared = _external_responses().prepare(
            'z-ai/glm-5.3', '/responses', payload, b'raw', {}, _stub_credentials())
        self.assertEqual(prepared.host, 'openrouter.ai')


class MediaRouteTests(unittest.TestCase):
    def test_image_row_cannot_use_the_chat_responses_route(self):
        from ai_router.errors import PreparationError
        payload = {'model': 'openai/gpt-image-2',
                   'reasoning': {'effort': 'none'},
                   'tools': [{'type': 'image_generation'}],
                   'input': [{'type': 'message', 'role': 'user', 'content': [
                       {'type': 'input_text', 'text': 'draw a red square'}]}]}
        with self.assertRaises(PreparationError):
            providers.select('openai/gpt-image-2', '/responses').prepare(
                'openai/gpt-image-2', '/responses', payload, b'raw', {},
                _stub_credentials())

    def test_video_turn_opens_a_job_on_the_videos_api(self):
        payload = {'model': 'google/veo-3.1-fast',
                   'reasoning': {'effort': 'none'},
                   'tools': [{'type': 'video_generation'}],
                   'input': [{'role': 'user', 'content': 'a slow push-in'}]}
        prepared = providers.select('google/veo-3.1-fast', '/responses').prepare(
            'google/veo-3.1-fast', '/responses', payload, b'raw', {},
            _stub_credentials())
        self.assertEqual(
            (prepared.host, prepared.path), ('openrouter.ai', '/api/v1/videos'))
        sent = json.loads(prepared.body)
        self.assertEqual(sent, {'model': 'google/veo-3.1-fast',
                                'prompt': 'a slow push-in'})

    def test_media_tool_on_a_chat_row_is_refused(self):
        from ai_router.errors import PreparationError
        payload = {'model': 'z-ai/glm-5.3',
                   'tools': [{'type': 'image_generation'}],
                   'input': [{'role': 'user', 'content': 'draw'}]}
        with self.assertRaises(PreparationError):
            _external_responses().prepare(
                'z-ai/glm-5.3', '/responses', payload, b'raw', {},
                _stub_credentials())

    def test_image_result_item_survives_history_replay(self):
        # A completed image_generation_call result carries `id`, not
        # `call_id`: it answers nothing, so the pairing contract and the
        # fragment scrub must both leave it alone on the next turn.
        items = [{'type': 'message', 'role': 'user', 'content': 'draw'},
                 {'type': 'image_generation_call', 'id': 'img1',
                  'status': 'completed', 'result': 'B64DATA'}]
        self.assertEqual(tool_runs.scrub_tool_fragments(items), items)
        self.assertEqual(wire_shape.pair_problems(items), {})
        self.assertEqual(tool_runs.open_calls(items), {})

    def test_media_rows_are_unlisted_preview(self):
        for slug, kind in (('openai/gpt-image-2', 'image'),
                            ('openai/gpt-image-2.5-sunburst', 'image'),
                            ('openai/gpt-image-2.5-flare', 'image'),
                            ('google/veo-3.1', 'video'),
                            ('google/veo-3.1-fast', 'video')):
            with self.subTest(model=slug):
                row = registry.by_slug(slug)
                self.assertEqual(row.tier, 'preview')
                self.assertFalse(row.listed)
                self.assertEqual(row.media_kind, kind)


if __name__ == '__main__':
    unittest.main()
