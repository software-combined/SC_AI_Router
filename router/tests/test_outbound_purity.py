"""Plan 183 phase 3: preparing a request never edits the client's payload.

Every outgoing stage builds new lists and copies only the dictionaries it
changes, so one original payload prepares again, on either route, with the
same wire body and tool metadata. The opt-in helper fallback relies on that:
the native attempt prepares first, and the external twin prepares later
from the same payload and the request's captured target context.
"""
import copy
import json
import unittest
from unittest import mock

from ai_router import provider_defs, request_context, subscription_fallback, turn_budget
from ai_router.image_items import IMAGE_TRIM_NOTE
from ai_router.providers import ExternalResponsesProvider, SubscriptionProvider
from tests.fakes import FakeUpstream, install_fake
from tests.harness import (StubCredentials, auth_file, isolated_home, post, start_server,
                           stub_credentials, test_state)
from tests.test_agent_handoffs import native_tools
from tests.test_replay_golden import EXPECTED, FIXTURES, golden_name

NATIVE = 'subscription:gpt-6-astra'
EXTERNAL = 'external:deepseek/deepseek-v4.1-flash-1017'
HELPER = 'gpt-5.6-luna'
HELPER_HEADERS = {'x-codex-turn-metadata': json.dumps({'thread_source': 'thread_title'})}


def _fixtures():
    for path in sorted(FIXTURES.glob('*.json')):
        yield path.stem, json.loads(path.read_text(encoding='utf-8'))


def _prepare(target, payload, context=None):
    """(wire bytes, tool metadata) for `payload` as sent, or the refusal text."""
    route, slug = target.split(':', 1)
    try:
        if route == 'subscription':
            prepared = SubscriptionProvider().prepare(
                slug, '/responses', payload, json.dumps(payload).encode(), {}, StubCredentials(),
                context=context)
        else:
            prepared = ExternalResponsesProvider(provider_defs.OPENROUTER).prepare(
                slug, '/responses', payload, b'', {}, stub_credentials(), context=context)
    except ValueError as exc:
        return f'{type(exc).__name__}: {exc}', None
    names = prepared.tool_names
    handoffs = names if isinstance(names, frozenset) else getattr(names, 'handoffs', None)
    return prepared.body, (
        dict(names) if isinstance(names, dict) else None,
        sorted(getattr(names, 'reserved', ())), sorted(getattr(names, 'dropped', ())),
        sorted(handoffs or ()), getattr(handoffs, 'stream', None),
        getattr(handoffs, 'spawn_models', None))


def _client(payload, target):
    return dict(copy.deepcopy(payload), model=target.split(':', 1)[1])


class FixturePurityTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        isolated_home(self)

    def test_every_fixture_leaves_the_client_payload_unchanged_on_both_routes(self):
        for stem, fixture in _fixtures():
            for target in dict.fromkeys([*fixture['targets'], NATIVE, EXTERNAL]):
                with self.subTest(fixture=stem, target=target):
                    client = _client(fixture['payload'], target)
                    before = copy.deepcopy(client)
                    body, _meta = _prepare(target, client)
                    self.assertEqual(client, before)
                    if target not in fixture['targets']:
                        continue
                    expected = json.loads((EXPECTED / golden_name(stem, target)).read_text())
                    if 'error' in expected:
                        self.assertEqual(body, expected['error'])
                    else:
                        self.assertEqual(json.loads(body), expected['wire'])

    def test_repeated_same_route_preparation_from_the_original_is_identical(self):
        for stem, fixture in _fixtures():
            for target in (NATIVE, EXTERNAL):
                with self.subTest(fixture=stem, target=target):
                    client = _client(fixture['payload'], target)
                    self.assertEqual(_prepare(target, client), _prepare(target, client))

    def test_native_then_external_matches_a_fresh_external_preparation(self):
        for stem, fixture in _fixtures():
            with self.subTest(fixture=stem):
                client = _client(fixture['payload'], NATIVE)
                _prepare(NATIVE, client)
                twin = dict(client, model=EXTERNAL.split(':', 1)[1])
                self.assertEqual(_prepare(EXTERNAL, twin),
                                 _prepare(EXTERNAL, _client(fixture['payload'], EXTERNAL)))

    def test_an_unchanged_native_body_keeps_the_clients_bytes(self):
        client = {'model': 'gpt-6-astra', 'input': [
            {'type': 'message', 'role': 'user', 'content': 'hello'}]}
        raw = b'\x28\xb5\x2f\xfd compressed client bytes'
        prepared = SubscriptionProvider().prepare(
            'gpt-6-astra', '/responses', client, raw, {'Content-Encoding': 'zstd'}, None)
        self.assertIs(prepared.body, raw)
        self.assertEqual(prepared.headers, {'Content-Encoding': 'zstd'})


class HelperFallbackReuseTests(unittest.TestCase):
    """The native attempt, then the twin, from one original helper payload."""

    def setUp(self):
        isolated_home(self)

    def _payload(self, tools):
        return {'model': HELPER, 'stream': True, 'tools': tools,
                'input': [{'type': 'message', 'role': 'user', 'content': 'title this'}]}

    def _plan(self, payload):
        context = request_context.resolve(HELPER, request_context.capture())
        native = SubscriptionProvider().prepare(
            HELPER, '/responses', payload, json.dumps(payload).encode(), {}, StubCredentials(),
            context=context)
        target = request_context.retarget(
            context, subscription_fallback.twin_slug(HELPER, context.catalogue))
        return native, subscription_fallback.Plan(
            target, '/responses', payload, b'', {}, stub_credentials())

    def test_twin_prepares_after_the_native_attempt_from_the_same_payload(self):
        payload = self._payload(native_tools('spawn_agent', 'send_message'))
        before = copy.deepcopy(payload)
        native, plan = self._plan(payload)
        self.assertEqual(sorted(native.tool_names), ['send_message', 'spawn_agent'])
        twin = plan.prepared()
        self.assertEqual(payload, before)
        fresh = dict(copy.deepcopy(before), model=plan.target.slug)
        self.assertEqual(twin.body, _prepare('external:' + plan.target.slug, fresh,
                                             plan.target)[0])
        sent = [tool['name'] for tool in json.loads(twin.body)['tools']]
        self.assertEqual(sent, ['collaboration__spawn_agent', 'collaboration__send_message'])


def _read_turn(outputs):
    """A realistic read loop: matched function call/output pairs per output."""
    items = [{'type': 'message', 'role': 'user', 'content': 'read the logs'}]
    for index, output in enumerate(outputs):
        items += [{'type': 'function_call', 'call_id': f'c{index}', 'name': 'read',
                   'arguments': json.dumps({'path': f'log{index}.txt'})},
                  {'type': 'function_call_output', 'call_id': f'c{index}', 'output': output}]
    return {'model': EXTERNAL.split(':', 1)[1], 'input': items, 'tools': [
        {'type': 'function', 'name': 'read', 'description': 'Read a file.',
         'parameters': {'type': 'object', 'properties': {'path': {'type': 'string'}}}}]}


def _image(index):
    return {'type': 'input_image', 'detail': 'high',
            'image_url': 'data:image/png;base64,' + str(index) * 2000}


class SizeFitPurityTests(unittest.TestCase):
    """The last-resort size fit trims a copy; the client's history stays whole."""

    def setUp(self):
        isolated_home(self)

    def _fit(self, payload):
        before = copy.deepcopy(payload)
        with mock.patch.object(turn_budget, 'BODY_BUDGET', 10000):
            body, _meta = _prepare(EXTERNAL, payload)
        self.assertEqual(payload, before)
        return json.loads(body)['input']

    def test_oversized_tool_outputs_trim_on_the_wire_only(self):
        text = 'synthetic-output-' * 4000
        wire = self._fit(_read_turn([text] * 3))
        outputs = [item['output'] for item in wire if item['type'] == 'function_call_output']
        trimmed = (text[:turn_budget.OUTPUT_HEAD] + turn_budget.OUTPUT_TRIM_NOTE
                   + text[-turn_budget.OUTPUT_TAIL:])
        self.assertEqual(outputs, [trimmed, text, text])

    def test_nested_images_trim_on_the_wire_only(self):
        payload = _read_turn([[{'type': 'input_text', 'text': 'screenshot'}, _image(0)]])
        payload['input'] += [{'type': 'message', 'role': 'user', 'content': [
            {'type': 'input_text', 'text': f'shot {index}'}, _image(index)]}
            for index in range(1, 7)]
        wire = self._fit(payload)
        blocks = wire[2]['output'] + [block for item in wire[3:] for block in item['content']]
        note = {'type': 'input_text', 'text': IMAGE_TRIM_NOTE}
        self.assertEqual(blocks[1::2], [note, note, note, *map(_image, range(3, 7))])
        self.assertEqual(blocks[::2], [{'type': 'input_text', 'text': 'screenshot'}]
                         + [{'type': 'input_text', 'text': f'shot {index}'}
                            for index in range(1, 7)])


class RoutedHelperFallbackTests(unittest.TestCase):
    def test_refused_helper_turn_with_native_collaboration_tools_reaches_the_twin(self):
        answers = [(429, b'{}', []),
                   (200, b'{"output": [], "model": "openai/gpt-6-luna"}',
                    [('Content-Type', 'application/json')])]
        recorded = install_fake(self, lambda: FakeUpstream(*answers.pop(0)))
        state = test_state(auth_file(self))
        state.update(openai_models=['gpt-6-luna'], openai_helper_fallback=True)
        server = start_server(state)
        self.addCleanup(server.shutdown)
        payload = {'model': HELPER, 'tools': native_tools('spawn_agent', 'send_message'),
                   'input': [{'type': 'message', 'role': 'user', 'content': 'title this'}]}
        response = post(server.server_port, '/test-token/responses', payload, HELPER_HEADERS)
        self.assertEqual(response.status, 200)
        response.read()
        self.assertEqual([call[0] for call in recorded], ['chatgpt.com', 'openrouter.ai'])
        native = json.loads(recorded[0][3])['tools']
        self.assertEqual([tool['name'] for tool in native], ['collaboration_plaintext'])
        twin = [tool['name'] for tool in json.loads(recorded[1][3])['tools']]
        self.assertEqual(twin, ['collaboration__spawn_agent', 'collaboration__send_message'])


if __name__ == '__main__':
    unittest.main()
