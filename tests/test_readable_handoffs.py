"""Mixed installs carry every brief readably; Codex executes the canonical tools.

A native request on an install where an external key resolves hides the
canonical handoff tools, whose message the backend requires to stay encrypted,
and offers readable copies in the plaintext namespace wherever Codex declares
them. The response returns each call to its canonical name with the plaintext
marker. External routes rewrite the canonical tools in place, and an install
without an external key keeps the stock encrypted contract.
"""
from copy import deepcopy
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from ai_router import agent_handoffs as handoffs, errors, provider_defs, request_context, sse
from ai_router.providers import ExternalResponsesProvider, SubscriptionProvider
from ai_router.tool_merge import tool_entries
from tests.harness import stub_credentials
from tests.test_agent_handoff_providers import Response
from tests.test_agent_handoffs import CIPHERTEXT, KEY, NO_KEY, native_tools

PARENT, CHILD = 'gpt-6-astra', 'deepseek/deepseek-v4.1-flash'
HANDOFFS = sorted(handoffs.HANDOFF_TOOLS)
ALIAS = 'collaboration_plaintext'


def declared(location, tools=None):
    tools = native_tools(*HANDOFFS) if tools is None else tools
    if location == 'classic':
        return {'model': PARENT, 'tools': tools, 'input': []}
    if location == 'lite':
        return {'model': PARENT, 'input': [{'type': 'additional_tools', 'role': 'developer',
                                            'id': 'at_client', 'tools': tools}]}
    return {'model': PARENT, 'tools': [{'type': 'tool_search', 'parameters': {'type': 'object'}}],
            'input': [{'type': 'tool_search_call', 'call_id': 's1', 'execution': 'client',
                       'arguments': {'query': 'collaboration'}},
                      {'type': 'tool_search_output', 'call_id': 's1', 'execution': 'client',
                       'tools': tools}]}


def native(payload, credentials=KEY):
    context = request_context.resolve(PARENT, request_context.capture())
    return SubscriptionProvider().prepare(PARENT, '/responses', payload, json.dumps(payload).encode(),
                                          {}, credentials, context=context)


def adapt(prepared, raw, content_type='text/event-stream'):
    return b''.join(SubscriptionProvider().adapt(Response(raw, content_type), prepared.tool_names))


def tools_in(body, namespace):
    lists = [body.get('tools', []), *(item.get('tools', []) for item in body.get('input', []))]
    return [tool for tools in lists for tool, ns in tool_entries(tools) if ns == namespace]


def frames(*events):
    return b''.join(sse.frame(json.dumps(event).encode()) for event in events)


def call(name, child=CHILD, **changes):
    return {'type': 'function_call', 'namespace': ALIAS, 'name': name,
            'id': 'fc_' + name, 'call_id': 'call_' + name, 'arguments': json.dumps(
                {'task_name': 'plain', 'target': 'plain', 'model': child,
                 'message': 'SYNTH_BRIEF\nKeep this scope.', 'count': 8.0}), **changes}


def restored(item):
    return {**item, 'namespace': 'collaboration', 'encrypted_function_args': []}


class NativeRequestTests(unittest.TestCase):
    def test_keyed_installs_offer_only_readable_aliases_in_every_location(self):
        for location in ('classic', 'lite', 'discovered'):
            with self.subTest(location=location):
                payload = declared(location)
                before = deepcopy(payload)
                prepared = native(payload)
                self.assertEqual(payload, before)
                self.assertEqual(prepared.tool_names, handoffs.HANDOFF_TOOLS)
                self.assertEqual(prepared.tool_names.location, location)
                body = json.loads(prepared.body)
                self.assertEqual(tools_in(body, 'collaboration'), [])
                aliases = tools_in(body, ALIAS)
                self.assertEqual(sorted(tool['name'] for tool in aliases), HANDOFFS)
                for tool in aliases:
                    self.assertEqual(tool['parameters']['properties']['message'],
                                     {'type': 'string', 'encrypted': False,
                                      'description': handoffs.READABLE_MESSAGE})
                if location == 'lite':
                    prefix = body['input'][0]
                    self.assertTrue(prefix['id'].startswith('at_'))
                    self.assertNotEqual(prefix['id'], 'at_client')
                    self.assertEqual(json.loads(native(deepcopy(before)).body)['input'][0], prefix)

    def test_an_install_without_an_external_key_is_stock_end_to_end(self):
        for location, credentials in (('classic', NO_KEY), ('lite', NO_KEY), ('classic', None),
                                      ('classic', stub_credentials())):
            with self.subTest(location=location, credentials=credentials):
                payload = declared(location)
                prepared = native(payload, credentials)
                self.assertFalse(prepared.tool_names)
                self.assertEqual(json.loads(prepared.body), handoffs.hint_full_lanes(payload))
                self.assertNotIn(ALIAS.encode(), prepared.body)
                for tool in tools_in(json.loads(prepared.body), 'collaboration'):
                    self.assertIs(tool['parameters']['properties']['message']['encrypted'], True)
                item = call('spawn_agent', namespace='collaboration')
                raw = frames({'type': 'response.output_item.done', 'item': item},
                             {'type': 'response.completed', 'response': {'output': [item]}})
                self.assertEqual(adapt(prepared, raw), raw)

    def test_any_resolving_external_key_makes_briefs_readable(self):
        defs = (SimpleNamespace(id='first_external'), SimpleNamespace(id='second_external'))
        second_only = SimpleNamespace(key_missing=lambda pid: None if pid == 'second_external'
                                      else LookupError('no key'))
        with mock.patch.object(provider_defs, 'external_defs', return_value=defs):
            self.assertEqual(native(declared('classic'), second_only).tool_names, handoffs.HANDOFF_TOOLS)
            self.assertFalse(native(declared('classic'), NO_KEY).tool_names)


class NativeResponseTests(unittest.TestCase):
    def test_readable_calls_reach_codex_under_the_canonical_name_with_the_marker(self):
        prepared = native(declared('classic'))
        created = sse.frame(b'{"type":"response.created","response":{"id":"resp_1","output":[]}}')
        # Aliases are the normal path; a model may also emit the hidden canonical name.
        for namespace in (ALIAS, 'collaboration'):
            for name, child in ((name, child) for name in HANDOFFS for child in (CHILD, 'gpt-6-sol')):
                item = call(name, child, namespace=namespace)
                raw = created + frames(
                    {'type': 'response.output_item.added', 'output_index': 0, 'item': {**item, 'arguments': ''}},
                    {'type': 'response.output_item.done', 'output_index': 0, 'item': item},
                    {'type': 'response.completed', 'response': {'id': 'resp_1', 'output': [item]}})
                with self.subTest(namespace=namespace, name=name, child=child, stream=True):
                    wire = adapt(prepared, raw)
                    self.assertTrue(wire.startswith(created))
                    events = [json.loads(data) for _, data in sse.blocks(sse.lines([wire])) if data]
                    self.assertEqual(events[1]['item'], {**restored(item), 'arguments': ''})
                    self.assertEqual(events[2]['item'], restored(item))
                    self.assertEqual(events[3]['response'], {'id': 'resp_1', 'output': [restored(item)]})
                with self.subTest(namespace=namespace, name=name, child=child, stream=False):
                    body = {'id': 'resp_1', 'model': 'synthetic-served', 'output': [item]}
                    result = json.loads(adapt(prepared, json.dumps(body).encode(), 'application/json'))
                    self.assertEqual(result, {**body, 'output': [restored(item)]})

    def test_ciphertext_or_a_marker_on_an_alias_call_is_refused(self):
        prepared = native(declared('classic'))
        for item in (call('spawn_agent', encrypted_function_args=['message']),
                     call('spawn_agent', arguments=json.dumps({'model': CHILD, 'message': CIPHERTEXT}))):
            for raw, kind in ((frames({'type': 'response.output_item.done', 'item': item}), 'text/event-stream'),
                              (json.dumps({'output': [item]}).encode(), 'application/json')):
                with self.subTest(item=item, kind=kind), self.assertRaises(errors.ResponseRejected) as caught:
                    adapt(prepared, raw, kind)
                self.assertEqual(caught.exception.detail, 'HANDOFF_READABLE_ENCRYPTED')
                self.assertNotIn('SYNTH_BRIEF', str(caught.exception))
                self.assertNotIn(CIPHERTEXT, str(caught.exception))

    def test_canonical_ciphertext_is_never_marked_and_reaches_only_a_native_child(self):
        prepared = native(declared('classic'))
        for child, refused in ((CHILD, True), ('gpt-6-sol', False)):
            item = call('spawn_agent', namespace='collaboration',
                        arguments=json.dumps({'model': child, 'message': CIPHERTEXT}))
            raw = frames({'type': 'response.output_item.done', 'item': item})
            with self.subTest(child=child):
                if refused:
                    with self.assertRaises(errors.ResponseRejected) as caught:
                        adapt(prepared, raw)
                    self.assertEqual(caught.exception.detail, 'HANDOFF_REQUIRES_PLAINTEXT')
                    self.assertNotIn(CIPHERTEXT, str(caught.exception))
                else:
                    self.assertEqual(adapt(prepared, raw), raw)


class ExternalRouteTests(unittest.TestCase):
    def test_canonical_calls_are_marked_and_no_alias_is_declared(self):
        provider = ExternalResponsesProvider(provider_defs.OPENROUTER)
        payload = {'model': CHILD, 'tools': native_tools(*HANDOFFS), 'input': []}
        prepared = provider.prepare(CHILD, '/responses', payload, b'', {}, KEY)
        self.assertEqual(sorted(tool['name'] for tool in json.loads(prepared.body)['tools']),
                         ['collaboration__' + name for name in HANDOFFS])
        self.assertEqual(prepared.tool_names.handoffs, handoffs.HANDOFF_TOOLS)
        for name in HANDOFFS:
            item = {'type': 'function_call', 'name': 'collaboration__' + name, 'id': 'fc_1',
                    'call_id': 'call_1', 'arguments': '{"target":"plain","message":"SYNTH"}'}
            source = Response(json.dumps({'output': [item]}).encode())
            result = json.loads(b''.join(provider.adapt(source, prepared.tool_names)))['output'][0]
            self.assertEqual(result, {**item, 'namespace': 'collaboration', 'name': name,
                                      'encrypted_function_args': []})


class ReplayTests(unittest.TestCase):
    def test_restored_history_replays_unchanged_on_both_routes(self):
        spawned = restored(call('spawn_agent'))
        history = [{'type': 'message', 'role': 'user', 'content': 'Delegate the synthetic task.'},
                   spawned, {'type': 'function_call_output', 'call_id': spawned['call_id'],
                             'output': 'spawned'}]
        tools = native_tools(*HANDOFFS)
        body = json.loads(native({'model': PARENT, 'tools': tools, 'input': deepcopy(history)}).body)
        self.assertEqual(body['input'], history)
        external = ExternalResponsesProvider(provider_defs.OPENROUTER).prepare(
            CHILD, '/responses', {'model': CHILD, 'tools': tools, 'input': deepcopy(history)},
            b'', {}, KEY)
        replayed = json.loads(external.body)['input']
        expected = {key: value for key, value in spawned.items() if key != 'namespace'}
        self.assertEqual(replayed[1], {**expected, 'name': 'collaboration__spawn_agent'})
        self.assertEqual(replayed[2], history[2])


if __name__ == '__main__':
    unittest.main()
