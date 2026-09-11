import io
import json
import os
import shutil
import tempfile
from pathlib import Path
import unittest
from unittest import mock
from ai_router.compaction import SUMMARY_PREFIX
from ai_router.discovered import _MEMORY, remember
from ai_router.capabilities import has_recursive_refs
from ai_router.tool_adapter import (
    prepare_tools, snoop_response_identity, stream_events, ToolEvents,
    SEARCH_NAME, integer_json)
from tests.fakes import FakeUpstream


def _isolated_home(test):
    tmp = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, tmp, True)
    _MEMORY.clear()
    test.addCleanup(_MEMORY.clear)
    patcher = mock.patch.dict(os.environ, {'ROUTER_HOME': tmp})
    patcher.start()
    test.addCleanup(patcher.stop)
    return tmp

class ToolAdapterTests(unittest.TestCase):
    def test_integral_provider_numbers_do_not_break_native_integer_arguments(self):
        raw = '{"limit":8.0,"text":"8.0","large":9007199254740993.0,"fraction":8.25}'
        self.assertEqual(integer_json(raw), '{"limit":8,"text":"8.0","large":9007199254740993,"fraction":8.25}')
        self.assertEqual(integer_json('{"value":1e8.0}'), '{"value":1e8.0}')
        self.assertEqual(integer_json('{oops'), '{oops')
        self.assertEqual(integer_json('{"text":"8.0"}'), '{"text":"8.0"}')
        self.assertEqual(integer_json('{"large":9007199254740993.0}'), '{"large":9007199254740993}')
        adapter = ToolEvents({(None, SEARCH_NAME): 'search'})
        item = adapter.item({'type': 'function_call', 'name': SEARCH_NAME, 'arguments': '{"query":"echo_probe","limit":8.0}'})
        self.assertIs(type(item['arguments']['limit']), int)

    def test_grok_oversized_catalog_defers_instead_of_rejecting(self):
        payload = {'model': 'x-ai/grok-4.6',
            'tools': [{'type': 'tool_search', 'description': 's',
                       'parameters': {'type': 'object', 'properties': {}}}] + [
                {'type': 'function', 'name': f'tool_{i}', 'parameters': {'type': 'object'}}
                for i in range(400)],
            'input': []}
        names = prepare_tools(payload)
        self.assertEqual([tool.get('name') for tool in payload['tools']],
                         [SEARCH_NAME])
        item = ToolEvents(names).item({'type': 'function_call', 'name': SEARCH_NAME,
            'arguments': '{"query":"echo"}'})
        self.assertEqual((item['type'], item['execution']), ('tool_search_call', 'client'))

    def test_grok_ceiling_without_search_still_fails_closed(self):
        payload = {'model': 'x-ai/grok-4.6', 'tools': [
            {'type': 'function', 'name': f'tool_{i}', 'parameters': {'type': 'object'}} for i in range(351)]}
        with self.assertRaisesRegex(ValueError, '350'):
            prepare_tools(payload)

    def test_grok_released_stub_overlap_survives_the_ceiling_cut(self):
        released = {'type': 'namespace', 'name': 'probe', 'tools': [
            {'type': 'function', 'name': 'echo', 'description': 'Echo',
             'parameters': {'type': 'object'}}]}
        stub = {'type': 'namespace', 'name': 'probe', 'tools': [
            {'type': 'function', 'name': 'echo', 'description': 'Echo'}]}
        payload = {'model': 'x-ai/grok-4.6',
            'tools': [{'type': 'tool_search', 'description': 's',
                       'parameters': {'type': 'object', 'properties': {}}},
                      stub] + [
                {'type': 'function', 'name': f'tool_{i}', 'parameters': {'type': 'object'}}
                for i in range(400)],
            'input': [{'type': 'tool_search_output', 'call_id': 's1', 'tools': [released]}]}
        names = prepare_tools(payload)
        self.assertEqual(len(payload['tools']), 2)
        item = ToolEvents(names).item({'type': 'function_call', 'name': payload['tools'][1]['name'],
            'arguments': '{"value":"probe"}'})
        self.assertEqual((item.get('namespace'), item.get('name')), ('probe', 'echo'))

    def test_grok_kept_over_ceiling_still_fails_closed(self):
        released = [{'type': 'function', 'name': f'found_{i}', 'description': 'Found',
                     'parameters': {'type': 'object'}} for i in range(400)]
        payload = {'model': 'x-ai/grok-4.6',
            'tools': [{'type': 'tool_search', 'description': 's',
                       'parameters': {'type': 'object', 'properties': {}}}],
            'input': [{'type': 'tool_search_output', 'call_id': 's1', 'tools': released}]}
        with self.assertRaisesRegex(ValueError, '350'):
            prepare_tools(payload)

    def test_grok_released_custom_tool_survives_with_its_kind(self):
        released = {'type': 'custom', 'name': 'exec', 'format': {'type': 'grammar'}}
        payload = {'model': 'x-ai/grok-4.6',
            'tools': [{'type': 'tool_search', 'description': 's',
                       'parameters': {'type': 'object', 'properties': {}}}] + [
                {'type': 'function', 'name': f'tool_{i}', 'parameters': {'type': 'object'}}
                for i in range(400)],
            'input': [{'type': 'tool_search_output', 'call_id': 's1', 'tools': [released]}]}
        names = prepare_tools(payload)
        self.assertEqual([tool.get('name') for tool in payload['tools']],
                         [SEARCH_NAME, 'exec'])
        item = ToolEvents(names).item({'type': 'function_call', 'name': 'exec',
            'arguments': '{"input":"hi"}'})
        self.assertEqual((item['type'], item['input']), ('custom_tool_call', 'hi'))

    def test_web_search_tool_dropped_without_upstream_capability(self):
        # 2026-09-10: deepseek-v4.1-flash streams aborted with OpenRouter's
        # 'Server tool request failed' while Codex's web_search server tool
        # rode along; the registry row carries no web-search capability.
        payload = {'model': 'deepseek/deepseek-v4.1-flash', 'tools': [
            {'type': 'web_search', 'external_web_access': False},
            {'type': 'function', 'name': 'exec', 'parameters': {'type': 'object'}}]}
        prepare_tools(payload)
        self.assertEqual([tool['type'] for tool in payload['tools']], ['function'])

    def test_web_search_tool_kept_when_upstream_supports_it(self):
        payload = {'model': 'meta/muse-spark-1.3-contributor', 'tools': [
            {'type': 'web_search', 'external_web_access': False}]}
        prepare_tools(payload)
        self.assertEqual([tool['type'] for tool in payload['tools']], ['web_search'])

    def test_web_search_tool_kept_for_unknown_models(self):
        payload = {'model': 'no/such-model', 'tools': [
            {'type': 'web_search', 'external_web_access': False}]}
        prepare_tools(payload)
        self.assertEqual([tool['type'] for tool in payload['tools']], ['web_search'])

    def test_grok_released_tool_survives_the_ceiling_cut(self):
        released = {'type': 'namespace', 'name': 'probe', 'tools': [
            {'type': 'function', 'name': 'echo', 'description': 'Echo',
             'parameters': {'type': 'object'}}]}
        payload = {'model': 'x-ai/grok-4.6',
            'tools': [{'type': 'tool_search', 'description': 's',
                       'parameters': {'type': 'object', 'properties': {}}}] + [
                {'type': 'function', 'name': f'tool_{i}', 'parameters': {'type': 'object'}}
                for i in range(400)],
            'input': [{'type': 'tool_search_output', 'call_id': 's1', 'tools': [released]}]}
        names = prepare_tools(payload)
        self.assertEqual(len(payload['tools']), 2)
        item = ToolEvents(names).item({'type': 'function_call', 'name': payload['tools'][1]['name'],
            'arguments': '{"value":"probe"}'})
        self.assertEqual((item.get('namespace'), item.get('name')), ('probe', 'echo'))

    def test_freeform_tool_and_history_round_trip(self):
        code = 'text(await tools.echo_probe({value: "probe"}));\n'
        payload = {'tools': [{'type': 'custom', 'name': 'exec', 'format': {'type': 'grammar'}}],
            'input': [{'type': 'custom_tool_call', 'call_id': 'call1', 'name': 'exec', 'input': code},
                      {'type': 'custom_tool_call_output', 'call_id': 'call1', 'output': 'result'}]}
        names = prepare_tools(payload)
        self.assertEqual(names, {(None, 'exec'): 'custom'})
        self.assertEqual(payload['tools'][0]['type'], 'function')
        self.assertEqual(json.loads(payload['input'][0]['arguments']), {'input': code})
        self.assertEqual(payload['input'][1]['type'], 'function_call_output')
        item = {'id': 'item1', 'type': 'function_call', 'call_id': 'call1', 'name': 'exec',
                'arguments': json.dumps({'input': code})}
        events = [
            {'type': 'response.output_item.added', 'item': {**item, 'arguments': ''}},
            {'type': 'response.function_call_arguments.delta', 'item_id': 'item1', 'delta': '{"input":'},
            {'type': 'response.function_call_arguments.done', 'item_id': 'item1', 'arguments': item['arguments']},
            {'type': 'response.output_item.done', 'item': item},
            {'type': 'response.completed', 'response': {'output': [item]}}]
        wire = b''.join(b'data: ' + json.dumps(event).encode() + b'\n\n' for event in events)
        result = [json.loads(block[6:]) for block in stream_events(io.BytesIO(wire), names)]
        self.assertEqual(len(result), 3)
        self.assertEqual(result[1]['item']['type'], 'custom_tool_call')
        self.assertEqual(result[1]['item']['input'], code)
        self.assertEqual(result[2]['response']['output'][0]['input'], code)

    def test_ordinary_tool_and_text_events_are_preserved(self):
        event = {'type': 'response.function_call_arguments.delta', 'item_id': 'ordinary', 'delta': '{'}
        wire = b'data: ' + json.dumps(event).encode() + b'\n\n'
        self.assertEqual(json.loads(next(stream_events(io.BytesIO(wire), {(None, 'exec'): 'custom'}))[6:]), event)

    def test_unmodified_delta_frame_passes_through_verbatim(self):
        upstream = b'{"delta":"hi","type":"response.output_text.delta"}'
        wire = b'data: ' + upstream + b'\n\n'
        out = list(stream_events(io.BytesIO(wire), {}))
        self.assertEqual(out, [b'data: ' + upstream + b'\n\n'])
        self.assertEqual(json.loads(out[0][6:]), json.loads(upstream))

    def test_mutated_function_call_frame_is_rewritten(self):
        event = {'type': 'response.output_item.done',
                 'item': {'type': 'function_call', 'name': 'unknown', 'arguments': '{"limit": 8.0}'}}
        upstream = json.dumps(event, separators=(',', ':')).encode()
        out = list(stream_events(io.BytesIO(b'data: ' + upstream + b'\n\n'), {}))
        self.assertEqual(len(out), 1)
        self.assertEqual(json.loads(out[0][6:])['item']['arguments'], '{"limit": 8}')
        self.assertNotEqual(out[0], b'data: ' + upstream + b'\n\n')

    def test_flag_resets_between_frames_in_one_stream(self):
        # Plan 091: a changed frame must not make the next unmodified frame
        # re-serialize; the reset happens per event, not per stream.
        mutated = {'type': 'response.output_item.done',
                   'item': {'type': 'function_call', 'name': 'unknown',
                            'arguments': '{"limit": 8.0}'}}
        plain = b'{"delta":"hi","type":"response.output_text.delta"}'
        wire = (b'data: ' + json.dumps(mutated).encode() + b'\n\n'
                + b'data: ' + plain + b'\n\n')
        out = list(stream_events(io.BytesIO(wire), {}))
        self.assertEqual(len(out), 2)
        self.assertEqual(json.loads(out[0][6:])['item']['arguments'], '{"limit": 8}')
        self.assertEqual(out[1], b'data: ' + plain + b'\n\n')

    def test_tracked_arguments_done_is_suppressed(self):
        names = {(None, 'exec'): 'custom'}
        item = {'id': 'item1', 'type': 'function_call', 'name': 'exec',
                'arguments': json.dumps({'input': 'hi'})}
        added = {'type': 'response.output_item.added', 'item': {**item, 'arguments': ''}}
        done = {'type': 'response.function_call_arguments.done', 'item_id': 'item1',
                'arguments': item['arguments']}
        wire = b''.join(b'data: ' + json.dumps(event).encode() + b'\n\n' for event in (added, done))
        out = list(stream_events(io.BytesIO(wire), names))
        self.assertEqual(len(out), 1)
        self.assertEqual(json.loads(out[0][6:])['type'], 'response.output_item.added')

    def test_malformed_code_input_never_becomes_an_executable_item(self):
        event = {'type': 'response.output_item.done', 'item': {'type': 'function_call', 'name': 'exec',
                 'arguments': '{"input":123}'}}
        wire = b'data: ' + json.dumps(event).encode() + b'\n\n'
        with self.assertRaisesRegex(ValueError, 'must be a string'):
            list(stream_events(io.BytesIO(wire), {(None, 'exec'): 'custom'}))

    def test_completed_event_records_served_model(self):
        notes = {}
        adapter = ToolEvents({}, notes)
        event = adapter.event({'type': 'response.completed',
                               'response': {'model': 'x-ai/grok-4.6', 'output': []}})
        self.assertEqual(notes, {'served_model': 'x-ai/grok-4.6'})
        self.assertEqual(event['response']['model'], 'x-ai/grok-4.6')
        adapter.event({'type': 'response.completed', 'response': {'output': []}})
        self.assertEqual(notes, {'served_model': 'x-ai/grok-4.6'})

    def test_discovery_remains_client_executed_with_history_preserved(self):
        payload = {'tools': [{'type': 'tool_search', 'execution': 'client', 'parameters': {'type': 'object'}}],
            'input': [{'type': 'tool_search_call', 'call_id': 's1', 'execution': 'client', 'arguments': {'query': 'echo'}},
                      {'type': 'tool_search_output', 'call_id': 's1', 'execution': 'client', 'status': 'completed', 'tools': [{'name': 'echo'}]}]}
        names = prepare_tools(payload)
        self.assertEqual(payload['tools'][0]['type'], 'function')
        self.assertNotIn('execution', payload['tools'][0])
        self.assertEqual(payload['input'][1]['type'], 'function_call_output')
        item = ToolEvents(names).item({'type': 'function_call', 'name': SEARCH_NAME, 'call_id': 's1', 'arguments': '{"query":"echo"}'})
        self.assertEqual(item, {'type': 'tool_search_call', 'call_id': 's1', 'execution': 'client', 'arguments': {'query': 'echo'}})
        qualified = ToolEvents(names).item({'type': 'function_call', 'name': SEARCH_NAME, 'arguments': '{"query":"probe.echo_probe"}'})
        self.assertEqual(qualified['arguments'], {'query': 'probe echo_probe'})

    def test_union_root_schema_is_string_wrapped_for_grok_only(self):
        union = {'anyOf': [{'type': 'object', 'properties': {'value': {'type': 'string'}}},
                           {'type': 'string'}]}
        for model, wrapped in (('x-ai/grok-4.6', True), ('z-ai/glm-5.3-flash', False)):
            with self.subTest(model=model):
                payload = {'model': model, 'tools': [
                    {'type': 'function', 'name': 'flex', 'description': 'Flex',
                     'parameters': union}]}
                names = prepare_tools(payload)
                tool = payload['tools'][0]
                if wrapped:
                    self.assertEqual(tool['parameters']['properties'], {'arguments_json': {'type': 'string'}})
                    self.assertIn(json.dumps(union), tool['description'])
                    for value in ({'value': 'x'}, 'plain'):
                        item = ToolEvents(names).item({'type': 'function_call', 'name': tool['name'],
                            'arguments': json.dumps({'arguments_json': json.dumps(value)})})
                        self.assertEqual(json.loads(item['arguments']), value)
                else:
                    self.assertEqual(tool['parameters'], union)

    def test_object_root_union_with_scalar_branch_is_wrapped_for_grok(self):
        # Reported 409: automation_update declares type object at root with a
        # oneOf holding a non-object branch. xAI rejects it; wrap it.
        params = {'type': 'object', 'properties': {},
                  'oneOf': [{'type': 'object', 'properties': {'a': {'type': 'string'}}},
                            {'type': 'string'}]}
        payload = {'model': 'x-ai/grok-4.6', 'tools': [
            {'type': 'function', 'name': 'automation_update', 'description': 'D',
             'parameters': params}]}
        names = prepare_tools(payload)
        tool = payload['tools'][0]
        self.assertEqual(tool['parameters']['properties'], {'arguments_json': {'type': 'string'}})
        self.assertIn(json.dumps(params), tool['description'])
        self.assertEqual(names[(None, 'automation_update')], 'json_text_root')
        for value in ({'a': 'x'}, 'plain'):
            item = ToolEvents(names).item({'type': 'function_call', 'name': 'automation_update',
                'arguments': json.dumps({'arguments_json': json.dumps(value)})})
            self.assertEqual(json.loads(item['arguments']), value)

    def test_object_only_union_root_stays_native_for_grok(self):
        # xAI documents object-only unions as acceptable; keep them native.
        params = {'type': 'object', 'properties': {},
                  'oneOf': [{'type': 'object', 'properties': {'a': {'type': 'string'}}},
                            {'type': 'object', 'properties': {'b': {'type': 'integer'}}}]}
        payload = {'model': 'x-ai/grok-4.6', 'tools': [
            {'type': 'function', 'name': 'flex', 'description': 'Flex',
             'parameters': params}]}
        names = prepare_tools(payload)
        self.assertEqual(payload['tools'][0]['parameters'], params)
        self.assertNotIn((None, 'flex'), names)

    def test_recursive_schema_keeps_exact_arguments_and_native_contract(self):
        schema = {'type': 'object', 'properties': {'tree': {'$ref': '#/$defs/Node'}},
            '$defs': {'Node': {'type': 'object', 'properties': {'children': {'type': 'array', 'items': {'$ref': '#/$defs/Node'}}}}}}
        self.assertTrue(has_recursive_refs(schema))
        self.assertFalse(has_recursive_refs({'properties': {'name': {'$ref': '#/$defs/Name'}}, '$defs': {'Name': {'type': 'string'}}}))
        payload = {'model': 'meta/muse-spark-1.3', 'tools': [{'type': 'namespace', 'name': 'probe', 'tools': [
            {'type': 'function', 'name': 'echo', 'parameters': schema}]}]}
        names = prepare_tools(payload)
        tool = payload['tools'][0]
        self.assertFalse(has_recursive_refs(tool['parameters']))
        self.assertIn(json.dumps(schema), tool['description'])
        original = {'tree': {'children': [{'children': []}]}}
        item = ToolEvents(names).item({'type': 'function_call', 'name': tool['name'],
            'arguments': json.dumps({'arguments_json': json.dumps(original)})})
        self.assertEqual(json.loads(item['arguments']), original)
        self.assertEqual((item['namespace'], item['name']), ('probe', 'echo'))

    def test_discovered_namespace_is_advertised_and_round_trips(self):
        released = {'type': 'namespace', 'name': 'probe', 'tools': [
            {'type': 'function', 'name': 'echo', 'description': 'Echo', 'defer_loading': True, 'parameters': {'type': 'object'}}]}
        payload = {'tools': [], 'input': [
            {'type': 'tool_search_output', 'call_id': 's1', 'status': 'completed', 'execution': 'client', 'tools': [released]},
            {'type': 'function_call', 'namespace': 'probe', 'name': 'echo', 'call_id': 'e1', 'arguments': '{"value":"probe"}'}]}
        names = prepare_tools(payload)
        tool = payload['tools'][0]
        self.assertEqual(tool['type'], 'function')
        self.assertNotIn('defer_loading', tool)
        self.assertEqual(payload['input'][1]['name'], tool['name'])
        self.assertNotIn('namespace', payload['input'][1])
        self.assertEqual(json.loads(payload['input'][0]['output'])['available_tools'][0]['name'], tool['name'])
        item = ToolEvents(names).item({'type': 'function_call', 'name': tool['name'], 'arguments': '{"value":"probe"}'})
        self.assertEqual(item['namespace'], 'probe')
        self.assertEqual(item['name'], 'echo')
        self.assertEqual(json.loads(item['arguments']), {'value': 'probe'})

    def test_discovered_tools_survive_compaction_via_summary(self):
        released = {'type': 'namespace', 'name': 'probe', 'tools': [
            {'type': 'function', 'name': 'echo', 'description': 'Echo',
             'parameters': {'type': 'object'}}]}
        items = [{'type': 'tool_search_output', 'call_id': 's1', 'status': 'completed',
                  'execution': 'client', 'tools': [released]}]
        _isolated_home(self)
        remember(items, 'run-7')
        payload = {'tools': [], 'input': [
            {'type': 'message', 'role': 'user', 'content': SUMMARY_PREFIX + '\nrun-7'}]}
        prepare_tools(payload)
        self.assertEqual(len(payload['tools']), 1)
        self.assertTrue(payload['tools'][0]['description'].startswith('probe.echo'))
        self.assertEqual(payload['tools'][0]['parameters'], {'type': 'object'})

    def test_discovered_cache_bounds_memory_but_keeps_disk(self):
        home = Path(_isolated_home(self))
        for i in range(20):
            tool = {'type': 'function', 'name': f'tool-{i}', 'parameters': {'type': 'object'}}
            items = [{'type': 'tool_search_output', 'call_id': 's', 'tools': [tool]}]
            remember(items, f'run-{i}')
        self.assertLessEqual(len(_MEMORY), 16)
        stored = sorted((home / 'discovered-tools').glob('*.json'))
        self.assertEqual(len(stored), 16)
        _MEMORY.clear()  # Simulate a router restart: disk is the only copy.
        for run in ('run-4', 'run-19'):
            payload = {'tools': [], 'input': [
                {'type': 'message', 'role': 'user', 'content': SUMMARY_PREFIX + f'\n{run}'}]}
            prepare_tools(payload)
            self.assertEqual(len(payload['tools']), 1)
        gone = {'tools': [], 'input': [
            {'type': 'message', 'role': 'user', 'content': SUMMARY_PREFIX + '\nrun-0'}]}
        prepare_tools(gone)
        self.assertEqual(gone['tools'], [])

    def test_namespaced_custom_history_matches_flattened_definition(self):
        payload = {'model': 'z-ai/glm-5.3-flash',
                   'tools': [{'type': 'namespace', 'name': 'probe', 'tools': [
                       {'type': 'custom', 'name': 'exec', 'format': {'type': 'grammar'}}]}],
                   'input': [
                       {'type': 'custom_tool_call', 'namespace': 'probe', 'name': 'exec',
                        'call_id': 'c1', 'input': 'echo hi'},
                       {'type': 'custom_tool_call_output', 'namespace': 'probe', 'name': 'exec',
                        'call_id': 'c1', 'output': 'hi'}]}
        names = prepare_tools(payload)
        wire = payload['tools'][0]['name']
        self.assertTrue(wire.startswith('ns_'))
        call, result = payload['input']
        self.assertEqual(call['type'], 'function_call')
        self.assertEqual(call['name'], wire)
        self.assertNotIn('namespace', call)
        self.assertEqual(json.loads(call['arguments']), {'input': 'echo hi'})
        self.assertEqual(result['type'], 'function_call_output')
        self.assertEqual(result['name'], wire)
        self.assertNotIn('namespace', result)
        self.assertEqual(result['call_id'], 'c1')
        # The response leg converts the wire call back to the namespaced shape.
        back = ToolEvents(names).item(
            {'type': 'function_call', 'name': wire, 'arguments': call['arguments']})
        self.assertEqual(back['type'], 'custom_tool_call')
        self.assertEqual((back['namespace'], back['name']), ('probe', 'exec'))
        self.assertEqual(back['input'], 'echo hi')

    def test_snoop_records_model_without_tools_json(self):
        body = b'{"id": "resp_1", "model": "x-ai/grok-4.6", "output": []}'
        notes = {}
        out = b''.join(snoop_response_identity(FakeUpstream(200, body, []), notes))
        self.assertEqual(notes, {'served_model': 'x-ai/grok-4.6'})
        self.assertEqual(out, body)

    def test_snoop_records_model_without_tools_sse(self):
        events = (b'event: response.output_item.done\n'
                  b'data: {"type": "response.output_item.done", "item": {}}\n\n'
                  b'event: response.completed\n'
                  b'data: {"type": "response.completed", '
                  b'"response": {"model": "x-ai/grok-4.6", "output": []}}\n\n')
        notes = {}
        out = b''.join(snoop_response_identity(
            FakeUpstream(200, events, [('Content-Type', 'text/event-stream')]), notes))
        self.assertEqual(notes, {'served_model': 'x-ai/grok-4.6'})
        self.assertEqual(out, events)

    def test_snoop_ignores_errors_and_malformed_bodies(self):
        notes = {}
        out = b''.join(snoop_response_identity(FakeUpstream(500, b'{"error": 1}', []), notes))
        self.assertEqual(notes, {})
        self.assertEqual(out, b'{"error": 1}')
        notes = {}
        out = b''.join(snoop_response_identity(FakeUpstream(200, b'not json', []), notes))
        self.assertEqual(notes, {})
        self.assertEqual(out, b'not json')

    def test_stub_in_tools_is_completed_by_discovered_schema(self):
        schema = {'type': 'object', 'properties': {'value': {'type': 'string'}}}
        stub = {'type': 'function', 'name': 'echo', 'description': 'Echo stub'}
        full = {'type': 'function', 'name': 'echo', 'description': 'Echo', 'parameters': schema}
        payload = {'tools': [{'type': 'namespace', 'name': 'probe', 'tools': [stub]}],
            'input': [{'type': 'tool_search_output', 'call_id': 's1', 'status': 'completed',
                       'execution': 'client',
                       'tools': [{'type': 'namespace', 'name': 'probe', 'tools': [full]}]}]}
        prepare_tools(payload)
        matches = [tool for tool in payload['tools']
                   if tool.get('description', '').startswith('probe.echo')]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['parameters'], schema)

    def test_declared_schema_is_not_clobbered_by_discovered_stub(self):
        schema = {'type': 'object', 'properties': {'value': {'type': 'string'}}}
        full = {'type': 'function', 'name': 'echo', 'description': 'Echo', 'parameters': schema}
        stub = {'type': 'function', 'name': 'echo', 'description': 'Echo stub'}
        payload = {'tools': [{'type': 'namespace', 'name': 'probe', 'tools': [full]}],
            'input': [{'type': 'tool_search_output', 'call_id': 's1', 'status': 'completed',
                       'execution': 'client',
                       'tools': [{'type': 'namespace', 'name': 'probe', 'tools': [stub]}]}]}
        prepare_tools(payload)
        matches = [tool for tool in payload['tools']
                   if tool.get('description', '').startswith('probe.echo')]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['parameters'], schema)

if __name__ == '__main__':
    unittest.main()
