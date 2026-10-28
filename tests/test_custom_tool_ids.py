"""Custom calls keep their own item family across response and history replay."""
import copy
import io
import json
import unittest
from compression import zstd

from ai_router import providers, subscription_history, upstream
from ai_router.tool_adapter import ToolEvents, stream_events


def custom_call(ident='fc_tmp_synthetic'):
    return {'type': 'custom_tool_call', 'id': ident, 'call_id': 'call-synthetic',
            'namespace': 'functions', 'name': 'exec', 'input': 'synthetic input',
            'status': 'completed'}


class CustomToolIdTests(unittest.TestCase):
    def test_response_conversion_repairs_only_the_custom_item_id(self):
        original = custom_call()
        original.update(type='function_call', arguments='{"input":"synthetic input"}')
        original.pop('input')
        item = ToolEvents({('functions', 'exec'): 'custom'}).item(copy.deepcopy(original))
        self.assertEqual(item, custom_call('ctc_tmp_synthetic'))

    def test_stream_item_ids_agree_and_raw_argument_frames_stay_suppressed(self):
        item = {'type': 'function_call', 'id': 'fc_tmp_synthetic',
                'call_id': 'call-synthetic', 'name': 'exec',
                'arguments': '{"input":"synthetic input"}'}
        events = [
            {'type': 'response.output_item.added', 'item': {**item, 'arguments': ''}},
            {'type': 'response.function_call_arguments.delta',
             'item_id': item['id'], 'delta': item['arguments']},
            {'type': 'response.function_call_arguments.done',
             'item_id': item['id'], 'arguments': item['arguments']},
            {'type': 'response.output_item.done', 'item': item},
            {'type': 'response.completed', 'response': {'output': [item]}},
        ]
        wire = b''.join(b'data: ' + json.dumps(event).encode() + b'\n\n' for event in events)
        emitted = [json.loads(frame[6:]) for frame in
                   stream_events(io.BytesIO(wire), {(None, 'exec'): 'custom'})]
        self.assertEqual(len(emitted), 3)
        calls = [emitted[0]['item'], emitted[1]['item'],
                 emitted[2]['response']['output'][0]]
        self.assertEqual([call['id'] for call in calls], ['ctc_tmp_synthetic'] * 3)
        self.assertTrue(all(call['call_id'] == item['call_id'] for call in calls))
        self.assertNotIn('fc_tmp_synthetic', json.dumps(emitted))

    def test_legacy_history_repairs_without_a_switch_and_leaves_input_unchanged(self):
        item = custom_call()
        payload = {'input': [item]}
        before = copy.deepcopy(payload)
        result = subscription_history.normalize(payload)
        self.assertEqual(result['input'], [custom_call('ctc_tmp_synthetic')])
        self.assertEqual(payload, before)
        self.assertIs(subscription_history.normalize(result), result)

    def test_mixed_history_preserves_other_ids_pairs_and_declarations(self):
        function = {'type': 'function_call', 'id': 'fc_function',
                    'call_id': 'call-function', 'name': 'echo', 'arguments': '{}'}
        output = {'type': 'function_call_output', 'id': 'fco_function',
                  'call_id': 'call-function', 'output': 'marker'}
        custom_output = {'type': 'custom_tool_call_output', 'id': 'ctco_result',
                         'call_id': 'call-synthetic', 'output': 'marker'}
        declaration = {'type': 'additional_tools', 'role': 'developer',
                       'id': 'at_synthetic', 'tools': []}
        native = custom_call('ctc_native')
        items = [declaration, function, output, custom_call(), custom_output,
                 {'type': 'message', 'role': 'developer', 'content': '<model_switch>'}, native]
        result = subscription_history.normalize({'input': items})['input']
        self.assertEqual(len(result), len(items))
        self.assertEqual(result[3], custom_call('ctc_tmp_synthetic'))
        for index in (0, 1, 2, 4, 5, 6):
            self.assertIs(result[index], items[index])

    def test_valid_missing_and_unmeasured_ids_remain_unchanged(self):
        missing = custom_call()
        missing.pop('id')
        for item in (custom_call('ctc_native'), custom_call('other_synthetic'), missing,
                     {'type': 'function_call', 'id': 'fc_function'}, None):
            with self.subTest(item=item):
                payload = {'input': [item]}
                self.assertIs(subscription_history.normalize(payload), payload)

    def test_both_subscription_paths_reencode_compressed_legacy_history(self):
        payload = {'model': 'gpt-6.1-sol', 'input': [custom_call()]}
        raw = zstd.compress(json.dumps(payload).encode())
        for path in ('/responses', '/responses/compact'):
            with self.subTest(path=path):
                prepared = providers.SubscriptionProvider().prepare(
                    payload['model'], path, payload, raw,
                    {'Content-Encoding': 'zstd', 'Accept-Encoding': 'zstd'}, None)
                sent = json.loads(prepared.body)
                self.assertEqual(sent['input'][0]['id'], 'ctc_tmp_synthetic')
                self.assertNotIn('Content-Encoding', prepared.headers)
                self.assertEqual(prepared.headers['Accept-Encoding'], 'identity')
                self.assertEqual(payload['input'][0]['id'], 'fc_tmp_synthetic')

    def test_safe_id_parameter_is_exact_and_keeps_existing_limits(self):
        for param in ('input[0].id', 'input[600].id', 'input[999999].id'):
            body = json.dumps({'error': {'param': param}})
            for raw in (body, json.dumps({'error': {'metadata': {'raw': body}}})):
                with self.subTest(param=param):
                    self.assertEqual(upstream.rejection_parameter(raw), param)
        for param in ('tools[0].id', 'input.id', 'input[0].content.id',
                      'input[0].identifier', 'input[0].id\n', 'input[1000000].id',
                      'input[0].id PRIVATE-CANARY'):
            with self.subTest(param=param):
                self.assertIsNone(upstream.rejection_parameter(json.dumps({'error': {'param': param}})))


if __name__ == '__main__':
    unittest.main()
