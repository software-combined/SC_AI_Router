"""Rewritten streamed tool IDs stay paired on the next Messages request."""
import json
import unittest
from unittest.mock import patch

from tests.fakes import FakeUpstream, install_fake
from tests.harness import (
    auth_file as _auth_file,
    post as _post,
    start_server as _start_server,
    test_state as _test_state,
)
from ai_router import claude_compat as compat


MODEL = 'anthropic/claude-fable-5.1'


def _frame(kind, payload):
    return b'event: %s\ndata: %s\n\n' % (kind.encode(), json.dumps(payload).encode())


def _tool_start(tool_id):
    return _frame('content_block_start', {
        'type': 'content_block_start', 'index': 0,
        'content_block': {'type': 'tool_use', 'id': tool_id,
                          'name': 'Read', 'input': {'file_path': 'probe.txt'}},
    })


class ToolResultReplayTest(unittest.TestCase):
    def test_rewritten_ids_are_carried_by_matching_tool_results(self):
        frames = [_tool_start('call_0'),
                  _frame('content_block_stop',
                         {'type': 'content_block_stop', 'index': 0}),
                  _tool_start('call_0'),
                  _frame('content_block_stop',
                         {'type': 'content_block_stop', 'index': 0})]
        with patch.object(compat, '_fresh_tool_id',
                          side_effect=('toolu_scg_a', 'toolu_scg_b')):
            shaped = b''.join(compat.shape(frames))
        ids = []
        for line in shaped.splitlines():
            if line.startswith(b'data: '):
                event = json.loads(line[6:])
                if event.get('type') == 'content_block_start':
                    ids.append(event['content_block']['id'])
        self.assertEqual(ids, ['toolu_scg_a', 'toolu_scg_b'])

        payload = {
            'model': MODEL, 'max_tokens': 8,
            'messages': [
                {'role': 'assistant', 'content': [
                    {'type': 'tool_use', 'id': ids[0], 'name': 'Read',
                     'input': {'file_path': 'probe-1.txt'}},
                    {'type': 'tool_use', 'id': ids[1], 'name': 'Read',
                     'input': {'file_path': 'probe-2.txt'}}]},
                {'role': 'user', 'content': [
                    {'type': 'tool_result', 'tool_use_id': ids[0],
                     'content': [{'type': 'text', 'text': 'MARKER-1'}]},
                    {'type': 'tool_result', 'tool_use_id': ids[1],
                     'content': [{'type': 'text', 'text': 'MARKER-2'}]}]},
            ],
        }
        recorded = install_fake(self, lambda: FakeUpstream(
            200, b'{"id":"msg_2","type":"message","content":[]}', []))
        server = _start_server(_test_state(_auth_file(self)))
        self.addCleanup(server.shutdown)
        response = _post(server.server_port, '/test-token/v1/messages', payload,
                         {'anthropic-version': '2023-06-01'})
        response.read()
        sent = json.loads(recorded[0][3])
        self.assertEqual(
            [item['id'] for item in sent['messages'][0]['content']], ids)
        self.assertEqual(
            [item['tool_use_id'] for item in sent['messages'][1]['content']], ids)
        self.assertNotIn('call_0', recorded[0][3].decode())


if __name__ == '__main__':
    unittest.main()
