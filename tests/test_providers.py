import json
import io
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest import mock
from ai_router import provider_defs, providers
from ai_router.image_items import IMAGE_NOTE
from tests.harness import (
    isolated_home as _isolated_home,
    stub_credentials as _stub_credentials,
)


def _external_responses():
    """The OpenRouter Codes adapter; Plan 141 makes adapters per-provider."""
    return providers.ExternalResponsesProvider(provider_defs.OPENROUTER)


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
            def request(self, method, path, body=None, headers=None):
                seen.update(headers)
                seen['body'] = json.loads(body)
            def getresponse(self):
                payload = {'output': [{'type': 'message', 'content': [
                    {'type': 'output_text', 'text': 's'}]}]}
                return SimpleNamespace(status=200,
                                        read=lambda: json.dumps(payload).encode())
            def close(self):
                pass
        with mock.patch.object(providers.http.client, 'HTTPSConnection', FakeConn):
            _external_responses().summarize('z-ai/glm-5.3', 'key', [])
        self.assertEqual(seen.get('X-OpenRouter-Metadata'), 'enabled')
        self.assertNotIn('provider', seen['body'])


class ProviderPrefsTests(unittest.TestCase):
    def _entry(self, prefs):
        return SimpleNamespace(slug='x/m', provider='openrouter',
                               max_output_tokens=1000, context_window=0,
                               provider_prefs=prefs, drop_images=False)

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

    def test_summarizer_body_carries_provider_exactly_when_set(self):
        seen = {}

        class FakeConn:
            def __init__(self, *a, **k):
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
        with mock.patch.object(providers.http.client, 'HTTPSConnection', FakeConn), \
                mock.patch.object(providers, 'by_slug',
                                   return_value=self._entry(prefs)):
            _external_responses().summarize('x/m', 'key', [])
        self.assertEqual(seen.get('provider'), prefs)


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

    def test_summarizer_pins_lowest_supported_effort(self):
        for model, effort in (('deepseek/deepseek-v4.1-flash', 'low'),
                              ('z-ai/glm-5.3', 'low')):
            with self.subTest(model=model):
                seen = {}
                self.assertEqual(self._summarize(model, seen), 's')
                self.assertEqual(seen['reasoning'], {'effort': effort})

    def test_summarizer_raises_output_cap_and_omits_effort_when_unknown(self):
        seen = {}
        self._summarize('z-ai/glm-5.3', seen)
        self.assertEqual(seen['max_output_tokens'], 4000)
        seen = {}
        self._summarize('unknown-model-xyz', seen)
        self.assertNotIn('reasoning', seen)

    def test_compact_remembers_discovered_tools(self):
        from ai_router.tool_adapter import prepare_tools
        _isolated_home(self)
        items = [{'type': 'message', 'role': 'user', 'content': 'do it'},
                 {'type': 'tool_search_output', 'call_id': 's1', 'status': 'completed',
                  'execution': 'client', 'tools': [
                      {'type': 'function', 'name': 'echo', 'description': 'Echo',
                       'parameters': {'type': 'object'}}]}]
        with mock.patch.object(providers.ExternalResponsesProvider, 'summarize', lambda *a: 'did stuff'):
            out = _external_responses().compact('z-ai/glm-5.3', {'input': items}, 'key')
        payload = {'tools': [], 'input': out}
        prepare_tools(payload)
        self.assertEqual(len(payload['tools']), 1)
        self.assertEqual(payload['tools'][0]['parameters'], {'type': 'object'})


class SummarizerRetryTests(unittest.TestCase):
    @staticmethod
    def _result(text='summary', status=None, **extra):
        payload = {'output': [{'type': 'message', 'content': [
            {'type': 'output_text', 'text': text}]}]}
        if status is not None:
            payload['status'] = status
        payload.update(extra)
        return 200, payload

    @classmethod
    def _truncated(cls):
        result = cls._result('partial', status='incomplete',
                             incomplete_details={'reason': 'max_output_tokens'})
        result[1]['output'][0]['status'] = 'incomplete'
        return result

    def _run(self, responses, model='z-ai/glm-5.3', ceiling=None):
        queue, calls, closed = list(responses), [], []

        class Response:
            def __init__(self, status, payload):
                self.status = status
                self.body = io.BytesIO(json.dumps(payload).encode())

            def read(self, *args):
                return self.body.read(*args)

        class Connection:
            def __init__(self, *args, **kwargs):
                calls.append({'timeout': kwargs.get('timeout')})

            def request(self, method, path, body=None, headers=None):
                calls[-1]['body'] = json.loads(body)

            def getresponse(self):
                if not queue:
                    raise AssertionError('summarizer retried beyond the fixture')
                response = queue.pop(0)
                if isinstance(response, BaseException):
                    raise response
                return Response(*response)

            def close(self):
                closed.append(True)

        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(
                providers.http.client, 'HTTPSConnection', Connection))
            if ceiling is not None:
                stack.enter_context(mock.patch.object(
                    providers, 'by_slug',
                    return_value=SimpleNamespace(max_output_tokens=ceiling, slug=model)))
            try:
                result = _external_responses().summarize(model, 'key', [
                    {'type': 'message', 'role': 'user', 'content': 'marker'}])
            except Exception as exc:  # Return the result so every path checks closure.
                result = exc
        return result, calls, closed

    def test_truncated_summary_retries_once_and_keeps_request(self):
        with mock.patch.object(providers, 'log_event') as logged:
            result, calls, closed = self._run([
                self._truncated(), self._result('complete')])
        self.assertEqual(result, 'complete')
        self.assertEqual([call['body']['max_output_tokens'] for call in calls],
                         [4000, 8000])
        self.assertEqual(calls[0]['body']['input'], calls[1]['body']['input'])
        self.assertEqual(calls[0]['body']['reasoning'], {'effort': 'low'})
        self.assertEqual(len(calls), len(closed))
        events = [call.kwargs for call in logged.call_args_list
                  if call.args and call.args[0] == 'compact_summary_attempt']
        self.assertEqual([event['outcome'] for event in events],
                         ['retry', 'completed'])
        self.assertTrue(all(set(event) <= {
            'model', 'attempt', 'max_output_tokens', 'outcome'} for event in events))

    def test_retry_ceiling_clamps_or_disables_second_attempt(self):
        result, calls, closed = self._run([
            self._truncated(), self._result('complete')], ceiling=6000)
        self.assertEqual(result, 'complete')
        self.assertEqual([call['body']['max_output_tokens'] for call in calls],
                         [4000, 6000])
        self.assertEqual(len(calls), len(closed))
        result, calls, closed = self._run([self._truncated()], ceiling=4000)
        self.assertIsInstance(result, providers.comp.IncompleteSummary)
        self.assertEqual([call['body']['max_output_tokens'] for call in calls],
                         [4000])
        self.assertEqual(len(calls), len(closed))

    def test_truncation_twice_is_rejected_after_two_attempts(self):
        result, calls, closed = self._run([self._truncated(), self._truncated()])
        self.assertIsInstance(result, providers.comp.IncompleteSummary)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(calls), len(closed))

    def test_retry_uses_one_shared_deadline(self):
        with mock.patch.object(providers.time, 'monotonic',
                               side_effect=[0, 1, 2, 3]):
            result, calls, closed = self._run([
                self._truncated(), self._result('complete')])
        self.assertEqual(result, 'complete')
        self.assertLess(calls[1]['timeout'], calls[0]['timeout'])
        self.assertLessEqual(calls[0]['timeout'], providers.SUMMARY_DEADLINE_S)
        self.assertEqual(len(calls), len(closed))
        with mock.patch.object(providers.time, 'monotonic',
                               side_effect=[0, 1, 120]):
            result, calls, closed = self._run([self._truncated()])
        self.assertIsInstance(result, TimeoutError)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls), len(closed))

    def test_other_failures_do_not_retry(self):
        valid = self._result('partial')
        cases = {
            'failed status': self._result(status='failed'),
            'in progress': self._result(status='in_progress'),
            'embedded error': (200, {**valid[1], 'error': {'code': 'bad'}}),
            'empty': (200, {'output': []}),
            'malformed': (200, {'output': 'bad'}),
            'auth': (401, {'error': 'unauthorized'}),
            'timeout': TimeoutError('timed out'),
        }
        for name, response in cases.items():
            with self.subTest(name=name):
                result, calls, closed = self._run([response])
                self.assertIsInstance(result, Exception)
                self.assertNotIsInstance(result, providers.comp.IncompleteSummary)
                self.assertEqual(len(calls), 1)
                self.assertEqual(len(calls), len(closed))

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


if __name__ == '__main__':
    unittest.main()
