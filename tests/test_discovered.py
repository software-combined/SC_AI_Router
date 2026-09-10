"""Discovered schemas survive repeated compaction and restart (brief defect 7)."""
import base64
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from ai_router.compaction import PREFIX, SUMMARY_PREFIX, encode_summary
from ai_router.discovered import _MEMORY, recall, remember, summaries_in


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

    def test_repeated_rediscovery_keeps_one_effective_definition(self):
        home = _home(self)
        for i in range(20):
            items = [_summary_message(f'run {i}')] if i else []
            remember(items + [_search_output(_tool('echo'))], f'run {i+1}')
        defs = recall([_summary_message('run 20')])
        self.assertEqual([t['name'] for t in defs], ['echo'])
        stored = list((home / 'discovered-tools').glob('*.json'))
        self.assertTrue(stored)
        for path in stored:
            names = [t.get('name') for t in json.loads(path.read_text())]
            self.assertEqual(len(names), len(set(names)))

    def test_disk_round_trip_deduplicates_legacy_duplicates(self):
        home = _home(self)
        remember([_search_output(_tool('echo'))], 'run one')
        _MEMORY.clear()
        store = home / 'discovered-tools'
        path = next(store.glob('*.json'))
        rows = json.loads(path.read_text())
        path.write_text(json.dumps(rows + [dict(rows[0])]))
        defs = recall([_summary_message('run one')])
        self.assertEqual([t['name'] for t in defs], ['echo'])

    def test_fresh_full_schema_beats_recalled_full_schema(self):
        _home(self)
        full_old = dict(_tool('echo'), description='old')
        full_new = dict(_tool('echo'), description='new')
        remember([_search_output(full_old)], 'run one')
        remember([_summary_message('run one'), _search_output(full_new)],
                 'run two')
        defs = recall([_summary_message('run two')])
        self.assertEqual(len(defs), 1)
        self.assertEqual(defs[0]['description'], 'new')

    def test_fresh_stub_completed_by_recalled_full_schema(self):
        _home(self)
        stub = {'type': 'function', 'name': 'echo'}
        full = dict(_tool('echo'), description='full')
        remember([_search_output(full)], 'run one')
        remember([_summary_message('run one'), _search_output(stub)],
                 'run two')
        defs = recall([_summary_message('run two')])
        self.assertEqual(len(defs), 1)
        self.assertEqual(defs[0].get('parameters'), {'type': 'object'})

    def test_mutating_recalled_data_leaves_store_intact(self):
        _home(self)
        remember([_search_output(_tool('echo'))], 'run one')
        defs = recall([_summary_message('run one')])
        defs[0]['name'] = 'mutated'
        defs.append(_tool('extra'))
        again = recall([_summary_message('run one')])
        self.assertEqual([t['name'] for t in again], ['echo'])

    def _ns_wrap(self, *names, **kwargs):
        full = kwargs.get('full', True)
        tools = []
        for name in names:
            tool = {'type': 'function', 'name': name}
            if full:
                tool['parameters'] = {'type': 'object'}
            tools.append(tool)
        return {'type': 'namespace', 'name': 'probe', 'tools': tools}

    def _flattened(self, defs):
        from ai_router.tool_adapter import tool_entries
        return sorted((ns, tool.get('name')) for tool, ns in tool_entries(defs))

    def test_wrapped_namespaces_chain_across_compactions(self):
        _home(self)
        remember([_search_output(self._ns_wrap('echo'))], 'run one')
        remember([_summary_message('run one'),
                  _search_output(self._ns_wrap('fshuttle'))], 'run two')
        self.assertEqual(
            self._flattened(recall([_summary_message('run two')])),
            [('probe', 'echo'), ('probe', 'fshuttle')])

    def test_wrapped_stub_completed_by_recalled_full_schema(self):
        _home(self)
        remember([_search_output(self._ns_wrap('echo'))], 'run one')
        remember([_summary_message('run one'),
                  _search_output(self._ns_wrap('echo', full=False))],
                 'run two')
        defs = recall([_summary_message('run two')])
        self.assertEqual(self._flattened(defs), [('probe', 'echo')])
        from ai_router.tool_adapter import tool_entries
        params = [tool.get('parameters') for tool, _ in tool_entries(defs)]
        self.assertEqual(params, [{'type': 'object'}])

    def test_namespaced_collision_keeps_both_scopes(self):
        _home(self)
        remember([_search_output(dict(_tool('echo'), namespace='a'),
                                 dict(_tool('echo'), namespace='b'))],
                 'run one')
        defs = recall([_summary_message('run one')])
        self.assertEqual(
            sorted((t.get('namespace'), t['name']) for t in defs),
            [('a', 'echo'), ('b', 'echo')])


if __name__ == '__main__':
    unittest.main()
