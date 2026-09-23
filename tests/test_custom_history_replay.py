import json
import unittest

from ai_router.tool_adapter import prepare_tools


def pair_payload(tools):
    """One custom call/output pair over `exec`, under the given tool list."""
    return {'model': 'xiaomi/mimo-v2.6-pro', 'tools': tools, 'input': [
        {'type': 'custom_tool_call', 'call_id': 'call1', 'name': 'exec',
         'input': 'echo hi'},
        {'type': 'custom_tool_call_output', 'call_id': 'call1', 'output': 'hi'}]}


class CustomHistoryReplayTests(unittest.TestCase):
    def test_function_declared_custom_history_converts_symmetrically(self):
        payload = pair_payload([{'type': 'function', 'name': 'exec',
                                 'parameters': {'type': 'object'}}])
        prepare_tools(payload)
        call, result = payload['input']
        self.assertEqual((call['type'], result['type']),
                         ('function_call', 'function_call_output'))
        self.assertEqual((call['call_id'], result['call_id']), ('call1', 'call1'))
        self.assertEqual(json.loads(call['arguments']), {'input': 'echo hi'})

    def test_unknown_custom_pair_keeps_symmetric_custom_shape(self):
        payload = pair_payload([])
        prepare_tools(payload)
        self.assertEqual([item['type'] for item in payload['input']],
                         ['custom_tool_call', 'custom_tool_call_output'])
        self.assertEqual([item['call_id'] for item in payload['input']],
                         ['call1', 'call1'])


if __name__ == '__main__':
    unittest.main()
