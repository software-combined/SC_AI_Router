"""Namespaced tool alias resilience (Plan 145).

Readable namespace__tool aliases, repair of damaged names, unsupported-call
guidance, content-free repair logging, the handler path, and the upstream hint.
"""
import hashlib
import json
import unittest
from unittest import mock

from ai_router import tool_aliases, upstream
from ai_router.tool_adapter import ToolEvents
from tests.fakes import FakeUpstream, install_fake
from tests.harness import auth_file, post, start_server, test_state
from tests.tool_stages import prepare_tools


def _namespaced(namespace, *names):
    tools = [{'type': 'function', 'name': name, 'description': name,
              'parameters': {'type': 'object'}} for name in names]
    return [{'type': 'namespace', 'name': namespace, 'tools': tools}]


def _prepare(namespace, *names):
    payload = {'model': 'z-ai/glm-5.3', 'tools': _namespaced(namespace, *names),
               'input': []}
    return prepare_tools(payload), payload


def _call(name, **extra):
    item = {'type': 'function_call', 'id': 'fc1', 'call_id': 'c1',
            'name': name, 'arguments': '{}'}
    item.update(extra)
    return item


class AliasSchemeTests(unittest.TestCase):
    def test_scheme_helpers(self):
        first = tool_aliases.fallback('probe', 'echo')
        self.assertEqual(tool_aliases.LIMIT, 64)
        self.assertEqual(first, tool_aliases.fallback('probe', 'echo'))
        self.assertRegex(first, r'^probe__echo_[0-9a-f]{12}$')
        self.assertLessEqual(len(first), 64)
        self.assertNotEqual(first, tool_aliases.fallback('probe', 'echo2'))
        self.assertEqual(tool_aliases.readable('probe', 'echo'), 'probe__echo')
        self.assertIsNone(tool_aliases.readable('n' * 40, 't' * 40))

    def test_readable_alias_and_reverse_map(self):
        names, payload = _prepare('probe', 'echo')
        self.assertEqual(payload['tools'][0]['name'], 'probe__echo')
        back = ToolEvents(names).item(_call('probe__echo'))
        self.assertEqual((back.get('namespace'), back.get('name')), ('probe', 'echo'))

    def test_collision_falls_back_to_a_disambiguated_stem(self):
        names, payload = _prepare('probe', 'a.b', 'a_b')
        wires = sorted(tool['name'] for tool in payload['tools'])
        self.assertEqual(len(set(wires)), 2)
        for wire in wires:
            self.assertRegex(wire, r'^probe__a_b_[0-9a-f]{12}$')
            back = ToolEvents(names).item(_call(wire))
            self.assertEqual(back.get('namespace'), 'probe')
            self.assertIn(back.get('name'), ('a.b', 'a_b'))

    def test_over_length_falls_back_to_a_truncated_stem(self):
        namespace, name = 'n' * 40, 't' * 40
        names, payload = _prepare(namespace, name)
        wire = payload['tools'][0]['name']
        self.assertTrue(wire.startswith(namespace + '__'))
        self.assertLessEqual(len(wire), 64)
        back = ToolEvents(names).item(_call(wire))
        self.assertEqual((back.get('namespace'), back.get('name')), (namespace, name))

    def test_native_and_dotted_names_are_repaired(self):
        names, _ = _prepare('probe', 'echo')
        for called in ('echo', 'probe.echo'):
            with self.subTest(called=called):
                back = ToolEvents(names).item(_call(called))
                self.assertEqual((back.get('namespace'), back.get('name')),
                                 ('probe', 'echo'))

    def test_near_miss_readable_alias_is_repaired(self):
        names, _ = _prepare('alpha', 'send_message')
        with mock.patch('ai_router.tool_aliases.log_event') as logged:
            back = ToolEvents(names, {'model': 'm'}).item(_call('alpha__send_messag'))
        self.assertEqual((back.get('namespace'), back.get('name')),
                         ('alpha', 'send_message'))
        causes = [call.kwargs['cause'] for call in logged.call_args_list
                  if call.args[0] == 'tool_call_repaired']
        self.assertEqual(causes, ['near'])

    def test_near_miss_is_never_guessed_between_two_aliases(self):
        names, _ = _prepare('probe', 'echo', 'echa')
        self.assertEqual(len(tool_aliases.candidates(names, 'probe__ech')), 2)
        self.assertIsNone(tool_aliases.repair(names, 'probe__ech'))
        back = ToolEvents(names).item(_call('probe__ech'))
        self.assertEqual(back['name'], 'probe__ech')
        self.assertNotIn('namespace', back)

    def test_near_miss_never_targets_a_digest_alias(self):
        names, payload = _prepare('probe', 'a.b', 'a_b')
        for tool in payload['tools']:
            self.assertRegex(tool['name'], r'^probe__a_b_[0-9a-f]{12}$')
        back = ToolEvents(names).item(_call('probe__echo'))
        self.assertEqual(back['name'], 'probe__echo')
        self.assertNotIn('namespace', back)

    def test_delivered_hint_does_not_stack_on_repreparation(self):
        names, _ = _prepare('probe', 'echo')
        once = tool_aliases.annotate('unsupported call: delivered_message', names)
        self.assertEqual(tool_aliases.annotate(once, names), once)
        self.assertEqual(once.count('That name marks a message'), 1)

    def test_delivered_name_gets_the_delivered_hint(self):
        names, _ = _prepare('probe', 'echo')
        output = tool_aliases.annotate('unsupported call: delivered_message', names)
        self.assertIn(tool_aliases.HINT_DELIVERED, output)
        self.assertNotIn('probe__echo', output)
        with mock.patch('ai_router.tool_aliases.log_event') as logged:
            ToolEvents(names, {'model': 'm'}).item(_call('delivered_message'))
        causes = [call.kwargs['cause'] for call in logged.call_args_list
                  if call.args[0] == 'tool_call_unresolved']
        self.assertEqual(causes, ['delivered'])

    def test_damaged_fallback_name_is_repaired(self):
        # The incident shape: a tool exposed under the fallback, re-typed
        # with one character dropped from the digest.
        names, payload = _prepare('probe', 'a.b', 'a_b')
        for tool in payload['tools']:
            damaged = tool['name'][:-1]
            with self.subTest(damaged=damaged):
                back = ToolEvents(names).item(_call(damaged))
                self.assertEqual(back.get('namespace'), 'probe')
                self.assertIn(back.get('name'), ('a.b', 'a_b'))

    def test_typos_and_unrelated_names_are_left_to_the_client(self):
        names, _ = _prepare('probe', 'echo')
        for called in ('foo_echo', 'my_echo',
                       'ns_deadbeefcafe_echo', 'probe__ecnaa'):
            with self.subTest(called=called):
                back = ToolEvents(names).item(_call(called))
                self.assertEqual(back['name'], called)
                self.assertNotIn('namespace', back)

    def test_namespaced_item_is_left_to_the_client(self):
        # A call that already carries a namespace is the client's own shape;
        # the router must never rewrite it to a same-named sibling.
        names, _ = _prepare('beta', 'send_message')
        item = _call('send_message', namespace='alpha')
        back = ToolEvents(names).item(item)
        self.assertEqual((back.get('namespace'), back.get('name')), ('alpha', 'send_message'))

    def test_dropped_namesake_is_not_substituted(self):
        payload = {'model': 'z-ai/glm-5.3',
                   'tools': _namespaced('gamma', 'send_message')
                            + _namespaced('delta', 'send_message'),
                   'input': []}
        names = prepare_tools(payload)
        dropped = [key for key in names if names[key].get('name') == 'send_message'][0]
        names.pop(dropped)
        names.dropped.add('send_message')  # the ceiling withheld that native name
        back = ToolEvents(names).item(_call('send_message'))
        self.assertEqual(back['name'], 'send_message')
        self.assertNotIn('namespace', back)

    def test_ceiling_bookkeeping_withholds_a_dropped_namesake(self):
        # grok's 350-tool ceiling keeps the search tool and released tools and
        # drops declared ones; the dropped native name must block substitution.
        released = {'type': 'namespace', 'name': 'gamma', 'tools': [
            {'type': 'function', 'name': 'send_message', 'description': 'g',
             'parameters': {'type': 'object'}}]}
        declared = {'type': 'namespace', 'name': 'delta', 'tools': [
            {'type': 'function', 'name': 'send_message', 'description': 'd',
             'parameters': {'type': 'object'}}]}
        payload = {'model': 'x-ai/grok-4.7',
            'tools': [{'type': 'tool_search', 'description': 's',
                       'parameters': {'type': 'object', 'properties': {}}}, declared] + [
                {'type': 'function', 'name': f'unrelated_{i}',
                 'parameters': {'type': 'object'}} for i in range(400)],
            'input': [{'type': 'tool_search_output', 'call_id': 's1', 'tools': [released]}]}
        names = prepare_tools(payload)
        self.assertIn('gamma__send_message', [tool['name'] for tool in payload['tools']])
        self.assertIn('send_message', names.dropped)
        back = ToolEvents(names).item(_call('send_message'))
        self.assertEqual(back['name'], 'send_message')
        self.assertNotIn('namespace', back)

    def test_fallback_names_stay_unique_when_a_stem_collides(self):
        long_name = 'x' * 70
        digest = hashlib.sha256(('probe\0' + long_name).encode()).hexdigest()[:12]
        names, payload = _prepare('probe', 'x' * 44 + '_' + digest, long_name)
        wires = [tool['name'] for tool in payload['tools']]
        self.assertEqual(len(set(wires)), 2)
        for wire in wires:
            self.assertLessEqual(len(wire), 64)
            back = ToolEvents(names).item(_call(wire))
            self.assertEqual(back.get('namespace'), 'probe')

    def test_exhausted_fallback_ladder_fails_closed(self):
        # A crafted readable alias can occupy every widened fallback slot; the
        # router must refuse the request rather than send two tools under one
        # name, which would silently re-target calls to the last registration.
        namespace, victim = 'probe', 'z' * 70
        blocked = [tool_aliases.fallback(namespace, victim, width)[len(namespace) + 2:]
                   for width in (12, 16, 20, 24, 32, 48)]
        payload = {'model': 'z-ai/glm-5.3',
                   'tools': _namespaced(namespace, *blocked, victim), 'input': []}
        with self.assertRaisesRegex(ValueError, 'unique wire name'):
            prepare_tools(payload)

    def test_stale_readable_twin_is_not_retargeted(self):
        # A readable alias whose last segment looks like a digest (two twins
        # one hex character apart) must not be repaired onto the survivor when
        # the tool the model named is no longer exposed.
        absent, present = 'job_a1b2c3d4e5f6', 'job_a1b2c3d4e5f7'
        names, payload = _prepare('probe', present)
        self.assertEqual(payload['tools'][0]['name'], 'probe__' + present)
        back = ToolEvents(names).item(_call('probe__' + absent))
        self.assertEqual(back['name'], 'probe__' + absent)
        self.assertNotIn('namespace', back)

    def test_top_level_name_is_never_repaired_or_counted(self):
        top = {'type': 'function', 'name': 'echo', 'description': 'top',
               'parameters': {'type': 'object'}}
        payload = {'model': 'z-ai/glm-5.3',
                   'tools': [top] + _namespaced('probe', 'echo'), 'input': []}
        names = prepare_tools(payload)
        with mock.patch('ai_router.tool_aliases.log_event') as logged:
            back = ToolEvents(names, {'model': 'z-ai/glm-5.3'}).item(_call('echo'))
        self.assertEqual(back['name'], 'echo')
        self.assertNotIn('namespace', back)
        self.assertEqual(logged.call_count, 0)

    def test_dropped_wire_name_is_not_repaired(self):
        names, payload = _prepare('probe', 'echo')
        wire = payload['tools'][0]['name']
        names.pop((None, wire))  # the tool ceiling dropped it this turn
        back = ToolEvents(names).item(_call(wire))
        self.assertEqual(back['name'], wire)
        self.assertNotIn('namespace', back)

    def test_ambiguous_plain_name_is_left_untouched(self):
        payload = {'model': 'z-ai/glm-5.3',
                   'tools': _namespaced('alpha', 'echo') + _namespaced('beta', 'echo'),
                   'input': []}
        names = prepare_tools(payload)
        back = ToolEvents(names).item(_call('echo'))
        self.assertEqual(back['name'], 'echo')
        self.assertNotIn('namespace', back)


class GuidanceTests(unittest.TestCase):
    def _output(self, text):
        payload = {'model': 'z-ai/glm-5.3', 'tools': _namespaced('probe', 'echo'),
                   'input': [{'type': 'function_call_output', 'call_id': 'c1',
                              'output': text}]}
        prepare_tools(payload)
        return payload['input'][0]['output']

    def test_damaged_name_gains_exact_alias(self):
        output = self._output('unsupported call: probe.echo')
        self.assertTrue(output.startswith('unsupported call: probe.echo\n'))
        self.assertIn('probe__echo', output)

    def test_unknown_name_gains_generic_sentence(self):
        output = self._output('unsupported call: nope')
        self.assertIn('Re-read the tool list and copy an exact name.', output)
        self.assertNotIn('probe__echo', output)

    def test_other_output_is_byte_identical(self):
        self.assertEqual(self._output('all good'), 'all good')

    def test_hint_is_not_stacked_when_prepared_twice(self):
        payload = {'model': 'z-ai/glm-5.3', 'tools': _namespaced('probe', 'echo'),
                   'input': [{'type': 'function_call_output', 'call_id': 'c1',
                              'output': 'unsupported call: probe__ech'}]}
        prepare_tools(payload)
        once = payload['input'][0]['output']
        prepare_tools(payload)
        self.assertEqual(payload['input'][0]['output'], once)
        self.assertEqual(once.count('No tool with that exact name'), 1)


class LoggingTests(unittest.TestCase):
    def test_repair_and_unresolved_log_once_with_model_only(self):
        names, payload = _prepare('probe', 'x' * 70)
        wire = payload['tools'][0]['name']
        adapter = ToolEvents(names, {'model': 'z-ai/glm-5.3'})
        repaired = _call(wire[:-1])
        unknown = _call('nope', id='fc2', call_id='c2')
        with mock.patch('ai_router.tool_aliases.log_event') as logged:
            for _ in range(2):
                adapter.event({'type': 'response.output_item.added',
                               'item': {**repaired, 'arguments': ''}})
                adapter.event({'type': 'response.output_item.done',
                               'item': dict(repaired)})
                adapter.event({'type': 'response.completed',
                               'response': {'model': 'served',
                                            'output': [dict(repaired), dict(unknown)]}})
        self.assertEqual(logged.call_count, 2)
        events = {call.args[0]: call.kwargs for call in logged.call_args_list}
        self.assertEqual(set(events), {'tool_call_repaired', 'tool_call_unresolved'})
        self.assertEqual(events['tool_call_repaired']['cause'], 'digest')
        self.assertEqual(events['tool_call_unresolved']['cause'], 'unknown')
        for kwargs in events.values():
            self.assertEqual(set(kwargs), {'model', 'cause'})
            self.assertEqual(kwargs['model'], 'z-ai/glm-5.3')


class HandlerPathTests(unittest.TestCase):
    def test_damaged_alias_is_repaired_end_to_end(self):
        name = 'x' * 70
        alias = tool_aliases.fallback('probe', name)
        item = {'id': 'item1', 'type': 'function_call', 'call_id': 'call1',
                'name': alias[:-1], 'arguments': '{}'}
        wire = (b'data: ' + json.dumps(
            {'type': 'response.output_item.done', 'item': item}).encode() + b'\n\n')
        install_fake(self, lambda: FakeUpstream(
            200, wire, [('Content-Type', 'text/event-stream')]))
        server = start_server(test_state(auth_file(self)))
        self.addCleanup(server.shutdown)
        response = post(server.server_port, '/test-token/responses',
            {'model': 'z-ai/glm-5.3',
             'input': [{'type': 'message', 'role': 'user', 'content': 'hi'}],
             'tools': _namespaced('probe', name)})
        self.assertEqual(response.status, 200)
        body = response.read()
        self.assertNotIn(alias[:-1].encode(), body)
        seen = [json.loads(block[6:]) for block in body.split(b'\n\n')
                if block.startswith(b'data:')]
        done = [event for event in seen
                if event.get('type') == 'response.output_item.done']
        self.assertEqual(len(done), 1)
        self.assertEqual(done[0]['item']['namespace'], 'probe')
        self.assertEqual(done[0]['item']['name'], name)


class UpstreamHintTests(unittest.TestCase):
    def test_schema_rejection_message_names_no_tool(self):
        raw = ('{"code": "invalid-argument", "error": "Failed to start sampling: '
               '[invalid_client_tool_schema] probe__echo: tool parameter '
               'root must be an object type"}')
        body = json.dumps({'error': {'message': 'Provider returned error',
                                     'metadata': {'raw': raw, 'provider_name': 'xAI'}}})
        status, message, _ = upstream.describe_failure(
            None, {'status': 400, 'body': body.encode()},
            {'model': 'x-ai/grok-4.7', 'provider': 'openrouter', 'protocol': 'responses',
             'elapsed_ms': 1831.8, 'timeout_s': 120, 'has_image': False})
        self.assertEqual(status, 400)
        self.assertNotIn('probe__echo', message)
        self.assertIn('tool schema was rejected', message)


if __name__ == '__main__':
    unittest.main()
