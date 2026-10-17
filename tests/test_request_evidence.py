"""Routed attempts retain identity and timing without retaining content."""
import gzip
from dataclasses import replace
import http.client
import json
import socket
import socketserver
import threading
import time
import unittest
from unittest import mock

from ai_router import outcome, providers, registry, relay, router, sse
from tests.fakes import FakeUpstream, install_fake
from tests.harness import auth_file, post, start_server, test_state
from tests.test_messages_stream_contract import ending, frame, message

CANARY = 'PRIVATE PROMPT TOOL HEADER AND ERROR CONTENT'
EXTERNAL = 'deepseek/deepseek-v4.1-flash-1017'


def event(kind, **fields):
    return sse.frame(json.dumps({'type': kind, **fields}).encode())


def setup(model, messages=False):
    return (frame('message_start', message={**message(), 'model': model}) if messages
            else event('response.created', response={'model': model, 'output': []}))


def done(model, messages=False):
    return (ending('end_turn') if messages else event('response.completed', response={
        'model': model, 'status': 'completed', 'output': [], 'reasoning': {'effort': 'low'}}))


class RequestEvidenceTests(unittest.TestCase):
    def turn(self, model, responses, messages=False, stream=True, fail_phase=None):
        replies = iter(responses)
        sends = install_fake(self, lambda: next(replies))
        if fail_phase:
            method = {'connect': 'connect', 'send': 'request', 'headers': 'getresponse'}[fail_phase]
            self.enterContext(mock.patch.object(http.client.HTTPSConnection, method,
                                                side_effect=TimeoutError(CANARY)))
        server = start_server(test_state(auth_file(self)))
        server.state['openai_models'].append('gpt-6-luna')
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        finished = threading.Event()

        class CompletionHandler(router.Handler):
            def do_POST(self):
                try:
                    super().do_POST()
                finally:
                    finished.set()

        server.RequestHandlerClass = CompletionHandler
        body = {'model': model, 'stream': stream, 'tools': []}
        body.update({'messages': [{'role': 'user', 'content': CANARY}], 'max_tokens': 128}
                    if messages else {'input': [{'role': 'user', 'content': CANARY}],
                                      'reasoning': {'effort': 'low'}})
        path = '/v1/messages' if messages else '/responses'
        with mock.patch.object(router, 'log_event') as logged:
            response = post(server.server_port, '/test-token' + path, body,
                            {'Authorization': 'Bearer ' + CANARY})
            wire = response.read()
            self.assertTrue(finished.wait(2))
        facts = [c.kwargs for c in logged.call_args_list if c.args[0] == 'attempt_ledger']
        self.assertEqual(len(facts), 1)
        self.assertEqual(server.inflight, 0)
        self.assertNotIn(CANARY, json.dumps(facts))
        self.assertNotIn(CANARY, json.dumps([c.kwargs for c in logged.call_args_list]))
        return wire, sends, facts[0]

    def response(self, wire, **kwargs):
        return FakeUpstream(kwargs.get('status', 200), wire, [
            ('Content-Type', kwargs.get('kind', 'text/event-stream')),
            ('Content-Encoding', kwargs.get('encoding', 'identity')),
            ('Authorization', CANARY)])

    def test_all_four_routes_report_the_observed_model_with_provenance(self):
        for model, messages in ((EXTERNAL, False), ('gpt-6-luna', False),
                                (EXTERNAL, True), ('claude-sonnet-5', True)):
            with self.subTest(model=model, messages=messages):
                original = setup(model, messages) + done(model, messages)
                wire, sends, facts = self.turn(model, [self.response(original)], messages)
                self.assertEqual(len(sends), 1)
                self.assertEqual(facts['outcome'], outcome.SUCCESS)
                self.assertTrue(facts['router_version'])
                attempt, = facts['attempt_evidence']
                self.assertEqual(attempt['requested_model'], model)
                self.assertEqual(attempt['upstream_model'], model)
                self.assertEqual(attempt['model_status'], 'provider_reported_match')
                self.assertEqual(attempt['model_reports'][0]['value'], model)
                self.assertEqual(attempt['model_reports'][0]['source'],
                                 'message_start.message.model' if messages
                                 else 'response.created.response.model')
                self.assertGreaterEqual(attempt['age_ms'], attempt['last_data_age_ms'])
                if model in ('gpt-6-luna', 'claude-sonnet-5'):
                    self.assertEqual(wire, original)
                else:
                    self.assertNotIn(CANARY, str(sends[0][4]))

    def test_setup_identity_survives_a_later_socket_timeout(self):
        class Interrupted(FakeUpstream):
            def read1(self, size):
                if self._pos:
                    raise TimeoutError(CANARY)
                return super().read1(size)

        response = Interrupted(200, setup('gpt-6-luna'), [('Content-Type', 'text/event-stream')])
        _, sends, facts = self.turn('gpt-6-luna', [response])
        self.assertEqual((len(sends), facts['outcome']), (1, outcome.TRANSPORT))
        attempt, = facts['attempt_evidence']
        self.assertEqual(attempt['model_status'], 'provider_reported_match')
        self.assertEqual(attempt['failure_phase'], 'read')
        self.assertEqual(attempt['error_type'], 'TimeoutError')
        self.assertEqual(attempt['timeout_s'], 120)
        self.assertTrue(attempt['committed'])

    def test_alias_keeps_requested_resolved_and_upstream_ids_separate(self):
        alias = '~fixture/model'
        row = replace(registry.by_slug(EXTERNAL), slug=alias, upstream_id=EXTERNAL)
        with mock.patch.dict(registry.BY_SLUG, {alias: row}):
            _, _, facts = self.turn(alias, [self.response(setup(EXTERNAL) + done(EXTERNAL))])
        attempt, = facts['attempt_evidence']
        self.assertEqual([attempt[k] for k in ('requested_model', 'resolved_model', 'upstream_model')],
                         [alias, alias, EXTERNAL])
        self.assertEqual(attempt['model_status'], 'provider_reported_match')

    def test_each_replay_retains_its_own_identity_and_outcome(self):
        failed = setup('unexpected-model') + event('response.failed', response={
            'status': 'failed', 'error': {'code': 'server_error', 'message': CANARY}})
        _, sends, facts = self.turn(EXTERNAL, [self.response(failed),
            self.response(setup(EXTERNAL) + done(EXTERNAL))])
        self.assertEqual(len(sends), 2)
        first, second = facts['attempt_evidence']
        self.assertEqual([first['attempt'], second['attempt']], [1, 2])
        self.assertEqual([first['reason'], second['reason']], ['initial', 'stream_replay'])
        self.assertEqual(first['model_status'], 'mismatch')
        self.assertEqual(first['outcome'], outcome.TRANSIENT)
        self.assertEqual(second['model_status'], 'provider_reported_match')
        self.assertEqual(second['outcome'], outcome.SUCCESS)

    def test_rejected_replay_reports_both_attempts_and_the_preserved_client_verdict(self):
        failed = setup(EXTERNAL) + event('response.failed', response={
            'status': 'failed', 'error': {'code': 'server_error'}})
        rejected = json.dumps({'error': {'type': 'invalid_request_error', 'message': CANARY}}).encode()
        _, sends, facts = self.turn(EXTERNAL, [self.response(failed),
            self.response(rejected, status=400, kind='application/json')])
        self.assertEqual(len(sends), 2)
        first, second = facts['attempt_evidence']
        self.assertEqual(facts['outcome'], outcome.TRANSIENT)
        self.assertEqual(first['outcome'], outcome.TRANSIENT)
        self.assertEqual(second['outcome'], outcome.REFUSED)
        self.assertEqual(second['http_status'], 400)

    def test_conflicting_reports_and_unreported_encoded_data_stay_honest(self):
        wire = setup('gpt-6-luna') + done('unexpected-model')
        _, _, facts = self.turn('gpt-6-luna', [self.response(wire)])
        attempt, = facts['attempt_evidence']
        self.assertEqual(attempt['model_status'], 'contradictory')
        compressed = gzip.compress(wire)
        actual, _, facts = self.turn('gpt-6-luna', [self.response(compressed, encoding='gzip')])
        self.assertEqual(actual, compressed)
        attempt, = facts['attempt_evidence']
        self.assertEqual(attempt['model_status'], 'unverified')
        self.assertEqual(attempt['model_reports'], [])
        self.assertEqual(attempt['effort_status'], 'unverified')

    def test_nonstream_identity_is_observed_before_tool_adaptation(self):
        for messages in (False, True):
            with self.subTest(messages=messages):
                payload = ({**message('end_turn'), 'model': EXTERNAL} if messages else
                           {'model': EXTERNAL, 'status': 'completed', 'output': []})
                wire = json.dumps(payload).encode()
                _, _, facts = self.turn(EXTERNAL,
                    [self.response(wire, kind='application/json')], messages, stream=False)
                attempt, = facts['attempt_evidence']
                self.assertEqual(attempt['model_status'], 'provider_reported_match')
                self.assertEqual(attempt['model_reports'][0]['source'],
                                 'message.model' if messages else 'response.model')

    def test_malformed_identity_cannot_copy_prose_into_request_logs(self):
        for model, messages in ((EXTERNAL, False), ('gpt-6-luna', False),
                                (EXTERNAL, True), ('claude-sonnet-5', True)):
            with self.subTest(model=model, messages=messages):
                _, _, facts = self.turn(model,
                    [self.response(setup(CANARY, messages) + done(CANARY, messages))], messages)
                self.assertEqual(facts['attempt_evidence'][0]['model_status'], 'unverified')

    def test_transport_timeout_names_the_actual_unfinished_phase(self):
        for phase in ('connect', 'send', 'headers'):
            with self.subTest(phase=phase):
                _, _, facts = self.turn('gpt-6-luna', [], fail_phase=phase)
                attempt, = facts['attempt_evidence']
                self.assertEqual(attempt['failure_phase'], phase)
                self.assertIsNone(attempt['last_data_age_ms'])
                self.assertEqual(attempt['model_status'], 'unverified')

    def test_client_disconnect_is_a_write_failure_without_another_send(self):
        from tests.test_stream_outcome_recovery import _handler, _metrics, _prepared
        upstream = self.response(setup('gpt-6-luna') + done('gpt-6-luna'))
        sends = install_fake(self, lambda: upstream)
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        right.close()
        handler = _handler(socketserver._SocketWriter(left))
        logs = []
        relay.relay(handler, providers.SubscriptionProvider(),
                    _prepared('api.example.test', 'openai'), _metrics('openai'),
                    time.monotonic(), log_event=lambda kind, **fields: logs.append((kind, fields)))
        facts, = [fields for kind, fields in logs if kind == 'attempt_ledger']
        self.assertEqual((len(sends), facts['outcome']), (1, outcome.CANCELLED))
        attempt, = facts['attempt_evidence']
        self.assertEqual(attempt['failure_phase'], 'write')
        self.assertEqual(attempt['error_type'], 'BrokenPipeError')
        self.assertTrue(attempt['committed'], 'Response headers had already reached the client')
        self.assertNotIn(CANARY, json.dumps(logs))

    def test_concurrent_requests_keep_separate_correlation_and_model_evidence(self):
        from concurrent.futures import ThreadPoolExecutor
        local = threading.local()
        install_fake(self, lambda: self.response(setup(local.model) + done(local.model)))
        original = http.client.HTTPSConnection.request
        def send(connection, method, path, body=None, headers=None):
            local.model = json.loads(body)['model']
            return original(connection, method, path, body, headers)
        self.enterContext(mock.patch.object(http.client.HTTPSConnection, 'request', send))
        server = start_server(test_state(auth_file(self)))
        server.state['openai_models'].extend(('gpt-6-luna', 'gpt-6-astra'))
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        complete = threading.Condition()
        facts = []
        def log(kind, **values):
            if kind == 'attempt_ledger':
                with complete:
                    facts.append(values)
                    complete.notify_all()
        def turn(model):
            result = post(server.server_port, '/test-token/responses',
                          {'model': model, 'stream': True, 'input': [], 'tools': []})
            return result.read()
        with mock.patch.object(router, 'log_event', log), ThreadPoolExecutor(2) as pool:
            self.assertTrue(all(pool.map(turn, ('gpt-6-luna', 'gpt-6-astra'))))
            with complete:
                self.assertTrue(complete.wait_for(lambda: len(facts) == 2, timeout=2))
        self.assertEqual(len({row['request_id'] for row in facts}), 2)
        records = [row['attempt_evidence'][0] for row in facts]
        self.assertIsNot(records[0], records[1])
        for record in records:
            self.assertEqual(record['model_reports'][0]['value'], record['requested_model'])
            self.assertEqual(record['model_status'], 'provider_reported_match')


if __name__ == '__main__':
    unittest.main()
