"""Plan 183: each Responses route runs one named stage list, in this order.

A reorder, an added stage or a dropped one is a visible edit here, reviewed
against the goldens. Stage modules never resolve a row themselves: the
adapter passes the request's captured row in.
"""
import copy
import json
import unittest

from ai_router import external_history, outbound, provider_defs, tool_adapter, tool_history
from ai_router.providers import ExternalResponsesProvider
from tests.harness import stub_credentials


def _names(stages):
    return [stage.__name__ for stage in stages]


class StageOrderTests(unittest.TestCase):
    def test_external_stage_order(self):
        self.assertEqual(_names(outbound.EXTERNAL_STAGES), [
            'refuse_opaque_briefs', 'recover_context', 'materialize_standalone',
            'scrub_fragments', 'declare_tools',
            'rewrite_history', 'compaction_text', 'strip_reasoning', 'note_media',
            'check_effort', 'drop_native_fields', 'upstream_model', 'output_cap'])

    def test_subscription_stage_order(self):
        self.assertEqual(_names(outbound.SUBSCRIPTION_STAGES), [
            'replay_boundary', 'replay_reasoning', 'recover_context', 'hint_handoffs'])
        self.assertEqual(outbound.SUBSCRIPTION_STAGES[:2], outbound.SUBSCRIPTION_REPLAY)

    def test_stage_modules_hold_no_registry_lookup(self):
        for module in (outbound, tool_adapter, tool_history):
            with self.subTest(module=module.__name__):
                self.assertFalse(hasattr(module, 'by_slug'))


class RetryReasoningTests(unittest.TestCase):
    def history(self):
        return [
            {'type': 'message', 'role': 'user', 'content': 'Inspect the synthetic file.'},
            {'type': 'reasoning', 'id': 'rs_before_call', 'summary': [],
             'content': [{'type': 'reasoning_text', 'text': 'Read the file first.'}]},
            {'type': 'function_call', 'name': 'read_file', 'call_id': 'c1', 'arguments': '{}'},
            {'type': 'function_call_output', 'call_id': 'c1', 'output': 'synthetic result'},
        ]

    def wire(self, items):
        payload = {'model': 'anthropic/claude-opus-5.5', 'input': items,
                   'tools': [{'type': 'function', 'name': 'read_file',
                              'parameters': {'type': 'object'}}]}
        original = copy.deepcopy(payload)
        prepared = ExternalResponsesProvider(provider_defs.OPENROUTER).prepare(
            payload['model'], '/responses', payload, b'', {}, stub_credentials())
        self.assertEqual(payload, original)
        return json.loads(prepared.body)

    def test_cutoff_retry_drops_only_trailing_reasoning(self):
        history = self.history()
        tail = [{'type': 'reasoning', 'id': 'rs_cutoff', 'summary': [],
                 'content': [{'type': 'reasoning_text', 'text': 'Unfinished analysis.'}]},
                {'type': 'reasoning', 'id': 'rs_cutoff_2', 'summary': [],
                 'content': [{'type': 'reasoning_text', 'text': 'Still unfinished.'}]},
                {'type': 'reasoning', 'id': 'rs_blob', 'encrypted_content': 'synthetic'}]
        self.assertEqual(self.wire(history + tail)['input'], history)

    def test_continue_and_assistant_reply_keep_preceding_reasoning(self):
        reasoning = self.history()[1]
        for role in ('user', 'assistant'):
            with self.subTest(role=role):
                items = self.history() + [reasoning, {'type': 'message', 'role': role,
                                                      'content': 'Continue.'}]
                self.assertEqual(self.wire(items)['input'], items)

    def test_subscription_and_blob_retry_keep_readable_reasoning_tail(self):
        items = self.history() + [dict(self.history()[1], id='rs_tail')]
        items = [{**item, 'encrypted_content': 'synthetic'}
                 if item['type'] == 'reasoning' else item for item in items]
        native = self.history()[:1] + self.history()[2:] + [
            {'type': 'reasoning', 'id': 'rs_tail', 'summary': [],
             'encrypted_content': 'synthetic'}]
        payload = {'model': 'gpt-6-astra', 'input': native}
        projected, _, _ = outbound.project_subscription(payload, '/responses')
        self.assertEqual(projected['input'], native)
        stripped = external_history.strip_reasoning_blobs(items)
        self.assertEqual(stripped[-1], dict(self.history()[1], id='rs_tail'))


if __name__ == '__main__':
    unittest.main()
