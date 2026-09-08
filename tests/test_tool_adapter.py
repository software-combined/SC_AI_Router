import io
import json
import unittest
from codex_router.tool_adapter import prepare_tools, stream_events, ToolEvents, has_recursive_refs, SEARCH_NAME, integer_json

class ToolAdapterTests(unittest.TestCase):
    def test_integral_provider_numbers_do_not_break_native_integer_arguments(self):
        raw = '{"limit":8.0,"text":"8.0","large":9007199254740993.0,"fraction":8.25}'
        self.assertEqual(integer_json(raw), '{"limit":8,"text":"8.0","large":9007199254740993,"fraction":8.25}')
        self.assertEqual(integer_json('{"value":1e8.0}'), '{"value":1e8.0}')
        adapter = ToolEvents({(None, SEARCH_NAME): 'search'})
        item = adapter.item({'type': 'function_call', 'name': SEARCH_NAME, 'arguments': '{"query":"echo_probe","limit":8.0}'})
        self.assertIs(type(item['arguments']['limit']), int)

    def test_grok_oversized_catalog_fails_before_upstream_retries(self):
        payload = {'model': '~x-ai/grok-latest', 'tools': [
            {'type': 'function', 'name': f'tool_{i}', 'parameters': {'type': 'object'}} for i in range(351)]}
        with self.assertRaisesRegex(ValueError, '350'):
            prepare_tools(payload)

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

    def test_malformed_code_input_never_becomes_an_executable_item(self):
        event = {'type': 'response.output_item.done', 'item': {'type': 'function_call', 'name': 'exec',
                 'arguments': '{"input":123}'}}
        wire = b'data: ' + json.dumps(event).encode() + b'\n\n'
        with self.assertRaisesRegex(ValueError, 'must be a string'):
            list(stream_events(io.BytesIO(wire), {(None, 'exec'): 'custom'}))

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
