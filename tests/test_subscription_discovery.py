"""Native subscription catalogue validation and dynamic roster composition."""
import json
import time
import unittest
import urllib.error
from types import SimpleNamespace
from unittest import mock

from ai_router import subscription_catalogue, subscription_discovery


class _Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, _size=None):
        return self.body


class SubscriptionCatalogueTests(unittest.TestCase):
    def test_live_discovery_keeps_unknown_model_and_drops_unadvertised_successor(self):
        rows = subscription_catalogue.validate({'models': [
            {'slug': 'gpt-new', 'display_name': 'GPT-New'},
            {'slug': 'gpt-5.6-luna', 'display_name': 'GPT-5.6-Luna'},
        ]})
        roster = subscription_catalogue.effective_roster(
            ['gpt-5.6-luna'], [row['slug'] for row in rows])
        self.assertEqual(roster, ('gpt-new',))

    def test_configured_order_wins_for_models_the_server_still_advertises(self):
        roster = subscription_catalogue.effective_roster(
            ['gpt-6-luna', 'gpt-6-sol', 'gone'],
            ['gpt-new', 'gpt-6-sol', 'gpt-6-luna'])
        self.assertEqual(roster, ('gpt-6-luna', 'gpt-6-sol', 'gpt-new'))

    def test_bad_native_shapes_fail_closed(self):
        cases = ({}, {'models': {}}, {'models': [None]},
                 {'models': [{'slug': 'x'}]},
                 {'models': [{'slug': 'x', 'display_name': 'X'},
                             {'slug': 'x', 'display_name': 'X'}]},
                 {'models': [{'slug': 'x', 'display_name': 'X',
                              'supported_reasoning_levels': ['low']}]},
                 {'models': [{'slug': 'x', 'display_name': 'X',
                              'supported_reasoning_levels': [
                                  {'effort': 'low', 'description': ''}],
                              'default_reasoning_level': 'high'}]},
                 {'models': [{'slug': 'x', 'display_name': 'X',
                              'supported_reasoning_levels': [
                                  {'effort': 'low', 'description': ''}]}]},
                 {'models': [{'slug': 'x', 'display_name': 'X',
                              'default_reasoning_level': 'low'}]},
                 {'models': [{'slug': 'x', 'display_name': 'X', 'hidden': 'yes'}]},
                 {'models': [{'slug': 'x', 'display_name': 'X',
                              'context_window': 0}]})
        for document in cases:
            with self.subTest(document=document):
                with self.assertRaises(ValueError):
                    subscription_catalogue.validate(document)

    def test_fetch_is_bounded_and_preserves_client_version(self):
        seen = {}

        def urlopen(request, timeout):
            seen['url'] = request.full_url
            seen['timeout'] = timeout
            return _Response(json.dumps({'models': [
                {'slug': 'gpt-new', 'display_name': 'GPT-New'}]}).encode())

        rows = subscription_discovery.fetch_native(
            {'Authorization': 'Bearer client'}, '0.155.0', _urlopen=urlopen)
        self.assertEqual(rows[0]['slug'], 'gpt-new')
        self.assertEqual(seen['timeout'], subscription_discovery.TIMEOUT_S)
        self.assertIn('client_version=0.155.0', seen['url'])

    def test_router_bearer_is_not_forwarded_to_chatgpt(self):
        seen = {}

        def urlopen(request, timeout):
            seen['headers'] = request.headers
            return _Response(b'{\"models\": []}')

        subscription_discovery.fetch_native(
            {'Authorization': 'Bearer router-token', 'User-Agent': 'Codex'},
            router_token='router-token', _urlopen=urlopen)
        self.assertNotIn('Authorization', seen['headers'])
        self.assertEqual(seen['headers']['User-agent'], 'Codex')

    def test_cache_identity_separates_account_and_client_version(self):
        first = {'Authorization': 'Bearer client', 'ChatGPT-Account-ID': 'a'}
        same = dict(first)
        other_account = dict(first, **{'ChatGPT-Account-ID': 'b'})
        self.assertEqual(subscription_discovery._identity(first, '1'),
                         subscription_discovery._identity(same, '1'))
        self.assertNotEqual(subscription_discovery._identity(first, '1'),
                            subscription_discovery._identity(other_account, '1'))
        self.assertNotEqual(subscription_discovery._identity(first, '1'),
                            subscription_discovery._identity(first, '2'))

    def test_request_membership_is_scoped_to_each_identity(self):
        from ai_router import providers
        from ai_router.errors import UnknownModel
        server = SimpleNamespace(state={
            'openai_models': ['gpt-static'],
            'openai_model_preferences': ['gpt-static']}, _subscription_snapshots={})
        first = {'Authorization': 'Bearer client', 'ChatGPT-Account-ID': 'a'}
        second = {'Authorization': 'Bearer client', 'ChatGPT-Account-ID': 'b'}
        for headers, slug in ((first, 'gpt-a'), (second, 'gpt-b')):
            identity = subscription_discovery._identity(headers, '1')
            server._subscription_snapshots[identity] = {
                'rows': (), 'roster': (slug,), 'identity': identity,
                'routing': subscription_discovery._routing_identity(headers),
                'auth': subscription_discovery._auth_identity(headers),
                'client_version': '1',
                'fetched_at': time.time()}
        self.assertEqual(subscription_discovery.request_models(
            server, first, 'client_version=1'), ('gpt-a',))
        self.assertEqual(subscription_discovery.request_models(
            server, second, 'client_version=1'), ('gpt-b',))
        self.assertEqual(providers.select(
            'gpt-a', '/responses', subscription_discovery.request_models(
                server, first, 'client_version=1')).name, 'openai')
        with self.assertRaises(UnknownModel):
            providers.select('gpt-b', '/responses', subscription_discovery.request_models(
                server, first, 'client_version=1'))

    def test_post_without_bearer_uses_the_discovery_routing_identity(self):
        server = SimpleNamespace(state={
            'openai_models': ['gpt-static']},
            _subscription_snapshots={})
        discovery_headers = {'Authorization': 'Bearer client',
                             'ChatGPT-Account-ID': 'a'}
        identity = subscription_discovery._identity(discovery_headers, '1')
        subscription_discovery._publish(
            server, (), ('gpt-new',), identity,
            subscription_discovery._routing_identity(discovery_headers),
            subscription_discovery._auth_identity(discovery_headers), '1')
        self.assertEqual(subscription_discovery.request_models(
            server, {'ChatGPT-Account-ID': 'a'}), ('gpt-new',))

    def test_post_without_identity_fails_back_to_static_roster(self):
        server = SimpleNamespace(state={
            'openai_models': ['gpt-static']},
            _subscription_snapshots={})
        headers = {'Authorization': 'Bearer client'}
        subscription_discovery._publish(
            server, (), ('gpt-live',),
            subscription_discovery._identity(headers, '1'), '',
            subscription_discovery._auth_identity(headers), '1')
        self.assertEqual(subscription_discovery.request_models(server, {}),
                         ('gpt-static',))

    def test_unversioned_post_refuses_ambiguous_versioned_snapshots(self):
        server = SimpleNamespace(state={
            'openai_models': ['gpt-static']},
            _subscription_snapshots={})
        headers = {'Authorization': 'Bearer client'}
        for version, slug in (('1', 'gpt-v1'), ('2', 'gpt-v2')):
            subscription_discovery._publish(
                server, (), (slug,),
                subscription_discovery._identity(headers, version), '',
                subscription_discovery._auth_identity(headers), version)
        self.assertEqual(subscription_discovery.request_models(server, headers),
                         ('gpt-static',))

    def test_models_route_adds_unknown_subscription_and_updates_routing(self):
        state = {'port': 1, 'token': 'router-token', 'openai_models': ['gpt-6-astra']}
        server = SimpleNamespace(state=state, _subscription_snapshots={})
        sent = {}

        handler = SimpleNamespace(
            headers={'Authorization': 'Bearer client'}, server=server,
            send_json=lambda status, payload: sent.update(
                status=status, payload=payload),
            error=lambda error: sent.update(error=error))

        rows = ({'slug': 'gpt-new', 'display_name': 'GPT-New',
                 'supported_reasoning_levels': [
                     {'effort': 'low', 'description': 'Low'}],
                 'default_reasoning_level': 'low',
                 'input_modalities': ['text'], 'priority': 900},)
        with mock.patch.object(subscription_discovery, 'fetch_native',
                               return_value=rows):
            subscription_discovery.serve(handler, 'client_version=0.155.0')
        self.assertEqual(sent['status'], 200)
        self.assertIn('gpt-new', state['openai_models'])
        self.assertNotIn('gpt-6-astra', state['openai_models'])
        self.assertEqual(state['openai_model_preferences'], ['gpt-6-astra'])
        by_slug = {row['slug']: row for row in sent['payload']['models']}
        self.assertIn('gpt-new', by_slug)
        self.assertNotIn('openai/gpt-new', by_slug)
        self.assertEqual(by_slug['gpt-new']['priority'], 1)
        self.assertEqual(by_slug['gpt-new']['input_modalities'], ['text'])

    def test_successful_empty_response_replaces_live_membership(self):
        state = {'port': 1, 'token': 'router-token',
                 'openai_models': ['gpt-6-astra'],
                 'openai_model_preferences': ['gpt-6-astra']}
        server = SimpleNamespace(state=state, _subscription_snapshots={})
        sent = {}
        handler = SimpleNamespace(
            headers={'Authorization': 'Bearer client'}, server=server,
            send_json=lambda status, payload: sent.update(
                status=status, payload=payload),
            error=lambda error: sent.update(error=error))
        with mock.patch.object(subscription_discovery, 'fetch_native',
                               return_value=()):
            subscription_discovery.serve(handler, 'client_version=0.155.0')
        self.assertEqual(state['openai_models'], [])
        self.assertEqual(state['openai_model_preferences'], ['gpt-6-astra'])
        self.assertNotIn('gpt-6-astra',
                         {row['slug'] for row in sent['payload']['models']})

    def test_authentication_rejection_clears_and_never_serves_stale_cache(self):
        headers = {'Authorization': 'Bearer client', 'ChatGPT-Account-ID': 'a'}
        snapshot = {
            'rows': ({'slug': 'gpt-old', 'display_name': 'GPT-Old'},),
            'roster': ('gpt-old',),
            'identity': subscription_discovery._identity(headers, '1'),
            'routing': subscription_discovery._routing_identity(headers),
            'auth': subscription_discovery._auth_identity(headers),
            'client_version': '1',
            'fetched_at': time.time(),
        }
        state = {'port': 1, 'token': 'router-token', 'openai_models': ['gpt-old']}
        server = SimpleNamespace(state=state, _subscription_snapshots={
            snapshot['identity']: snapshot})
        sent = {}
        handler = SimpleNamespace(
            headers=headers, server=server,
            send_json=lambda status, payload: sent.update(
                status=status, payload=payload),
            error=lambda error: sent.update(error=error))
        rejection = urllib.error.HTTPError(
            'https://chatgpt.com/backend-api/codex/models', 401, 'Denied',
            {}, None)
        with mock.patch.object(subscription_discovery, 'fetch_native',
                               side_effect=rejection):
            subscription_discovery.serve(handler, 'client_version=1')
        self.assertEqual(sent['error'].status, 401)
        self.assertEqual(server._subscription_snapshots, {})
        self.assertNotIn('payload', sent)

    def test_stale_cache_requires_same_account_and_client_version(self):
        old_headers = {'Authorization': 'Bearer client',
                       'ChatGPT-Account-ID': 'a'}
        snapshot = {
            'rows': ({'slug': 'gpt-old', 'display_name': 'GPT-Old'},),
            'roster': ('gpt-old',),
            'identity': subscription_discovery._identity(old_headers, '1'),
            'fetched_at': time.time(),
        }
        state = {'port': 1, 'token': 'router-token', 'openai_models': ['gpt-old']}
        server = SimpleNamespace(state=state, _subscription_snapshots={
            snapshot['identity']: snapshot})
        sent = {}
        handler = SimpleNamespace(
            headers={'Authorization': 'Bearer client',
                     'ChatGPT-Account-ID': 'b'},
            server=server,
            send_json=lambda status, payload: sent.update(
                status=status, payload=payload),
            error=lambda error: sent.update(error=error))
        with mock.patch.object(subscription_discovery, 'fetch_native',
                               side_effect=ValueError('offline')):
            subscription_discovery.serve(handler, 'client_version=1')
        self.assertEqual(sent['error'].status, 503)
        self.assertNotIn('payload', sent)

    def test_failed_composition_needs_no_cache(self):
        state = {'port': 1, 'token': 'router-token', 'openai_models': ['gpt-6-astra']}
        server = SimpleNamespace(state=state, _subscription_snapshots={})
        sent = {}
        handler = SimpleNamespace(
            headers={'Authorization': 'Bearer client'}, server=server,
            send_json=lambda status, payload: sent.update(
                status=status, payload=payload),
            error=lambda error: sent.update(error=error))
        rows = ({'slug': 'gpt-new', 'display_name': 'GPT-New'},)
        with mock.patch.object(subscription_discovery, 'fetch_native',
                               return_value=rows), \
                mock.patch.object(subscription_discovery.catalogue, 'merge',
                                  side_effect=ValueError('bad row')):
            subscription_discovery.serve(handler, 'client_version=1')
        self.assertEqual(sent['error'].status, 503)
        self.assertEqual(server._subscription_snapshots, {})
        self.assertEqual(state['openai_models'], ['gpt-6-astra'])
        self.assertNotIn('openai_model_preferences', state)


if __name__ == '__main__':
    unittest.main()
