"""Native Codex metadata must survive discovery and the combined picker."""
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from ai_router import availability, subscription_catalogue, subscription_discovery
from tests.test_subscription_discovery import _Response


class NativeCatalogueWireTests(unittest.TestCase):
    def test_native_metadata_is_merged_with_third_party_models(self):
        upgrade = {'model': 'gpt-new', 'migration_markdown': 'Try the new model.'}
        native = {'models': [
            {'slug': 'gpt-new', 'display_name': 'GPT New', 'visibility': 'list'},
            {'slug': 'gpt-old', 'display_name': 'GPT Old', 'upgrade': upgrade},
            {'slug': 'gpt-hidden', 'display_name': 'Hidden', 'visibility': 'hide'},
            {'slug': 'gpt-internal', 'display_name': 'Internal', 'visibility': 'none'},
        ]}
        state = {'token': 'synthetic-token', 'openai_models': ['gpt-static']}
        server = SimpleNamespace(state=state, _subscription_snapshots={})
        sent = {}
        handler = SimpleNamespace(
            headers={'Authorization': 'Bearer synthetic-client'}, server=server,
            send_json=lambda status, payload: sent.update(status=status, payload=payload),
            error=lambda error: sent.update(error=error))
        with mock.patch.object(subscription_discovery, '_open_without_redirects',
                               return_value=_Response(json.dumps(native).encode())), \
                mock.patch.object(availability, 'current', return_value=None):
            subscription_discovery.serve(handler, 'client_version=0.155.0')
        self.assertEqual(sent.get('status'), 200)
        rows = {row['slug']: row for row in sent['payload']['models']}
        self.assertIn('gpt-new', rows)
        self.assertIn('deepseek/deepseek-v4.1-flash', rows)
        self.assertNotIn('gpt-static', rows)
        self.assertEqual(rows['gpt-old']['upgrade'], upgrade)
        self.assertEqual(rows['gpt-hidden']['visibility'], 'hide')
        self.assertEqual(rows['gpt-internal']['visibility'], 'none')
        self.assertIn('gpt-new', subscription_discovery.request_models(
            server, handler.headers, 'client_version=0.155.0'))

    def test_legacy_hidden_flag_uses_native_wire_value(self):
        rows = subscription_catalogue.validate({'models': [
            {'slug': 'gpt-hidden', 'display_name': 'Hidden', 'hidden': True}]})
        self.assertEqual(rows[0]['visibility'], 'hide')
        self.assertNotIn('hidden', rows[0])

    def test_malformed_native_metadata_still_fails_closed(self):
        for field in ({'visibility': 'unexpected'}, {'upgrade': 'gpt-new'},
                      {'upgrade': {}}, {'upgrade': {'model': 1, 'migration_markdown': ''}},
                      {'upgrade': {'model': 'gpt-new', 'migration_markdown': []}}):
            with self.subTest(field=field), self.assertRaises(ValueError):
                subscription_catalogue.validate({'models': [
                    {'slug': 'gpt-old', 'display_name': 'GPT Old', **field}]})
