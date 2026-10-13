"""AWS Bedrock (Mantle) provider: definition, routing and isolation.

The offline proof uses the shared route harness with simulated upstreams:
a Bedrock row must reach the regional Mantle host with its own key and
exact upstream id, on its declared protocol only, and must never fall
back to another provider or region. Live acceptance stays a separate
candidate-probe gate.
"""
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from ai_router import availability, claude, provider_defs, providers, registry
from tests.model_route_fixtures import RouteHarness, payload, success

CLAUDE_ROW = 'bedrock/anthropic.claude-sonnet-5'
RESPONSES_ROW = 'bedrock/openai.gpt-oss-120b'
MANTLE = 'bedrock-mantle.us-east-1.api.aws'


class BedrockDefinitionTests(unittest.TestCase):
    def test_definition_and_hosts(self):
        defn = provider_defs.BEDROCK
        self.assertEqual((defn.id, defn.label, defn.kind),
                         ('bedrock', 'AWS Bedrock', 'external'))
        self.assertEqual(defn.dialect, provider_defs.DIALECT_OPENAI_COMPATIBLE)
        self.assertIn(defn.dialect, provider_defs.EXTERNAL_DIALECTS)
        self.assertEqual(defn.path_for(provider_defs.RESPONSES, '/responses'),
                         '/v1/responses')
        self.assertEqual(defn.path_for(provider_defs.MESSAGES, '/v1/messages'),
                         '/anthropic/v1/messages')
        self.assertFalse(defn.serves(provider_defs.IMAGES))
        self.assertFalse(defn.serves(provider_defs.VIDEOS))
        self.assertEqual((defn.key.env, defn.key.file, defn.key.state_key),
                         ('BEDROCK_API_KEY', 'bedrock.key', None))
        self.assertFalse(defn.required)
        self.assertTrue(provider_defs.OPENROUTER.required)
        self.assertEqual(provider_defs.host_for('bedrock', 'ap-southeast-2'),
                         'bedrock-mantle.ap-southeast-2.api.aws')
        self.assertIsNone(provider_defs.host_for('bedrock', 'not a region'))
        self.assertEqual(provider_defs.host_for('openrouter', 'eu'),
                         'eu.openrouter.ai')

    def test_region_shape(self):
        for good in ('us-east-1', 'ap-southeast-2', 'eu-west-1'):
            self.assertTrue(provider_defs.valid_bedrock_region(good), good)
        for bad in ('US-EAST-1', 'us_east_1', '', 'a1', 'x-', None, 7):
            self.assertFalse(provider_defs.valid_bedrock_region(bad), bad)

    def test_rows_carry_one_protocol_each(self):
        for slug, protocol in ((CLAUDE_ROW, 'messages'),
                               (RESPONSES_ROW, 'responses')):
            row = registry.by_slug(slug)
            self.assertIsNotNone(row, slug)
            self.assertEqual(row.provider, 'bedrock')
            self.assertEqual(row.tier, 'preview')
            self.assertFalse(row.listed)
            self.assertTrue(registry.row_serves(row, protocol))
            other = 'responses' if protocol == 'messages' else 'messages'
            self.assertFalse(registry.row_serves(row, other))


class BedrockRouteTests(unittest.TestCase):
    def setUp(self):
        self.harness = RouteHarness(self)
        self._snaps = dict(availability._SNAPSHOTS)
        self._had = set(availability._HAD_SNAPSHOT)
        self.addCleanup(availability._SNAPSHOTS.update, self._snaps)
        self.addCleanup(availability._SNAPSHOTS.clear)
        availability._SNAPSHOTS.clear()
        availability._HAD_SNAPSHOT.clear()

    def test_responses_row_reaches_mantle_with_bearer_key(self):
        row = registry.by_slug(RESPONSES_ROW)
        status, _wire, sends, _facts = self.harness.turn(
            payload(RESPONSES_ROW, 'responses', row.default_reasoning),
            'responses', [success(row.upstream_id, 'responses')])
        self.assertEqual(status, 200)
        host, _method, path = sends[0][:3]
        self.assertEqual((host, path), (MANTLE, '/v1/responses'))
        headers = {k.lower(): v for k, v in sends[0][4].items()}
        self.assertEqual(headers['authorization'], 'Bearer test-key')
        self.assertNotIn('x-api-key', headers)
        self.assertEqual(json.loads(sends[0][3])['model'], row.upstream_id)

    def test_messages_row_reaches_mantle_with_api_key_header(self):
        row = registry.by_slug(CLAUDE_ROW)
        status, _wire, sends, _facts = self.harness.turn(
            payload(CLAUDE_ROW, 'messages', row.default_reasoning),
            'messages', [success(row.upstream_id, 'messages')])
        self.assertEqual(status, 200)
        host, _method, path = sends[0][:3]
        self.assertEqual((host, path), (MANTLE, '/anthropic/v1/messages'))
        headers = {k.lower(): v for k, v in sends[0][4].items()}
        self.assertEqual(headers['x-api-key'], 'test-key')
        self.assertEqual(headers['anthropic-version'], '2023-06-01')
        self.assertNotIn('authorization', headers)

    def test_cross_protocol_rows_refuse_before_a_send(self):
        status, _w, sends, _f = self.harness.turn(
            payload(CLAUDE_ROW, 'responses', 'none'), 'responses', [],
            sent=False, projected=False)
        self.assertEqual((status, sends), (400, []))
        status, _w, sends, _f = self.harness.turn(
            payload(RESPONSES_ROW, 'messages', 'low'), 'messages', [],
            sent=False, projected=False)
        self.assertEqual((status, sends), (409, []))

    def test_availability_gates_each_provider_alone(self):
        availability._SNAPSHOTS['bedrock'] = {
            'provider': 'bedrock', 'key': 'k', 'region': 'us-east-1',
            'models': frozenset({RESPONSES_ROW}), 'fetched_at': 0}
        provider = providers.select(RESPONSES_ROW, '/responses')
        self.assertEqual((provider.name, provider.host), ('bedrock', MANTLE))
        with self.assertRaises(Exception):
            providers.select(CLAUDE_ROW, '/responses')
        # An OpenRouter snapshot never gates a Bedrock row, and vice versa.
        availability._SNAPSHOTS.clear()
        availability._SNAPSHOTS['openrouter'] = {
            'provider': 'openrouter', 'key': 'k', 'region': 'global',
            'models': frozenset(), 'fetched_at': 0}
        provider = providers.select(RESPONSES_ROW, '/responses')
        self.assertEqual(provider.name, 'bedrock')


class BedrockSetupTests(unittest.TestCase):
    def test_finish_setup_refreshes_the_newly_keyed_provider(self):
        # A provider keyless at startup must join availability when its
        # key is saved, without waiting for a service restart.
        from ai_router import setup as setup_mod
        refreshed = []
        state = {'openai_mode': 'subscription'}
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.object(setup_mod.state_mod, 'read',
                                  return_value=dict(state)), \
                mock.patch.object(setup_mod, '_atomic_replace'), \
                mock.patch('ai_router.availability.current_key',
                           side_effect=lambda home, pid=None: (
                               'bedrock-key' if pid == 'bedrock' else None)), \
                mock.patch('ai_router.availability.refresh',
                           side_effect=lambda pid, host, key, home, region:
                           refreshed.append((pid, host, region)) or
                           {'provider': pid, 'models': frozenset()}):
            self.assertTrue(setup_mod._finish_setup(state, home))
        self.assertEqual(refreshed, [(
            'bedrock', 'bedrock-mantle.us-east-1.api.aws', 'us-east-1')])


class BedrockAvailabilityTests(unittest.TestCase):
    def setUp(self):
        self._snaps = dict(availability._SNAPSHOTS)
        self._had = set(availability._HAD_SNAPSHOT)
        self.addCleanup(availability._SNAPSHOTS.update, self._snaps)
        self.addCleanup(availability._SNAPSHOTS.clear)
        availability._SNAPSHOTS.clear()
        availability._HAD_SNAPSHOT.clear()

    def test_live_ids_map_to_bedrock_slugs_only(self):
        doc = {'data': [{'id': 'anthropic.claude-sonnet-5'},
                        {'id': 'unregistered/model'}]}
        with tempfile.TemporaryDirectory() as tmp:
            snap = availability.refresh(
                'bedrock', MANTLE, 'bedrock-key', tmp, 'us-east-1',
                lambda req, timeout=None: _Resp(doc))
            self.assertEqual(snap['provider'], 'bedrock')
            self.assertEqual(snap['models'], frozenset({CLAUDE_ROW}))
            self.assertTrue((Path(tmp) / 'models-availability-bedrock.json').exists())
            self.assertFalse((Path(tmp) / 'models-availability.json').exists())

    def test_bedrock_auth_rejection_keeps_openrouter_snapshot(self):
        def denied(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 401, 'no', {}, None)
        availability._SNAPSHOTS['openrouter'] = {
            'provider': 'openrouter', 'key': 'k', 'region': 'global',
            'models': frozenset({'z-ai/glm-5.3'}), 'fetched_at': 0}
        availability._HAD_SNAPSHOT.add('openrouter')
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(availability.refresh(
                'bedrock', MANTLE, 'bad-key', tmp, 'us-east-1', denied))
        self.assertIn('openrouter', availability._SNAPSHOTS)
        self.assertNotIn('bedrock', availability._SNAPSHOTS)
        self.assertTrue(availability.permitted('z-ai/glm-5.3',
                                               provider_id='openrouter'))


class _Resp:
    def __init__(self, payload, status=200):
        self.status = status
        self._body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, *args):
        return self._body


if __name__ == '__main__':
    unittest.main()
