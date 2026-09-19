import json
import unittest
from types import SimpleNamespace
from unittest import mock

from ai_router import provider_defs, upstream


class FailureDescriptionTests(unittest.TestCase):
    def test_stall_before_headers_names_model_and_retry(self):
        status, message, _ = upstream.describe_failure(
            TimeoutError('timed out'), None,
            {'model': 'x-ai/grok-4.6', 'provider': 'openrouter',
             'elapsed_ms': 120001.0, 'timeout_s': 120, 'has_image': False})
        self.assertEqual(status, 502)
        self.assertIn('x-ai/grok-4.6', message)
        self.assertIn('Retry a shorter turn', message)
        self.assertNotIn('120', message)

    def test_grok_image_stall_suggests_dropping_the_image(self):
        # The hint matches the pinned id and any tilde alias of the vendor.
        for model in ('x-ai/grok-4.6', '~x-ai/grok-latest'):
            with self.subTest(model=model):
                status, message, _ = upstream.describe_failure(
                    TimeoutError('timed out'), None,
                    {'model': model, 'provider': 'openrouter',
                     'elapsed_ms': 120001.0, 'timeout_s': 120, 'has_image': True})
                self.assertEqual(status, 502)
                self.assertIn('retry without the image', message)
        _, message, _ = upstream.describe_failure(
            TimeoutError('timed out'), None,
            {'model': 'z-ai/glm-5.3', 'provider': 'openrouter',
             'elapsed_ms': 120001.0, 'timeout_s': 120, 'has_image': True})
        self.assertNotIn('image', message)

    def test_dns_failure_names_the_model_and_leaves_the_host_to_the_log(self):
        status, message, _ = upstream.describe_failure(
            OSError('Name or service not known'), None,
            {'model': 'z-ai/glm-5.3', 'provider': 'openrouter',
             'host': 'openrouter.ai', 'elapsed_ms': 12.0, 'timeout_s': 120,
             'has_image': False})
        self.assertEqual(status, 502)
        self.assertIn('z-ai/glm-5.3', message)
        self.assertNotIn('openrouter.ai', message)

    def test_nested_provider_400_becomes_actionable_400(self):
        raw = ('{"code": "invalid-argument", "error": "Failed to start sampling: '
               '[invalid_client_tool_schema] ns_abc123def456_tool_update: tool parameter '
               'root must be an object type"}')
        body = json.dumps({'error': {'message': 'Provider returned error',
                                     'metadata': {'raw': raw, 'provider_name': 'xAI'}}})
        status, message, _ = upstream.describe_failure(
            None, {'status': 400, 'body': body.encode()},
            {'model': 'x-ai/grok-4.6', 'provider': 'openrouter', 'protocol': 'responses',
             'elapsed_ms': 1831.8, 'timeout_s': 120, 'has_image': False})
        self.assertEqual(status, 400)
        self.assertIn('x-ai/grok-4.6', message)
        self.assertIn('tool schema was rejected', message)
        self.assertNotIn('xAI', message)
        self.assertNotIn('ns_abc123def456_tool_update', message)
        self.assertNotIn('Failed to start sampling', message)
        self.assertNotIn('arguments_json', message)

    def test_bare_message_body_names_recovery_without_code(self):
        body = json.dumps({'error': {'message': 'Provider returned error',
                                     'metadata': {'provider_name': 'Meta'}}})
        status, message, code = upstream.describe_failure(
            None, {'status': 400, 'body': body.encode()},
            {'model': 'meta/muse-spark-1.3-contributor', 'provider': 'openrouter',
             'protocol': 'responses',
             'elapsed_ms': 1500.0, 'timeout_s': 120, 'has_image': False, 'routed': True})
        self.assertEqual(status, 400)
        self.assertIsNone(code)
        self.assertIn('without naming a cause', message)
        self.assertIn('Switch this thread back to the previous model, '
                      'or start a new thread for meta/muse-spark-1.3-contributor',
                      message)
        self.assertNotIn('Do not retry it unchanged', message)
        self.assertNotIn('code ', message)
        self.assertNotIn('Provider returned error', message)

    def test_only_a_code_shaped_field_reaches_the_log(self):
        # A code-shaped value surfaces as the returned code, which the relay
        # logs; prose, however short, never does, in message or log.
        for raw_code, expected in ((' INVALID_Request-9 ', 'invalid_request-9'),
                                   ('MY secret token ABC123 x', None),
                                   ('invalid-request!!', None),
                                   ('x' * 100, None)):
            with self.subTest(code=raw_code):
                body = json.dumps({'error': {
                    'message': 'Provider returned error mentioning MY SECRET-SCHEMA',
                    'code': raw_code,
                    'metadata': {'provider_name': 'Meta'}}})
                self.assertEqual(upstream._provider_reason(body.encode())[3], expected)
                _, message, code = upstream.describe_failure(
                    None, {'status': 400, 'body': body.encode()},
                    {'model': 'meta/muse-spark-1.3-contributor', 'provider': 'openrouter',
                     'protocol': 'responses',
                     'elapsed_ms': 1500.0, 'timeout_s': 120, 'has_image': False,
                     'routed': True})
                self.assertEqual(code, expected)
                self.assertNotIn('MY SECRET-SCHEMA', message)
                self.assertNotIn('code ', message)

    def test_routed_flag_controls_the_recovery_sentence(self):
        body = json.dumps({'error': {'message': 'Provider returned error',
                                     'metadata': {'provider_name': 'Meta'}}})
        _, routed_message, _ = upstream.describe_failure(
            None, {'status': 400, 'body': body.encode()},
            {'model': 'meta/muse-spark-1.3-contributor', 'provider': 'openrouter',
             'protocol': 'responses',
             'elapsed_ms': 1500.0, 'timeout_s': 120, 'has_image': False, 'routed': True})
        plain_message = upstream.describe_failure(
            None, {'status': 400, 'body': body.encode()},
            {'model': 'claude-sonnet-5', 'provider': 'anthropic-subscription',
             'elapsed_ms': 1500.0, 'timeout_s': 120, 'has_image': False})[1]
        self.assertIn('Switch this thread back to the previous model', routed_message)
        self.assertNotIn('Switch this thread back', plain_message)
        self.assertIn('Do not retry it unchanged', plain_message)

    def test_error_type_and_inner_raw_code_win_in_order(self):
        body = json.dumps({'error': {'message': 'Provider returned error',
                                     'error_type': ' Upstream_Timeout ',
                                     'metadata': {'provider_name': 'Meta'}}})
        self.assertEqual(upstream._provider_reason(body.encode())[3], 'upstream_timeout')
        raw = json.dumps({'error': {'code': 'Inner_Code-9', 'error': 'boom'}})
        body = json.dumps({'error': {'message': 'Provider returned error',
                                     'metadata': {'raw': raw, 'provider_name': 'Meta'}}})
        self.assertEqual(upstream._provider_reason(body.encode())[3], 'inner_code-9')

    def test_unparseable_upstream_body_passes_through(self):
        self.assertIsNone(upstream.describe_failure(
            None, {'status': 400, 'body': b'not json at all'},
            {'model': 'z-ai/glm-5.3', 'provider': 'openrouter',
             'elapsed_ms': 500.0, 'timeout_s': 120, 'has_image': False}))
        self.assertIsNone(upstream.describe_failure(
            ValueError('odd shape'), None,
            {'model': 'z-ai/glm-5.3', 'provider': 'openrouter',
             'elapsed_ms': 500.0, 'timeout_s': 120, 'has_image': False}))


class ServingEndpointTests(unittest.TestCase):
    # Key names pinned from the router-metadata guide and the OpenAPI
    # `OpenRouterMetadata`/`EndpointInfo`/`RouterAttempt` schemas (2026-09-14):
    # `endpoints.available[]` entries carry `provider` plus `selected`, and
    # `attempts[]` entries carry `provider`.
    def test_selected_available_entry_wins(self):
        body = json.dumps({'openrouter_metadata': {
            'endpoints': {'available': [
                {'provider': 'OpenAI', 'selected': False},
                {'provider': 'DeepSeek', 'selected': True}]},
            'attempts': [{'provider': 'DeepSeek', 'status': 200}]}}).encode()
        self.assertEqual(upstream.serving_endpoint(body), 'DeepSeek')

    def test_attempts_backfill_when_nothing_selected(self):
        body = json.dumps({'error': {'metadata': {}},
                           'openrouter_metadata': {
                               'endpoints': {'available': []},
                               'attempts': [{'provider': 'xAI', 'status': 400}]}})
        self.assertEqual(upstream.serving_endpoint(body), 'xAI')

    def test_last_attempt_wins_the_failover(self):
        body = json.dumps({'openrouter_metadata': {'attempts': [
            {'provider': 'OpenAI', 'status': 500},
            {'provider': 'DeepSeek', 'status': 429}]}}).encode()
        self.assertEqual(upstream.serving_endpoint(body), 'DeepSeek')

    def test_error_provider_name_is_the_last_resort(self):
        body = json.dumps({'error': {'metadata': {'provider_name': 'Meta'}}}).encode()
        self.assertEqual(upstream.serving_endpoint(body), 'Meta')

    def test_prose_never_reaches_the_log(self):
        body = json.dumps({'openrouter_metadata': {
            'summary': 'available=1, selected=OpenAI',
            'endpoints': {'available': [
                {'provider': 'Not a slug; retry shortly!', 'selected': True}]}}}).encode()
        self.assertIsNone(upstream.serving_endpoint(body))

    def test_vendor_slash_slugs_pass(self):
        body = json.dumps({'openrouter_metadata': {'attempts': [
            {'provider': 'fireworks/deepseek-v4', 'status': 200}]}}).encode()
        self.assertEqual(upstream.serving_endpoint(body), 'fireworks/deepseek-v4')

    def test_garbage_returns_none(self):
        self.assertIsNone(upstream.serving_endpoint(b'not json'))
        self.assertIsNone(upstream.serving_endpoint({'openrouter_metadata': {}}))
        self.assertIsNone(upstream.serving_endpoint(None))


class RelayEndpointLogTests(unittest.TestCase):
    def setUp(self):
        upstream.clear_refusals()
        self.addCleanup(upstream.clear_refusals)

    def _relay(self, status, raw):
        from ai_router import relay
        from ai_router.transport import Prepared

        class FakeResp:
            def __init__(self): self.status = status
            def read(self, *a): return raw
            def getheader(self, *a, **k): return ''

        class FakeConn:
            def __init__(self, *a, **k): pass
            def connect(self): pass
            def request(self, *a, **k): pass
            def getresponse(self): return FakeResp()
            def close(self): pass

        handler = SimpleNamespace(
            server=SimpleNamespace(credentials=SimpleNamespace(
                key_rejected=lambda provider: False)),
            error=lambda err, **k: None)
        provider = SimpleNamespace(defn=provider_defs.OPENROUTER)
        body = json.dumps({'model': 'm', 'input': []}).encode()
        prepared = Prepared('openrouter.ai', '/responses', {}, body, {}, 'openrouter')
        metrics = {'provider': 'openrouter', 'protocol': 'responses',
                   'model': 'm', 'path': '/responses'}
        events = []
        with mock.patch.object(relay.http.client, 'HTTPSConnection', FakeConn):
            relay.relay(handler, provider, prepared, metrics, 0.0,
                        log_event=lambda event, **f: events.append((event, f)))
        return events

    def test_rejected_400_carries_the_serving_endpoint(self):
        raw = json.dumps({'error': {'message': 'Provider returned error',
                                     'metadata': {'provider_name': 'xAI'}},
                          'openrouter_metadata': {'attempts': [
                              {'provider': 'xAI', 'status': 400}]}}).encode()
        events = self._relay(400, raw)
        rejected = [f for e, f in events if e == 'upstream_rejected']
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]['serving_endpoint'], 'xAI')

    def test_unavailable_503_carries_the_serving_endpoint(self):
        raw = json.dumps({'error': {'message': 'No available provider', 'code': 503},
                          'openrouter_metadata': {'attempts': [
                              {'provider': 'DeepSeek', 'status': 503}]}}).encode()
        events = self._relay(503, raw)
        unavailable = [f for e, f in events if e == 'upstream_unavailable']
        self.assertEqual(len(unavailable), 1)
        self.assertEqual(unavailable[0]['serving_endpoint'], 'DeepSeek')

    def test_402_logs_fixed_category_and_no_upstream_prose(self):
        raw = json.dumps({'error': {'message': 'Provider blew up on MARKER-402',
                                     'metadata': {'provider_name': 'Meta'}}}).encode()
        events = self._relay(402, raw)
        rejected = [f for e, f in events if e == 'upstream_rejected']
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]['code'], 'KEY_NO_CREDIT')
        self.assertEqual(rejected[0]['category'], 'KEY_NO_CREDIT')
        self.assertNotIn('serving_endpoint', rejected[0])
        self.assertNotIn('parameter', rejected[0])
        self.assertNotIn('MARKER-402', json.dumps(rejected))


class RefusalCacheTests(unittest.TestCase):
    def setUp(self):
        upstream.clear_refusals()
        self.addCleanup(upstream.clear_refusals)

    def _refusal_body(self, marker='boom'):
        return json.dumps({'error': {'message': f'Provider blew up on {marker}',
                                     'metadata': {'provider_name': 'Meta'}}}).encode()

    def test_identical_body_answers_twice_with_one_dispatch(self):
        from ai_router import relay
        from ai_router.transport import Prepared
        dispatches = []
        refused = self._refusal_body()

        class FakeResp:
            status = 400
            def read(self, *a): return refused
            def getheader(self, *a, **k): return ''

        class FakeConn:
            def __init__(self, *a, **k): pass
            def connect(self): pass
            def request(self, *a, **k): dispatches.append(1)
            def getresponse(self): return FakeResp()
            def close(self): pass

        seen = {}
        handler = SimpleNamespace(
            server=SimpleNamespace(credentials=SimpleNamespace(
                key_rejected=lambda provider: False)),
            error=lambda err: seen.update(err=err))
        provider = SimpleNamespace(defn=provider_defs.OPENROUTER)
        body = json.dumps({'model': 'm', 'input': [], 'tools': []}).encode()
        prepared = Prepared('openrouter.ai', '/responses', {}, body, {}, 'openrouter')
        metrics = {'provider': 'openrouter', 'protocol': 'responses',
                   'model': 'meta/muse-spark-1.3-contributor', 'path': '/responses'}
        events = []
        with mock.patch.object(relay.http.client, 'HTTPSConnection', FakeConn):
            relay.relay(handler, provider, prepared, metrics, 0.0,
                        log_event=lambda event, **f: events.append((event, f)))
            first = seen['err']
            relay.relay(handler, provider, prepared, metrics, 0.0,
                        log_event=lambda event, **f: events.append((event, f)))
        self.assertEqual(len(dispatches), 1)
        self.assertEqual(seen['err'].status, 400)
        self.assertEqual(seen['err'].message, first.message)
        cached = [e for e, _ in events if e == 'upstream_rejected_cached']
        self.assertEqual(len(cached), 1)
        fields = dict(events[-1][1])
        self.assertNotIn('request_bytes', fields)

    def test_changed_body_dispatches_again(self):
        body = json.dumps({'input': []}).encode()
        upstream.remember_refusal('openrouter', 'm', body, 'MSG', now=10.0)
        self.assertEqual(upstream.recall_refusal('openrouter', 'm', body, now=20.0), (400, 'MSG'))
        self.assertIsNone(upstream.recall_refusal(
            'openrouter', 'm', json.dumps({'input': [1]}).encode(), now=20.0))

    def test_entries_expire_after_60_seconds(self):
        body = b'same'
        upstream.remember_refusal('openrouter', 'm', body, 'MSG', now=100.0)
        self.assertEqual(upstream.recall_refusal('openrouter', 'm', body, now=160.0), (400, 'MSG'))
        self.assertIsNone(upstream.recall_refusal('openrouter', 'm', body, now=160.1))

    def test_cache_caps_at_8_entries(self):
        for i in range(9):
            upstream.remember_refusal('openrouter', 'm', f'body-{i}'.encode(),
                                      f'MSG-{i}', now=100.0 + i)
        self.assertEqual(len(upstream._REFUSALS), 8)
        self.assertIsNone(upstream.recall_refusal('openrouter', 'm', b'body-0', now=110.0))
        self.assertEqual(upstream.recall_refusal('openrouter', 'm', b'body-8', now=110.0),
                         (400, 'MSG-8'))

    def test_responses_upstream_5xx_is_a_retryable_503(self):
        body = json.dumps({'error': {'message': 'No available provider',
                                     'code': 503}}).encode()
        status, message, _ = upstream.describe_failure(
            None, {'status': 503, 'body': body},
            {'model': 'm', 'provider': 'openrouter', 'protocol': 'responses',
             'elapsed_ms': 10.0, 'timeout_s': 120, 'has_image': False, 'routed': True})
        self.assertEqual(status, 503)
        self.assertIn('unavailable', message)
        self.assertIn('Retry shortly', message)
        self.assertNotIn('Do not retry', message)

    def test_responses_upstream_408_is_a_retryable_503(self):
        body = json.dumps({'error': {'message': 'timed out'}}).encode()
        status, _, _ = upstream.describe_failure(
            None, {'status': 408, 'body': body},
            {'model': 'm', 'provider': 'openrouter', 'protocol': 'responses',
             'elapsed_ms': 10.0, 'timeout_s': 120, 'has_image': False, 'routed': True})
        self.assertEqual(status, 503)

    def test_messages_upstream_5xx_keeps_todays_409(self):
        body = json.dumps({'error': {'message': 'Provider returned error'}}).encode()
        status, message, _ = upstream.describe_failure(
            None, {'status': 502, 'body': body},
            {'model': 'm', 'provider': 'openrouter', 'protocol': 'messages',
             'elapsed_ms': 10.0, 'timeout_s': 120, 'has_image': False})
        self.assertEqual(status, 409)
        self.assertIn('Do not retry it unchanged', message)

    def test_classify_429_quota_auth_and_transient(self):
        quota = json.dumps({'error': {'message': 'slow down', 'code': 'insufficient_quota'}})
        auth = json.dumps({'error': {'message': 'slow down', 'code': 'invalid_api_key'}})
        fuzzy_quota = json.dumps({'error': {'message': 'slow down',
                                            'metadata': {'provider_code': 'billing_hard_limit'}}})
        transient = json.dumps({'error': {'message': 'Rate limited: quota words in prose only'}})
        self.assertEqual(upstream.classify_429(quota), 'quota')
        self.assertEqual(upstream.classify_429(auth), 'auth')
        self.assertEqual(upstream.classify_429(fuzzy_quota), 'quota')
        # Prose never classifies: only structured code fields count.
        self.assertEqual(upstream.classify_429(transient), 'transient')
        self.assertEqual(upstream.classify_429(b'not json'), 'transient')

    def test_upstream_retry_after_returns_category_and_header(self):
        from types import SimpleNamespace
        logged = []
        with mock.patch.object(upstream, 'log_event',
                               lambda event, **f: logged.append((event, f))):
            response = SimpleNamespace(status=429, getheader=lambda *a, **k: '7')
            prepared = SimpleNamespace(provider='openrouter')
            self.assertEqual(upstream.upstream_retry_after(
                response, prepared, {'path': '/responses'},
                body=b'{"error": {"code": "x"}}'), ('transient', '7'))
            self.assertEqual(logged[-1], ('upstream_rate_limited',
                                          {'provider': 'openrouter', 'path': '/responses',
                                           'category': 'transient'}))
            other = SimpleNamespace(status=200, getheader=lambda *a, **k: '2')
            self.assertIsNone(upstream.upstream_retry_after(
                other, prepared, {'path': '/responses'}, body=b''))

    def test_transient_upstream_failure_dispatches_again(self):
        from ai_router import relay
        from ai_router.transport import Prepared
        dispatches = []
        refused = self._refusal_body()

        class FakeResp:
            status = 502
            def read(self, *a): return refused
            def getheader(self, *a, **k): return ''

        class FakeConn:
            def __init__(self, *a, **k): pass
            def connect(self): pass
            def request(self, *a, **k): dispatches.append(1)
            def getresponse(self): return FakeResp()
            def close(self): pass

        seen = {}
        handler = SimpleNamespace(
            server=SimpleNamespace(credentials=SimpleNamespace(
                key_rejected=lambda provider: False)),
            error=lambda err: seen.setdefault('err', err))
        provider = SimpleNamespace(defn=provider_defs.OPENROUTER)
        body = json.dumps({'model': 'm', 'input': [], 'tools': []}).encode()
        prepared = Prepared('openrouter.ai', '/responses', {}, body, {}, 'openrouter')
        metrics = {'provider': 'openrouter', 'protocol': 'responses',
                   'model': 'meta/muse-spark-1.3-contributor', 'path': '/responses'}
        events = []
        with mock.patch.object(relay.http.client, 'HTTPSConnection', FakeConn):
            for _ in range(2):
                relay.relay(handler, provider, prepared, metrics, 0.0,
                            log_event=lambda event, **f: events.append((event, f)))
        self.assertEqual(len(dispatches), 2)
        self.assertEqual([e for e, _ in events if e == 'upstream_rejected_cached'], [])
        self.assertEqual(len(upstream._REFUSALS), 0)

    def test_non_responses_route_is_not_cached(self):
        from ai_router import relay
        from ai_router.transport import Prepared
        dispatches = []
        refused = self._refusal_body()

        class FakeResp:
            status = 400
            def read(self, *a): return refused
            def getheader(self, *a, **k): return ''

        class FakeConn:
            def __init__(self, *a, **k): pass
            def connect(self): pass
            def request(self, *a, **k): dispatches.append(1)
            def getresponse(self): return FakeResp()
            def close(self): pass

        handler = SimpleNamespace(
            server=SimpleNamespace(credentials=SimpleNamespace(
                key_rejected=lambda provider: False)),
            error=lambda err: None)
        provider = SimpleNamespace(defn=provider_defs.OPENROUTER)
        body = json.dumps({'model': 'm', 'messages': [{'role': 'user', 'content': 'hi'}]}).encode()
        prepared = Prepared('openrouter.ai', '/v1/messages', {}, body, {}, 'openrouter')
        metrics = {'provider': 'openrouter', 'protocol': 'messages',
                   'model': 'anthropic/claude-opus-5', 'path': '/v1/messages'}
        with mock.patch.object(relay.http.client, 'HTTPSConnection', FakeConn):
            for _ in range(2):
                relay.relay(handler, provider, prepared, metrics, 0.0,
                            log_event=lambda event, **f: None)
        self.assertEqual(len(dispatches), 2)
        self.assertEqual(len(upstream._REFUSALS), 0)

    def test_concurrent_remember_is_safe_and_capped(self):
        import threading
        failures = []

        def worker(n):
            try:
                for i in range(200):
                    upstream.remember_refusal('openrouter', 'm', f'{n}-{i}'.encode(), 'MSG')
                    upstream.recall_refusal('openrouter', 'm', f'{n}-{i}'.encode())
            except Exception as exc:  # noqa: BLE001 - the test asserts nothing escapes
                failures.append(exc)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(failures, [])
        self.assertLessEqual(len(upstream._REFUSALS), 8)
