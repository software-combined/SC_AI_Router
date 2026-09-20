"""Codex enrolment metadata belongs only to the subscription request."""
import copy
import json
import unittest

from ai_router import provider_defs, providers
from tests.harness import StubCredentials


class AccessProgramBoundaryTests(unittest.TestCase):
    def payload(self, model):
        return {'model': model, 'access_programs': {'cyber': True},
                'input': [{'role': 'user', 'content': 'Read the version.'}],
                'reasoning': {'effort': 'high'}, 'parallel_tool_calls': True,
                'tools': [{'type': 'function', 'name': 'read_version',
                           'parameters': {'type': 'object', 'properties': {}}}]}

    def test_muse_first_turn_and_tool_continuation_omit_subscription_metadata(self):
        for model in ('meta/muse-spark-1.3', 'meta/muse-spark-1.3-contributor'):
            payload = self.payload(model)
            for continuation in (False, True):
                with self.subTest(model=model, continuation=continuation):
                    if continuation:
                        payload['input'].extend([
                            {'type': 'function_call', 'name': 'read_version',
                             'call_id': 'call_1', 'arguments': '{}'},
                            {'type': 'function_call_output', 'call_id': 'call_1',
                             'output': '0.6.98'}])
                    prepared = providers.ExternalResponsesProvider(
                        provider_defs.OPENROUTER).prepare(
                            model, '/responses', copy.deepcopy(payload), b'',
                            {'Authorization': 'Bearer subscription-only'}, StubCredentials())
                    wire = json.loads(prepared.body)
                    self.assertNotIn('access_programs', wire)
                    for field in ('model', 'reasoning', 'tools', 'input', 'parallel_tool_calls'):
                        self.assertEqual(wire[field], payload[field])
                    self.assertNotIn('subscription-only', json.dumps(prepared.headers))

    def test_subscription_preserves_access_programs(self):
        payload = self.payload('gpt-6-astra')
        raw = json.dumps(payload).encode()
        prepared = providers.SubscriptionProvider().prepare(
            'gpt-6-astra', '/responses', payload, raw,
            {'Authorization': 'Bearer subscription-only'}, StubCredentials())
        self.assertEqual(json.loads(prepared.body)['access_programs'], {'cyber': True})
        self.assertEqual(prepared.headers['Authorization'], 'Bearer subscription-only')
