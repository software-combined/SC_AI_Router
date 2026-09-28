import json
import unittest

from ai_router import provider_defs
from ai_router.providers import ExternalResponsesProvider
from ai_router.tool_adapter import SEARCH_NAME, ToolEvents
from tests.harness import stub_credentials
from tests.tool_stages import prepare_tools


class HistoryPortabilityTests(unittest.TestCase):

        def _history_payload(self, model='meta/muse-spark-1.3-contributor'):
            echo = {'type': 'function', 'name': 'echo', 'description': 'Echo', 'parameters': {'type': 'object'}}
            released = {'type': 'namespace', 'name': 'probe', 'tools': [echo]}
            return {'model': model, 'tools': [
                {'type': 'tool_search', 'execution': 'client', 'parameters': {'type': 'object'}},
                {'type': 'function', 'name': 'exec', 'parameters': {'type': 'object'}}], 'input': [
                {'type': 'tool_search_call', 'call_id': 's1', 'execution': 'client', 'arguments': {'query': 'echo'}},
                {'type': 'tool_search_output', 'call_id': 's1', 'execution': 'client', 'status': 'completed', 'tools': [released]},
                {'type': 'function_call', 'name': 'exec', 'call_id': 'e1', 'arguments': '{"value":"probe"}'},
                {'type': 'function_call_output', 'name': 'exec', 'call_id': 'e1', 'output': 'result'}]}

        def test_native_declared_pair_survives_with_discovery_intact(self):
            # The regression that matters most: the plain pair and the discovery
            # pair pass through untouched in native mode, deterministically.
            payload = self._history_payload('deepseek/deepseek-v4.1-flash')
            payload = prepare_tools(payload)[0]
            kinds = [(i.get('type'), i.get('name')) for i in payload['input']]
            self.assertEqual(kinds, [('function_call', SEARCH_NAME),
                                     ('function_call_output', None),
                                     ('function_call', 'exec'),
                                     ('function_call_output', 'exec')])
            self.assertEqual(payload['input'][2]['arguments'], '{"value":"probe"}')
            rerun = self._history_payload('deepseek/deepseek-v4.1-flash')
            rerun = prepare_tools(rerun)[0]
            self.assertEqual(json.dumps(payload['input'], sort_keys=True),
                             json.dumps(rerun['input'], sort_keys=True))

        def test_portable_replaces_only_the_discovery_pair_with_a_note(self):
            payload = self._history_payload()
            payload, names = prepare_tools(payload)
            kinds = [(i.get('type'), i.get('role')) for i in payload['input']]
            self.assertEqual(kinds, [('message', 'user'), ('function_call', None),
                                     ('function_call_output', None)])
            self.assertIn('search call itself is omitted',
                          payload['input'][0]['content'][0]['text'])
            released = [t for t in payload['tools'] if 'probe.echo' in t.get('description', '')]
            self.assertEqual(len(released), 1)
            back = ToolEvents(names).item(
                {'type': 'function_call', 'name': released[0]['name'],
                 'arguments': '{"value":"probe"}'})
            self.assertEqual((back.get('namespace'), back.get('name')), ('probe', 'echo'))
            marker = {'type': 'message', 'role': 'developer', 'content': [
                {'type': 'input_text', 'text': '<model_switch> hop'}]}
            by_marker = self._history_payload('deepseek/deepseek-v4.1-flash')
            by_marker['input'].append(marker)
            by_marker = prepare_tools(by_marker)[0]
            self.assertEqual(json.dumps(by_marker['input'][:3], sort_keys=True),
                             json.dumps(payload['input'], sort_keys=True))
            self.assertEqual(by_marker['input'][-1], marker)
            # Mirror: the marker at index 0 means nothing is foreign, so the
            # payload is byte-identical to the native run.
            native = self._history_payload('deepseek/deepseek-v4.1-flash')
            native = prepare_tools(native)[0]
            leading = self._history_payload('deepseek/deepseek-v4.1-flash')
            leading['input'].insert(0, marker)
            leading = prepare_tools(leading)[0]
            self.assertEqual(json.dumps(leading['input'][1:], sort_keys=True),
                             json.dumps(native['input'], sort_keys=True))

        def test_portable_drops_orphan_discovery_halves(self):
            exec_tool = {'type': 'function', 'name': 'exec', 'parameters': {'type': 'object'}}
            for item in ({'type': 'function_call', 'name': SEARCH_NAME, 'call_id': 's9', 'arguments': '{"q":"e"}'},
                         {'type': 'function_call_output', 'name': SEARCH_NAME, 'call_id': 's9', 'output': '{}'}):
                with self.subTest(item=item['type']):
                    payload = {'model': 'meta/muse-spark-1.3-contributor', 'tools': [exec_tool], 'input': [item]}
                    payload = prepare_tools(payload)[0]
                    self.assertEqual(payload['input'], [])

        def test_portable_keeps_a_nameless_plain_output(self):
            # Codex omits `name` on function_call_output, so the portable pass must
            # pair by call_id: a nameless output for a plain call is real history
            # and survives, or every tool result and delegated assignment would be
            # dropped on the portable row.
            payload = self._history_payload()
            call = {'type': 'function_call', 'name': 'exec', 'call_id': 'e2',
                    'arguments': '{"value":"probe"}'}
            output = {'type': 'function_call_output', 'call_id': 'e2', 'output': 'kept'}
            payload['input'].extend([call, output])
            payload = prepare_tools(payload)[0]
            kept = [item for item in payload['input'] if item.get('call_id') == 'e2']
            self.assertEqual([item.get('type') for item in kept],
                             ['function_call', 'function_call_output'])
            self.assertEqual(kept[1]['output'], 'kept')
            notes = [item for item in payload['input']
                     if item.get('type') == 'message' and item.get('role') == 'user']
            self.assertEqual(len(notes), 1)

        def test_user_text_never_selects_the_portable_pass(self):
            # The marker is the client's developer message; user text is data.
            marker = {'type': 'message', 'role': 'user', 'content': [
                {'type': 'input_text', 'text': '<model_switch> typed by a person'}]}
            payload = self._history_payload('deepseek/deepseek-v4.1-flash')
            payload['input'].insert(0, marker)
            payload = prepare_tools(payload)[0]
            self.assertEqual([(item.get('type'), item.get('name')) for item in payload['input']],
                             [('message', None), ('function_call', SEARCH_NAME),
                              ('function_call_output', None), ('function_call', 'exec'),
                              ('function_call_output', 'exec')])

        @staticmethod
        def _reasoning_item():
            # A carried reasoning item as Codex replays it: readable text, no
            # summary, owned by the model that produced it.
            return {'type': 'reasoning', 'id': 'rs_tmp_probe', 'summary': [],
                    'encrypted_content': 'blob',
                    'content': [{'type': 'reasoning_text', 'text': 'prior model thinking'}]}

        def test_portable_turn_drops_carried_reasoning(self):
            # Measured 2026-09-12: Meta answers a carried reasoning item with a
            # bare HTTP 400, so a portable turn must not replay one. Native,
            # marker-free turns keep the item (its blob is stripped later).
            marker = {'type': 'message', 'role': 'developer', 'content': [
                {'type': 'input_text', 'text': '<model_switch> hop'}]}
            for model, with_marker in (('meta/muse-spark-1.3-contributor', False),
                                       ('deepseek/deepseek-v4.1-flash', True)):
                with self.subTest(model=model, marker=with_marker):
                    payload = self._history_payload(model)
                    payload['input'].insert(0, self._reasoning_item())
                    if with_marker:
                        payload['input'].insert(1, marker)
                    payload = prepare_tools(payload)[0]
                    self.assertEqual(
                        [item for item in payload['input'] if item.get('type') == 'reasoning'], [])
            after = self._history_payload('deepseek/deepseek-v4.1-flash')
            after['input'].insert(0, marker)
            after['input'].insert(1, self._reasoning_item())
            after = prepare_tools(after)[0]
            self.assertEqual(
                [item.get('id') for item in after['input'] if item.get('type') == 'reasoning'],
                ['rs_tmp_probe'])
            native = self._history_payload('deepseek/deepseek-v4.1-flash')
            native['input'].insert(0, self._reasoning_item())
            native = prepare_tools(native)[0]
            self.assertEqual(
                [item.get('id') for item in native['input'] if item.get('type') == 'reasoning'],
                ['rs_tmp_probe'])

        def test_wire_body_carries_no_reasoning_for_a_portable_row(self):
            # End-to-end through the provider this incident used: the refused
            # body had a carried reasoning item and Meta rejected it, while the
            # same body without that item is accepted.

            def wire(model):
                payload = self._history_payload(model)
                payload['input'].insert(0, self._reasoning_item())
                provider = ExternalResponsesProvider(provider_defs.OPENROUTER)
                prepared = provider.prepare(payload['model'], '/responses', payload,
                                            json.dumps(payload).encode(), {}, stub_credentials())
                return json.loads(prepared.body)

            portable = wire('meta/muse-spark-1.3-contributor')
            self.assertEqual([i for i in portable['input'] if i.get('type') == 'reasoning'], [])
            native = wire('deepseek/deepseek-v4.1-flash')
            self.assertEqual(len([i for i in native['input'] if i.get('type') == 'reasoning']), 1)

        def test_portable_turn_replays_a_readable_reasoning_summary(self):
            # A summary is context the previous model wrote for replay: it
            # survives as a visible note instead of a foreign reasoning item.
            summarised = dict(self._reasoning_item(), id='rs_tmp_summary',
                              summary=[{'type': 'text', 'text': 'ten-call cap'}])
            payload = self._history_payload()
            payload['input'].insert(0, summarised)
            payload = prepare_tools(payload)[0]
            self.assertEqual([i for i in payload['input'] if i.get('type') == 'reasoning'], [])
            notes = [i for i in payload['input']
                     if i.get('type') == 'message' and i.get('role') == 'user']
            text = ' '.join(b.get('text', '') for note in notes
                            for b in (note.get('content') or []))
            self.assertIn('ten-call cap', text)

        def test_search_note_never_splits_a_parallel_tool_group(self):
            # 2026-09-13: a carried thread that switched models replays the
            # <model_switch> marker, so every later turn ran the portable pass.
            # The note it wrote for the search pair landed between a parallel
            # group's calls and their outputs and deepseek/deepseek-v4.1-flash
            # refused the turn ("incomplete parallel tool-call group").
            marker = {'type': 'message', 'role': 'developer', 'content': [
                {'type': 'input_text', 'text': '<model_switch> hop'}]}
            payload = self._history_payload('deepseek/deepseek-v4.1-flash')
            payload['input'] = [
                {'type': 'function_call', 'name': 'exec', 'call_id': 'c0',
                 'arguments': '{"value":"a"}'},
                {'type': 'function_call', 'name': 'exec', 'call_id': 'c1',
                 'arguments': '{"value":"b"}'},
                {'type': 'tool_search_call', 'call_id': 's1', 'execution': 'client',
                 'arguments': {'query': 'echo'}},
                {'type': 'function_call_output', 'name': 'exec', 'call_id': 'c0', 'output': 'a'},
                {'type': 'function_call_output', 'name': 'exec', 'call_id': 'c1', 'output': 'b'},
                {'type': 'tool_search_output', 'call_id': 's1', 'execution': 'client',
                 'status': 'completed', 'tools': []},
                marker,
                {'type': 'message', 'role': 'user', 'content': [
                    {'type': 'input_text', 'text': 'next'}]}]
            payload = prepare_tools(payload)[0]
            # A group after the marker is native and receives no note; the
            # marker sits between the rewritten foreign prefix and the rest.
            self.assertEqual([item.get('type') for item in payload['input']],
                             ['function_call', 'function_call',
                              'function_call_output', 'function_call_output',
                              'message', 'message', 'message'])
            self.assertIn('search call itself is omitted',
                          payload['input'][4]['content'][0]['text'])
            self.assertEqual(payload['input'][5], marker)
            self.assertEqual(payload['input'][6]['content'][0]['text'], 'next')

        def test_search_note_never_splits_an_apply_patch_group(self):
            # The run window covers every call/output type the scrub
            # accepts, not just function/custom calls: an apply_patch pair
            # astride the search pair keeps the note deferred too.
            marker = {'type': 'message', 'role': 'developer', 'content': [
                {'type': 'input_text', 'text': '<model_switch> hop'}]}
            payload = self._history_payload('deepseek/deepseek-v4.1-flash')
            payload['input'] = [
                {'type': 'apply_patch_call', 'call_id': 'a1',
                 'status': 'completed',
                 'operation': {'type': 'update_file', 'path': 'n.txt',
                               'diff': 'x'}},
                {'type': 'tool_search_call', 'call_id': 's1', 'execution': 'client',
                 'arguments': {'query': 'echo'}},
                {'type': 'apply_patch_call_output', 'call_id': 'a1',
                 'status': 'completed', 'output': 'done'},
                {'type': 'tool_search_output', 'call_id': 's1', 'execution': 'client',
                 'status': 'completed', 'tools': []},
                marker,
                {'type': 'message', 'role': 'user', 'content': [
                    {'type': 'input_text', 'text': 'next'}]}]
            payload = prepare_tools(payload)[0]
            # A group after the marker is native and receives no note.
            self.assertEqual([item.get('type') for item in payload['input']],
                             ['apply_patch_call', 'apply_patch_call_output',
                              'message', 'message', 'message'])
            self.assertIn('search call itself is omitted',
                          payload['input'][2]['content'][0]['text'])
            self.assertEqual(payload['input'][3], marker)
            self.assertEqual(payload['input'][4]['content'][0]['text'], 'next')

        @staticmethod
        def _marker(text='<model_switch> hop'):
            return {'type': 'message', 'role': 'developer', 'content': [
                {'type': 'input_text', 'text': text}]}

        def test_items_after_the_last_marker_replay_natively(self):
            # The boundary rule end to end: foreign reasoning before the
            # marker is dropped, the current model's own reasoning after it
            # reaches the wire (blob stripped, text kept). Proven to fail on
            # 48c00a0, where both items were dropped.
            payload = {'model': 'deepseek/deepseek-v4.1-flash',
                       'tools': [{'type': 'function', 'name': 'exec',
                                  'parameters': {'type': 'object'}}],
                       'input': [dict(self._reasoning_item(), id='rs_foreign'),
                                 self._marker(),
                                 dict(self._reasoning_item(), id='rs_native')]}
            provider = ExternalResponsesProvider(provider_defs.OPENROUTER)
            prepared = provider.prepare(payload['model'], '/responses', payload,
                                        json.dumps(payload).encode(), {}, stub_credentials())
            carried = [i for i in json.loads(prepared.body)['input']
                       if i.get('type') == 'reasoning']
            self.assertEqual([i.get('id') for i in carried], ['rs_native'])
            self.assertNotIn('encrypted_content', carried[0])
            self.assertEqual(carried[0]['content'],
                             [{'type': 'reasoning_text', 'text': 'prior model thinking'}])

        def test_double_switch_uses_the_last_marker(self):
            payload = self._history_payload('deepseek/deepseek-v4.1-flash')
            payload['input'] = [dict(self._reasoning_item(), id='rs_first'),
                                self._marker('<model_switch> one'),
                                dict(self._reasoning_item(), id='rs_second'),
                                self._marker('<model_switch> two'),
                                dict(self._reasoning_item(), id='rs_native')]
            payload = prepare_tools(payload)[0]
            self.assertEqual(
                [i.get('id') for i in payload['input'] if i.get('type') == 'reasoning'],
                ['rs_native'])

        def test_portable_row_still_rewrites_everything(self):
            payload = self._history_payload()
            payload['input'] = [dict(self._reasoning_item(), id='rs_before'),
                                self._marker(),
                                dict(self._reasoning_item(), id='rs_after')]
            payload = prepare_tools(payload)[0]
            self.assertEqual(
                [i for i in payload['input'] if i.get('type') == 'reasoning'], [])

        def test_marker_inside_a_tool_run_keeps_the_run_whole(self):
            # The marker splits a parallel group's calls from their outputs;
            # the boundary moves back to the group's first call, so every
            # call keeps its output and nothing is rewritten.
            search_output = {'type': 'tool_search_output', 'call_id': 's9',
                             'execution': 'client', 'status': 'completed', 'tools': []}
            payload = self._history_payload('deepseek/deepseek-v4.1-flash')
            payload['input'] = [
                {'type': 'function_call', 'name': 'exec', 'call_id': 'c0',
                 'arguments': '{"value":"a"}'},
                {'type': 'tool_search_call', 'call_id': 's9', 'execution': 'client',
                 'arguments': {'query': 'echo'}},
                self._marker(),
                {'type': 'function_call_output', 'name': 'exec', 'call_id': 'c0', 'output': 'a'},
                search_output]
            payload = prepare_tools(payload)[0]
            kinds = [(i.get('type'), i.get('name')) for i in payload['input']]
            self.assertEqual(kinds, [('function_call', 'exec'),
                                     ('function_call', SEARCH_NAME),
                                     ('message', None),
                                     ('function_call_output', 'exec'),
                                     ('function_call_output', None)])
            # Known limit, pinned: a reasoning item between the group's first
            # call and the marker lands on the native side with its blob
            # stripped at the wire (see test_items_after_the_last_marker).
            payload2 = self._history_payload('deepseek/deepseek-v4.1-flash')
            payload2['input'] = [
                {'type': 'function_call', 'name': 'exec', 'call_id': 'c0',
                 'arguments': '{"value":"a"}'},
                dict(self._reasoning_item(), id='rs_straddle'),
                self._marker(),
                {'type': 'function_call_output', 'name': 'exec', 'call_id': 'c0', 'output': 'a'}]
            payload2 = prepare_tools(payload2)[0]
            self.assertEqual(
                [i.get('id') for i in payload2['input'] if i.get('type') == 'reasoning'],
                ['rs_straddle'])

        def test_marker_straddle_with_discovery_call_first_keeps_no_orphan(self):
            # The straddle variant with the discovery call issued before the
            # parallel call: the boundary moves back past both calls, so the
            # discovery output on the native side keeps its mate.
            payload = self._history_payload('deepseek/deepseek-v4.1-flash')
            payload['input'] = [
                {'type': 'tool_search_call', 'call_id': 's1', 'execution': 'client',
                 'arguments': {'query': 'echo'}},
                {'type': 'function_call', 'name': 'exec', 'call_id': 'c0',
                 'arguments': '{"value":"a"}'},
                self._marker(),
                {'type': 'function_call_output', 'name': 'exec', 'call_id': 'c0', 'output': 'a'},
                {'type': 'tool_search_output', 'call_id': 's1', 'execution': 'client',
                 'status': 'completed', 'tools': []}]
            payload = prepare_tools(payload)[0]
            kinds = [(i.get('type'), i.get('name')) for i in payload['input']]
            self.assertEqual(kinds, [('function_call', SEARCH_NAME),
                                     ('function_call', 'exec'),
                                     ('message', None),
                                     ('function_call_output', 'exec'),
                                     ('function_call_output', None)])
