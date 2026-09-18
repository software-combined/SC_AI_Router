"""Trim policy for oversized routed turns: repeated listings, images, outputs.

Slice 2 of the 2026-09-16 rescue: the router serves a turn it can reduce with
visible notes instead of refusing it, and never drops history silently.
"""
import json
import unittest
from unittest import mock

from ai_router import provider_defs, providers, turn_budget
from ai_router.image_items import IMAGE_TRIM_NOTE
from ai_router.registry import by_slug
from ai_router.tool_adapter import SEARCH_REPEAT_NOTE, prepare_tools, stream_events
from ai_router.turn_budget import OUTPUT_TRIM_NOTE, carried_tokens, fit, report_usage
from tests.fakes import FakeUpstream
from tests.harness import stub_credentials as _stub_credentials

MODEL = 'meta/muse-spark-1.3-contributor'


def _search_item(call_id, name='echo'):
    return {'type': 'tool_search_output', 'call_id': call_id, 'status': 'completed',
            'execution': 'client',
            'tools': [{'type': 'namespace', 'name': 'probe', 'description': 'probe tools',
                       'tools': [{'type': 'function', 'name': name,
                                  'description': 'Echo.', 'parameters': {'type': 'object'}}]}]}


def _search_payload(call_ids):
    return {'model': MODEL,
            'tools': [{'type': 'tool_search', 'parameters': {'type': 'object'}}],
            'input': [_search_item(call_id) for call_id in call_ids]}


def _image(text):
    return {'type': 'input_image', 'detail': 'high', 'image_url': 'data:image/png;base64,' + text}


def _image_payload(count):
    return {'model': MODEL,
            'input': [{'type': 'message', 'role': 'user',
                       'content': [{'type': 'input_text', 'text': 'shot %d' % index},
                                   _image('x' * 400)]} for index in range(count)]}


def _output_payload(count, size):
    return {'model': MODEL,
            'input': [{'type': 'function_call', 'call_id': 'c%d' % index,
                       'name': 'shell', 'arguments': '{}'} for index in range(count)]
                    + [{'type': 'function_call_output', 'call_id': 'c%d' % index,
                        'output': 'o' * size} for index in range(count)]}


class RepeatedListingTests(unittest.TestCase):
    def test_repeated_search_results_collapse_to_the_newest_listing(self):
        payload = _search_payload(['s1', 's2', 's3'])
        prepare_tools(payload)
        outputs = [json.loads(item['output']) for item in payload['input']]
        self.assertEqual([item['call_id'] for item in payload['input']],
                         ['s1', 's2', 's3'])
        self.assertEqual(outputs[0]['available_tools'], [SEARCH_REPEAT_NOTE])
        self.assertEqual(outputs[1]['available_tools'], [SEARCH_REPEAT_NOTE])
        self.assertEqual(outputs[2]['available_tools'],
                         [{'name': 'probe__echo', 'description': 'Echo.'}])
        self.assertIn('how_to_use', outputs[2])
        self.assertNotIn('how_to_use', outputs[0])
        # The released tool itself still rides in the request tool list, once.
        self.assertEqual([tool.get('name') for tool in payload['tools']],
                         ['codex_client_tool_search', 'probe__echo'])

    def test_a_distinct_tool_keeps_its_own_listing(self):
        payload = {'model': MODEL,
                   'tools': [{'type': 'tool_search', 'parameters': {'type': 'object'}}],
                   'input': [_search_item('s1'), _search_item('s2', name='other')]}
        prepare_tools(payload)
        outputs = [json.loads(item['output']) for item in payload['input']]
        self.assertEqual(outputs[0]['available_tools'],
                         [{'name': 'probe__echo', 'description': 'Echo.'}])
        self.assertEqual(outputs[1]['available_tools'],
                         [{'name': 'probe__other', 'description': 'Echo.'}])


class FitTests(unittest.TestCase):
    def test_images_past_the_newest_kept_set_are_noted_oldest_first(self):
        payload = _image_payload(6)
        stats = fit(payload, 10)
        blocks = [item['content'][1] for item in payload['input']]
        self.assertEqual(stats['images'], 2)
        self.assertEqual([block['type'] for block in blocks],
                         ['input_text', 'input_text'] + ['input_image'] * 4)
        self.assertEqual([block['text'] for block in blocks[:2]],
                         [IMAGE_TRIM_NOTE, IMAGE_TRIM_NOTE])
        self.assertGreater(stats['dropped_bytes'], 0)

    def test_a_turn_inside_the_budget_is_untouched(self):
        payload = _image_payload(1)
        before = json.dumps(payload)
        self.assertEqual(fit(payload, turn_budget.BODY_BUDGET), {})
        self.assertEqual(json.dumps(payload), before)

    def test_long_old_tool_outputs_are_truncated_head_and_tail(self):
        payload = _output_payload(5, 40 * 1024)
        stats = fit(payload, 10)
        outputs = [item for item in payload['input']
                   if item.get('type') == 'function_call_output']
        self.assertEqual(stats['outputs'], 3)
        for item in outputs[:3]:
            self.assertLess(len(item['output']), 40 * 1024)
            self.assertIn(OUTPUT_TRIM_NOTE, item['output'])
            self.assertTrue(item['output'].startswith('o'))
            self.assertTrue(item['output'].endswith('o'))
        self.assertEqual([len(item['output']) for item in outputs[3:]], [40 * 1024] * 2)

    def test_an_irreducible_body_reports_no_trim(self):
        payload = {'model': MODEL, 'input': [{'type': 'message', 'role': 'user',
                                              'content': [{'type': 'input_text',
                                                           'text': 'x' * 4000}]}]}
        self.assertEqual(fit(payload, 10), {})

    def test_body_size_measures_the_body_the_adapter_sends(self):
        payload = _image_payload(6)
        wire = len(json.dumps(payload).encode())
        self.assertEqual(turn_budget.body_size(payload), wire)
        # The compact form is smaller, so a gate using it would under-trigger.
        self.assertGreater(wire, len(json.dumps(payload, separators=(',', ':')).encode()))
        self.assertEqual(fit(payload, wire), {})
        self.assertEqual(fit(payload, wire - 1)['images'], 2)


class PrepareTrimTests(unittest.TestCase):
    def prepare(self, payload, budget):
        provider = providers.ExternalResponsesProvider(provider_defs.OPENROUTER)
        with mock.patch.object(turn_budget, 'BODY_BUDGET', budget):
            return provider.prepare(MODEL, '/responses', payload,
                                    json.dumps(payload).encode(),
                                    {'Content-Type': 'application/json'},
                                    _stub_credentials())

    def test_an_over_budget_body_is_trimmed_and_logged(self):
        payload = _image_payload(6)
        with mock.patch.object(providers, 'log_event') as logged:
            prepared = self.prepare(payload, 1500)
        body = json.loads(prepared.body)
        blocks = [block for item in body['input'] for block in item['content']]
        self.assertEqual([block['type'] for block in blocks].count('input_image'), 4)
        trimmed = [call for call in logged.call_args_list
                   if call.args and call.args[0] == 'turn_trimmed']
        self.assertEqual(len(trimmed), 1)
        self.assertEqual(trimmed[0].kwargs['images'], 2)
        self.assertEqual(trimmed[0].kwargs['prepared_bytes'], len(prepared.body))

    def test_a_body_inside_the_budget_is_left_alone(self):
        payload = _image_payload(6)
        with mock.patch.object(providers, 'log_event') as logged:
            prepared = self.prepare(payload, turn_budget.BODY_BUDGET)
        self.assertNotIn('turn_trimmed',
                         [call.args[0] for call in logged.call_args_list if call.args])
        self.assertEqual(len(json.loads(prepared.body)['input']), 6)


def _completed(usage):
    event = {'type': 'response.completed',
             'response': {'id': 'r1', 'output': [], 'usage': usage}}
    return b'data: ' + json.dumps(event).encode() + b'\n\n'


class CarriedTokensTests(unittest.TestCase):
    def test_text_weight_uses_the_measured_ratio(self):
        payload = {'model': MODEL, 'input': []}
        self.assertEqual(carried_tokens(payload, 5800), 1000)
        self.assertEqual(carried_tokens(payload, 0), 0)

    def test_image_bytes_ride_the_flat_allowance_not_the_byte_ratio(self):
        payload = _image_payload(1)
        decoded = len(json.dumps(payload).encode())
        images = turn_budget.image_payload_bytes(payload['input'])
        self.assertEqual(carried_tokens(payload, decoded),
                         int((decoded - images) / turn_budget.BYTES_PER_TOKEN) + 1600)


class ReportUsageTests(unittest.TestCase):
    def test_a_carried_figure_raises_the_reported_input_tokens(self):
        usage = {'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15,
                 'input_tokens_details': {'cached_tokens': 3}}
        notes = {'model': MODEL, 'context_tokens': 900}
        with mock.patch.object(turn_budget, 'log_event') as logged:
            self.assertTrue(report_usage(usage, notes))
        self.assertEqual(usage['input_tokens'], 900)
        self.assertEqual(usage['total_tokens'], 905)
        self.assertEqual(usage['input_tokens_details'], {'cached_tokens': 3})
        self.assertEqual(logged.call_args.args[0], 'usage_reported')
        self.assertEqual(logged.call_args.kwargs['reported'], 10)

    def test_a_smaller_or_missing_carried_figure_changes_nothing(self):
        usage = {'input_tokens': 900, 'output_tokens': 5, 'total_tokens': 905}
        self.assertFalse(report_usage(usage, {'context_tokens': 899}))
        self.assertFalse(report_usage(usage, {}))
        self.assertFalse(report_usage(usage, None))
        self.assertEqual(usage['input_tokens'], 900)
        self.assertFalse(report_usage(None, {'context_tokens': 900}))


class UsageOnTheWireTests(unittest.TestCase):
    def test_a_streamed_completed_frame_reports_the_carried_figure(self):
        usage = {'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15}
        response = FakeUpstream(200, _completed(usage),
                                [('Content-Type', 'text/event-stream')])
        notes = {'model': MODEL, 'context_tokens': 900}
        chunks = b''.join(stream_events(response, {}, notes))
        self.assertIn(b'"input_tokens": 900', chunks)
        self.assertIn(b'"total_tokens": 905', chunks)

    def test_a_turn_without_a_carried_figure_keeps_provider_numbers(self):
        usage = {'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15}
        response = FakeUpstream(200, _completed(usage),
                                [('Content-Type', 'text/event-stream')])
        chunks = b''.join(stream_events(response, {}, {'model': MODEL}))
        self.assertIn(b'"input_tokens": 10', chunks)

    def test_a_whole_body_response_reports_the_carried_figure(self):
        body = json.dumps({'id': 'r1', 'output': [],
                           'usage': {'input_tokens': 10, 'output_tokens': 5}}
                          ).encode()
        response = FakeUpstream(200, body, [('Content-Type', 'application/json')])
        provider = providers.ExternalResponsesProvider(provider_defs.OPENROUTER)
        chunks = b''.join(provider.adapt(response, {('probe', 'echo'): 'identity'},
                                         {'model': MODEL, 'context_tokens': 900}))
        self.assertEqual(json.loads(chunks)['usage']['input_tokens'], 900)


class PrepareUsageTests(unittest.TestCase):
    def prepare(self, decoded_len=None):
        payload = _image_payload(2)
        raw = json.dumps(payload).encode()
        provider = providers.ExternalResponsesProvider(provider_defs.OPENROUTER)
        return provider.prepare(MODEL, '/responses', payload, raw,
                                {'Content-Type': 'application/json'},
                                _stub_credentials(), decoded_len=decoded_len)

    def test_prepare_reports_what_the_client_carries(self):
        prepared = self.prepare(decoded_len=7_000_000)
        self.assertEqual(prepared.context_tokens, by_slug(MODEL).context_window)

    def test_prepare_without_a_decoded_length_reports_nothing(self):
        self.assertIsNone(self.prepare().context_tokens)

    def test_subscription_prepare_reports_nothing(self):
        payload = {'model': 'gpt-6-astra', 'input': []}
        provider = providers.SubscriptionProvider()
        prepared = provider.prepare('gpt-6-astra', '/responses', payload,
                                    json.dumps(payload).encode(),
                                    {'Content-Type': 'application/json'},
                                    _stub_credentials(), decoded_len=5_800_000)
        self.assertIsNone(prepared.context_tokens)


if __name__ == '__main__':
    unittest.main()
