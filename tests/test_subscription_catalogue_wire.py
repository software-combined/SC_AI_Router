"""Native Codex metadata must survive discovery and the combined picker."""
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from ai_router import availability, providers, subscription_catalogue, subscription_discovery
from tests.test_subscription_discovery import _Response


class NativeCatalogueWireTests(unittest.TestCase):
    def test_post_version_header_selects_the_discovered_roster_after_upgrade(self):
        server = SimpleNamespace(state={'openai_models': ['gpt-static']},
                                 _subscription_snapshots={})
        sent = {}
        headers = {'Authorization': 'Bearer synthetic-client', 'ChatGPT-Account-ID': 'a'}
        handler = SimpleNamespace(
            headers=headers, server=server,
            send_json=lambda status, payload: sent.update(status=status, payload=payload),
            error=lambda error: sent.update(error=error))
        for version, model in (('0.158.0', 'gpt-6-sol'), ('0.159.2', 'gpt-6.1-sol')):
            native = ({'slug': model, 'display_name': model},)
            with mock.patch.object(subscription_discovery, 'fetch_native', return_value=native), \
                    mock.patch.object(availability, 'combined_ids', return_value=None):
                subscription_discovery.serve(handler, 'client_version=' + version)
            self.assertEqual(sent.get('status'), 200)
        self.assertIn('gpt-6.1-sol', {row['slug'] for row in sent['payload']['models']})
        for header in ('version', 'Version'):
            with self.subTest(header=header):
                request_headers = {**headers, header: '0.159.2'}
                roster = subscription_discovery.request_models(server, request_headers)
                self.assertEqual(roster, ('gpt-6.1-sol',))
                self.assertEqual(providers.select('gpt-6.1-sol', '/responses', roster).name,
                                 'openai')
                self.assertEqual(subscription_discovery.request_models(
                    server, request_headers, 'client_version=0.158.0'), ('gpt-6-sol',))
        self.assertEqual(subscription_discovery.request_models(server, headers), ('gpt-static',))

    def test_live_models_override_static_retirement_without_changing_routes(self):
        levels = [{'effort': 'low', 'description': 'Low'}]
        native = {'models': [
            {'slug': 'gpt-6.1-sol', 'display_name': 'GPT-6.1-Sol'},
            {'slug': 'gpt-5.6-sol', 'display_name': 'GPT-5.6-Sol',
             'default_reasoning_level': 'low', 'supported_reasoning_levels': levels},
            {'slug': 'gpt-5.6-luna', 'display_name': 'GPT-5.6-Luna'},
            {'slug': 'gpt-reserve', 'display_name': 'Reserve', 'visibility': 'hide'},
        ]}
        allowed = ['openai/gpt-6.1-sol']
        state = {'token': 'synthetic-token', 'allowed_models': allowed,
                 'openai_models': ['gpt-6-sol', 'gpt-6-luna', 'gpt-static']}
        server = SimpleNamespace(state=state, _subscription_snapshots={})
        sent = {}
        handler = SimpleNamespace(
            headers={'Authorization': 'Bearer synthetic-client'}, server=server,
            send_json=lambda status, payload: sent.update(status=status, payload=payload),
            error=lambda error: sent.update(error=error))
        with mock.patch.object(subscription_discovery, '_open_without_redirects',
                               return_value=_Response(json.dumps(native).encode())), \
                mock.patch.object(availability, 'combined_ids', return_value=None):
            subscription_discovery.serve(handler, 'client_version=0.159.2')
            self.assertEqual(sent.get('status'), 200)
            rows = {row['slug']: row for row in sent['payload']['models']}
            roster = subscription_discovery.request_models(
                server, handler.headers, 'client_version=0.159.2')
            self.assertEqual(set(roster), {row['slug'] for row in native['models']})
            self.assertEqual(set(rows), set(roster) | set(allowed))
            for row in native['models']:
                with self.subTest(slug=row['slug']):
                    for key, value in row.items():
                        self.assertEqual(rows[row['slug']][key], value)
                    self.assertEqual(providers.select(
                        row['slug'], '/responses', roster, allowed=allowed).name,
                        'openai')
            self.assertEqual(providers.select(
                allowed[0], '/responses', roster, allowed=allowed).name, 'openrouter')

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
                mock.patch.object(availability, 'combined_ids', return_value=None):
            subscription_discovery.serve(handler, 'client_version=0.155.0')
        self.assertEqual(sent.get('status'), 200)
        rows = {row['slug']: row for row in sent['payload']['models']}
        self.assertIn('gpt-new', rows)
        self.assertIn('deepseek/deepseek-v4.1-flash-1017', rows)
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
