"""Discovered schemas survive repeated compaction and restart (brief defect 7)."""
import base64
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from codex_router.compaction import PREFIX, SUMMARY_PREFIX, encode_summary
from codex_router.discovered import _MEMORY, recall, remember, summaries_in


def _home(test):
    tmp = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, tmp, True)
    _MEMORY.clear()
    test.addCleanup(_MEMORY.clear)
    patcher = mock.patch.dict(os.environ, {'ROUTER_HOME': tmp})
    patcher.start()
    test.addCleanup(patcher.stop)
    return Path(tmp)


def _tool(name):
    return {'type': 'function', 'name': name, 'parameters': {'type': 'object'}}


def _search_output(*tools):
    return {'type': 'tool_search_output', 'call_id': 's', 'tools': list(tools)}


def _summary_message(summary):
    return {'type': 'message', 'role': 'user',
            'content': [{'type': 'input_text', 'text': SUMMARY_PREFIX + '\n' + summary}]}


class DiscoveredStoreTests(unittest.TestCase):
    def test_repeated_compaction_chains_schemas_forward(self):
        _home(self)
        first = [_search_output(_tool('echo'))]
        remember(first, 'run one')
        chained = first + [_summary_message('run one'),
                           _search_output(_tool('fshuttle'))]
        remember(chained, 'run two')
        defs = recall([_summary_message('run two')])
        self.assertEqual({t['name'] for t in defs}, {'echo', 'fshuttle'})

    def test_v2_compaction_item_recalls(self):
        _home(self)
        remember([_search_output(_tool('echo'))], 'run one')
        blob = PREFIX + base64.b64encode(b'run one').decode()
        defs = recall([{'type': 'compaction', 'id': 'cmp_x', 'encrypted_content': blob}])
        self.assertEqual([t['name'] for t in defs], ['echo'])
        self.assertEqual(recall(
            [{'type': 'compaction', 'encrypted_content': 'opaque-native'}]), [])

    def test_disk_round_trip_survives_restart(self):
        home = _home(self)
        remember([_search_output(_tool('echo'))], 'run one')
        self.assertEqual(len(list((home / 'discovered-tools').glob('*.json'))), 1)
        _MEMORY.clear()
        defs = recall([_summary_message('run one')])
        self.assertEqual([t['name'] for t in defs], ['echo'])

    def test_summaries_in_ignores_malformed_content(self):
        self.assertEqual(summaries_in(None), [])
        self.assertEqual(summaries_in([{'type': 'message', 'role': 'user'},
                                       {'type': 'message', 'role': 'user',
                                        'content': None},
                                       {'type': 'message', 'role': 'user',
                                        'content': {'type': 'input_text'}},
                                       'just a string', 42]), [])

    def test_summaries_in_covers_v1_and_v2_shapes(self):
        blob = encode_summary('run two')
        self.assertEqual(
            summaries_in([_summary_message('run one'),
                          {'type': 'compaction', 'encrypted_content': blob},
                          {'type': 'message', 'role': 'user', 'content': 'plain'}]),
            ['run one', 'run two'])

    def test_empty_summary_and_missing_tools_remember_nothing(self):
        home = _home(self)
        remember([_search_output(_tool('echo'))], '  ')
        remember([{'type': 'message', 'role': 'user', 'content': 'hi'}], 'run one')
        self.assertEqual(_MEMORY, {})
        self.assertFalse((home / 'discovered-tools').exists())


if __name__ == '__main__':
    unittest.main()
