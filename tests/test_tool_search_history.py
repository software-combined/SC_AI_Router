"""Discovery calls keep native item IDs when adapted and replayed."""
import copy
import json
import unittest

from ai_router.history_items import repair_call_id
from ai_router.providers import SubscriptionProvider
from ai_router.tool_adapter import SEARCH_NAME, ToolEvents


def discovery_pair(item_id='fc_synthetic_search'):
    return [
        {'type': 'tool_search_call', 'id': item_id, 'call_id': 'search_1',
         'execution': 'client', 'status': 'completed', 'arguments': {'query': 'echo'}},
        {'type': 'tool_search_output', 'id': 'tso_synthetic_search', 'call_id': 'search_1',
         'execution': 'client', 'status': 'completed', 'tools': [
             {'type': 'function', 'name': 'echo', 'parameters': {'type': 'object'},
              'strict': False}]},
    ]


class ToolSearchHistoryTests(unittest.TestCase):
    def test_adaptation_assigns_the_search_item_prefix_on_every_output_frame(self):
        for event_type in ('response.output_item.added', 'response.output_item.done',
                           'response.completed'):
            with self.subTest(event=event_type):
                call = {'type': 'function_call', 'id': 'fc_synthetic_search',
                        'call_id': 'search_1', 'name': SEARCH_NAME,
                        'arguments': '{"query":"echo"}'}
                adapter = ToolEvents({(None, SEARCH_NAME): 'search'})
                event = ({'type': event_type, 'response': {'output': [call]}}
                         if event_type == 'response.completed'
                         else {'type': event_type, 'item': call})
                adapted = adapter.event(event)
                item = (adapted['response']['output'][0] if 'response' in adapted
                        else adapted['item'])
                self.assertEqual(item['type'], 'tool_search_call')
                self.assertEqual(item['id'], 'tsc_synthetic_search')
                self.assertEqual(item['call_id'], 'search_1')

    def test_saved_discovery_replays_with_tools_and_results_intact(self):
        marker = {'type': 'message', 'role': 'developer', 'content': [
            {'type': 'input_text', 'text': '<model_switch> Synthetic model switch.'}]}
        tool_run = [
            {'type': 'function_call', 'id': 'fc_synthetic_echo', 'name': 'echo',
             'call_id': 'echo_1', 'arguments': '{}'},
            {'type': 'function_call_output', 'call_id': 'echo_1', 'output': 'SYNTHETIC_OK'},
        ]
        for path in ('/responses', '/responses/compact'):
            for switched in (False, True):
                with self.subTest(path=path, switched=switched):
                    pair = discovery_pair()
                    items = pair + tool_run + ([marker] if switched else [])
                    payload = {'model': 'gpt-6-luna', 'input': items}
                    original = copy.deepcopy(payload)
                    prepared = SubscriptionProvider().prepare(
                        payload['model'], path, payload, json.dumps(payload).encode(), {}, None)
                    sent = json.loads(prepared.body)['input']
                    self.assertEqual(sent, [{**pair[0], 'id': 'tsc_synthetic_search'},
                                            *items[1:]])
                    self.assertEqual(payload, original)

    def test_correct_native_ids_keep_the_original_wire_bytes(self):
        payload = {'model': 'gpt-6-luna', 'input': discovery_pair('tsc_synthetic_search')}
        raw = json.dumps(payload, indent=2).encode()
        prepared = SubscriptionProvider().prepare(
            payload['model'], '/responses', payload, raw, {}, None)
        self.assertEqual(prepared.body, raw)

    def test_id_repair_is_narrow_pure_and_idempotent(self):
        for kind, prefix in (('tool_search_call', 'tsc_'), ('custom_tool_call', 'ctc_')):
            with self.subTest(kind=kind):
                item = {'type': kind, 'id': 'fc_synthetic', 'call_id': 'same_call'}
                original = copy.deepcopy(item)
                repaired = repair_call_id(item)
                self.assertEqual(repaired, {**item, 'id': prefix + 'synthetic'})
                self.assertEqual(item, original)
                self.assertIs(repair_call_id(repaired), repaired)
        for item in (None, {}, {'type': 'function_call', 'id': 'fc_synthetic'},
                     {'type': 'tool_search_output', 'id': 'fc_synthetic'},
                     {'type': 'tool_search_call'}, {'type': 'tool_search_call', 'id': None},
                     {'type': 'tool_search_call', 'id': 'other_synthetic'}):
            with self.subTest(item=item):
                self.assertIs(repair_call_id(item), item)


if __name__ == '__main__':
    unittest.main()
