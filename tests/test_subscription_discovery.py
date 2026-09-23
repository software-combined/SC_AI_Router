"""Native subscription catalogue validation and dynamic roster composition."""
import json
import unittest
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
    def test_unknown_model_is_kept_and_retired_model_is_not_seeded(self):
        rows = subscription_catalogue.validate({'models': [
            {'slug': 'gpt-new', 'display_name': 'GPT-New'},
            {'slug': 'gpt-5.6-luna', 'display_name': 'GPT-5.6-Luna'},
        ]})
        roster = subscription_catalogue.effective_roster(
            ['gpt-5.6-luna'], [row['slug'] for row in rows])
        self.assertEqual(roster, ('gpt-6-luna', 'gpt-new'))

    def test_bad_native_shapes_fail_closed(self):
        cases = ({}, {'models': {}}, {'models': [None]},
                 {'models': [{'slug': 'x'}]},
                 {'models': [{'slug': 'x', 'display_name': 'X'},
                             {'slug': 'x', 'display_name': 'X'}]})
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

    def test_models_route_adds_unknown_subscription_and_updates_routing(self):
        state = {'port': 1, 'token': 'router-token', 'openai_models': ['gpt-6-astra']}
        server = SimpleNamespace(state=state, _subscription_snapshot=None)
        sent = {}

        handler = SimpleNamespace(
            headers={'Authorization': 'Bearer client'}, server=server,
            send_json=lambda status, payload: sent.update(
                status=status, payload=payload))

        rows = ({'slug': 'gpt-new', 'display_name': 'GPT-New'},)
        with mock.patch.object(subscription_discovery, 'fetch_native',
                               return_value=rows):
            subscription_discovery.serve(handler, 'client_version=0.155.0')
        self.assertEqual(sent['status'], 200)
        self.assertIn('gpt-new', state['openai_models'])
        self.assertIn('gpt-new', {row['slug'] for row in sent['payload']['models']})


if __name__ == '__main__':
    unittest.main()
