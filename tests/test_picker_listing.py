"""What the Codex picker lists: subscription rows and their OpenRouter twins.

The subscription picker gate (0.6.83 to 0.6.88) hid an exhausted row and put
its twin in its place. That is withdrawn: every subscription row is listed,
the twin is listed beside it, and a leftover gate document changes nothing.
"""
import json
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from ai_router.catalogue import check, merge, merge_file
from ai_router import subscription_discovery


def _home(tmp, mode='subscription', roster=('gpt-6-luna',)):
    home = Path(tmp)
    (home / 'mixed-router-state.json').write_text(json.dumps(
        {'port': 1, 'token': 't', 'openai_models': list(roster),
         'openai_mode': mode}) + '\n')
    return home


class PickerListingTests(unittest.TestCase):
    def test_a_subscription_row_lists_beside_its_twin(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = _home(tmp)
            merged = merge_file(home / 'mixed-models.json')
            slugs = [m['slug'] for m in merged['models']]
            self.assertIn('gpt-6-luna', slugs)
            self.assertIn('openai/gpt-6-luna', slugs)
            self.assertTrue(check(str(home / 'mixed-models.json')))

    def test_none_mode_lists_the_twin_without_the_subscription_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = _home(tmp, mode='none')
            merged = merge_file(home / 'mixed-models.json')
            slugs = [m['slug'] for m in merged['models']]
            self.assertNotIn('gpt-6-luna', slugs)
            self.assertIn('openai/gpt-6-luna', slugs)
            self.assertTrue(check(str(home / 'mixed-models.json'), include_twins=True))

    def test_a_leftover_gate_document_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = _home(tmp)
            (home / 'subscription-gate.json').write_text(json.dumps(
                {'gpt-6-luna': {'source': 'headers', 'until': 2 ** 31 - 1,
                                  'probed': 0, 'since': 0}}) + '\n')
            merged = merge_file(home / 'mixed-models.json')
            slugs = [m['slug'] for m in merged['models']]
            self.assertIn('gpt-6-luna', slugs)
            self.assertIn('openai/gpt-6-luna', slugs)

    def test_legacy_luna_is_migrated_but_not_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = _home(tmp, roster=('gpt-5.6-luna',))
            merged = merge_file(home / 'mixed-models.json')
            slugs = [m['slug'] for m in merged['models']]
            self.assertIn('gpt-6-luna', slugs)
            self.assertIn('openai/gpt-6-luna', slugs)
            self.assertNotIn('gpt-5.6-luna', slugs)
            self.assertNotIn('openai/gpt-5.6-luna', slugs)

    def test_unknown_native_model_does_not_invent_an_openrouter_twin(self):
        merged = merge({'models': []}, roster=('gpt-future',),
                       subscription_rows=({'slug': 'gpt-future',
                                           'display_name': 'GPT-Future'},))
        slugs = {m['slug'] for m in merged['models']}
        self.assertIn('gpt-future', slugs)
        self.assertNotIn('openai/gpt-future', slugs)

    def test_authentication_rejection_clears_all_versions_for_one_account(self):
        headers = {'Authorization': 'Bearer client', 'ChatGPT-Account-ID': 'a'}
        routing = subscription_discovery._routing_identity(headers)
        server = SimpleNamespace(state={'openai_models': []},
                                 _subscription_snapshots={})
        for version in ('1', '2'):
            subscription_discovery._publish(
                server, (), ('gpt-' + version,),
                subscription_discovery._identity(headers, version), routing,
                subscription_discovery._auth_identity(headers), version)
        subscription_discovery._drop_scope(server, headers)
        self.assertEqual(server._subscription_snapshots, {})

    def test_authentication_rejection_does_not_clear_other_auth_only_clients(self):
        first = {'Authorization': 'Bearer one'}
        second = {'Authorization': 'Bearer two'}
        server = SimpleNamespace(state={'openai_models': []},
                                 _subscription_snapshots={})
        for headers, slug in ((first, 'gpt-one'), (second, 'gpt-two')):
            subscription_discovery._publish(
                server, (), (slug,), subscription_discovery._identity(headers, '1'),
                '', subscription_discovery._auth_identity(headers), '1')
        subscription_discovery._drop_scope(server, first)
        remaining = list(server._subscription_snapshots.values())
        self.assertEqual([entry['roster'] for entry in remaining], [('gpt-two',)])

    def test_auth_only_request_refuses_multiple_account_scopes(self):
        headers = {'Authorization': 'Bearer shared'}
        server = SimpleNamespace(state={'openai_models': ['gpt-static']},
                                 _subscription_snapshots={})
        for account in ('a', 'b'):
            account_headers = dict(headers, **{'ChatGPT-Account-ID': account})
            subscription_discovery._publish(
                server, (), ('gpt-' + account,),
                subscription_discovery._identity(account_headers, '1'),
                subscription_discovery._routing_identity(account_headers),
                subscription_discovery._auth_identity(headers), '1')
        self.assertEqual(subscription_discovery.request_models(server, headers),
                         ('gpt-static',))

    def test_transient_failure_cannot_resurrect_a_rejected_snapshot(self):
        headers = {'Authorization': 'Bearer client'}
        server = SimpleNamespace(state={'openai_models': ['gpt-static']},
                                 _subscription_snapshots={})
        identity = subscription_discovery._identity(headers, '1')
        subscription_discovery._publish(
            server, (), ('gpt-live',), identity, '',
            subscription_discovery._auth_identity(headers), '1')
        entered, auth_done = threading.Barrier(2), threading.Event()
        sent = {}

        def fetch(*args, **kwargs):
            entered.wait()
            if threading.current_thread().name == 'auth':
                raise urllib.error.HTTPError('https://x', 401, 'Denied', {}, None)
            auth_done.wait()
            raise ValueError('offline')

        def handler():
            return SimpleNamespace(
                headers=headers, server=server,
                send_json=lambda status, payload: sent.update(status=status),
                error=lambda error: sent.update(error=error))

        def auth_request():
            subscription_discovery.serve(handler(), 'client_version=1')
            auth_done.set()

        with mock.patch.object(subscription_discovery, 'fetch_native', fetch):
            transient = threading.Thread(target=subscription_discovery.serve,
                                         args=(handler(), 'client_version=1'),
                                         name='transient')
            auth = threading.Thread(target=auth_request, name='auth')
            transient.start(); auth.start()
            transient.join(); auth.join()
        self.assertEqual(sent['error'].status, 503)
        self.assertNotIn('status', sent)

    def test_old_success_cannot_republish_an_invalidated_snapshot(self):
        headers = {'Authorization': 'Bearer client'}
        server = SimpleNamespace(state={'openai_models': []},
                                 _subscription_snapshots={})
        scope, generation = subscription_discovery._scope_generation(headers)
        subscription_discovery._drop_scope(server, headers)
        self.assertFalse(subscription_discovery._publish(
            server, (), ('gpt-live',), 'id', '',
            subscription_discovery._auth_identity(headers), '1',
            scope=scope, generation=generation))
        self.assertEqual(server._subscription_snapshots, {})

    def test_old_fallback_cannot_send_after_concurrent_auth_rejection(self):
        headers = {'Authorization': 'Bearer client'}
        server = SimpleNamespace(state={'openai_models': ['gpt-static']},
                                 _subscription_snapshots={})
        subscription_discovery._publish(
            server, (), ('gpt-live',), subscription_discovery._identity(headers, '1'),
            '', subscription_discovery._auth_identity(headers), '1')
        merged, auth_done = threading.Event(), threading.Event()
        sent = {}

        def fetch(*args, **kwargs):
            if threading.current_thread().name == 'auth':
                raise urllib.error.HTTPError('https://x', 401, 'Denied', {}, None)
            raise ValueError('offline')

        def merge(*args, **kwargs):
            merged.set(); auth_done.wait()
            return {'models': []}

        def handler():
            return SimpleNamespace(headers=headers, server=server,
                send_json=lambda status, payload: sent.update(status=status),
                error=lambda error: sent.update(error=error))

        def auth_request():
            subscription_discovery.serve(handler(), 'client_version=1')
            auth_done.set()

        with mock.patch.object(subscription_discovery, 'fetch_native', fetch), \
                mock.patch.object(subscription_discovery.catalogue, 'merge', merge):
            transient = threading.Thread(target=subscription_discovery.serve,
                                         args=(handler(), 'client_version=1'))
            auth = threading.Thread(target=auth_request, name='auth')
            transient.start(); merged.wait(); auth.start(); auth.join()
            transient.join()
        self.assertEqual(sent['error'].status, 401)
        self.assertNotIn('status', sent)

    def test_subscription_order_overrides_native_priority(self):
        native = ({'slug': 'gpt-6-luna', 'display_name': 'GPT-6-Luna',
                   'priority': 900},)
        merged = merge({'models': []},
                       roster=('gpt-6-sol', 'gpt-6-luna'),
                       subscription_rows=native)
        subscription = [row for row in merged['models']
                        if row['slug'] in ('gpt-6-sol', 'gpt-6-luna')]
        self.assertEqual([row['slug'] for row in subscription],
                         ['gpt-6-sol', 'gpt-6-luna'])
        self.assertEqual([row['priority'] for row in subscription], [1, 2])


if __name__ == '__main__':
    unittest.main()
