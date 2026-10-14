"""Messages retries stop before any tool, thinking or opaque commitment."""
import json
import threading
import unittest
from unittest import mock

from ai_router import outcome, router
from tests.fakes import FakeUpstream, install_fake
from tests.harness import auth_file, post, start_server, test_state
from tests.test_messages_stream_contract import START, ending, frame

MODEL = 'deepseek/deepseek-v4.1-flash'
CLIENT = {'name': 'Read', 'input_schema': {'type': 'object', 'properties': {}}}
OVERLOAD = frame('error', error={'type': 'overloaded_error', 'message': 'synthetic'})
DONE = START + ending('end_turn')


def response(wire, status=200, kind='text/event-stream'):
    return lambda: FakeUpstream(status, wire, [('Content-Type', kind)])


class MessagesRecoveryTests(unittest.TestCase):
    def turn(self, replies, tools=None, model=MODEL, path='/v1/messages', stream=True):
        count = 0

        def next_response():
            nonlocal count
            item = replies[min(count, len(replies) - 1)]
            count += 1
            if isinstance(item, Exception):
                raise item
            return item()

        sends = install_fake(self, next_response)
        server = start_server(test_state(auth_file(self)))
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
        with mock.patch.object(router, 'log_event') as logged:
            result = post(server.server_port, '/test-token' + path,
                          {'model': model, 'messages': [],
                           **({} if stream is None else {'stream': stream}),
                           'tools': [CLIENT] if tools is None else tools},
                          {'Authorization': 'Bearer subscription-fixture'})
            wire = result.read()
            self.assertTrue(finished.wait(2), 'request cleanup did not finish')
        ledgers = [c.kwargs for c in logged.call_args_list if c.args[0] == 'attempt_ledger']
        self.assertEqual(len(ledgers), 1)
        self.assertEqual(server.inflight, 0)
        self.assertEqual(server.large_request_reservations, {})
        self.assertEqual(server.large_request_bytes, 0)
        return result.status, wire, sends, ledgers[0]

    def test_empty_transient_attempt_is_replaced_once_without_duplicate_identity(self):
        for tools in ([], [CLIENT], [{**CLIENT, 'type': 'custom'}]):
            with self.subTest(tools=tools):
                status, wire, sends, ledger = self.turn(
                    [response(START + OVERLOAD), response(DONE)], tools)
                self.assertEqual((status, wire, len(sends)), (200, DONE, 2))
                self.assertEqual(sends[0], sends[1])
                self.assertNotIn('subscription-fixture', str(sends[0][4]))
                self.assertEqual([a[2] for a in ledger['attempts']],
                                 ['initial', 'stream_replay'])
                self.assertEqual(ledger['outcome'], outcome.SUCCESS)

    def test_exhausted_replay_keeps_one_upstream_terminal(self):
        _, wire, sends, ledger = self.turn([response(START + OVERLOAD)])
        self.assertEqual((wire, len(sends)), (START + OVERLOAD, 2))
        self.assertEqual(ledger['outcome'], outcome.TRANSIENT)
        self.assertEqual(ledger['terminal_source'], outcome.UPSTREAM)
        self.assertEqual(ledger['decisions'],
                         ['stream_replay:approved', 'stream_replay:budget'])

    def test_token_counting_does_not_gain_a_generation_retry(self):
        _, wire, sends, _ = self.turn([response(START + OVERLOAD)],
                                     path='/v1/messages/count_tokens')
        self.assertEqual((wire, len(sends)), (START + OVERLOAD, 1))

    def test_nonstream_request_never_gains_replay_from_unexpected_sse(self):
        for stream in (False, None):
            with self.subTest(stream=stream):
                _, wire, sends, ledger = self.turn([response(START + OVERLOAD)], stream=stream)
                self.assertEqual((wire, len(sends)), (START + OVERLOAD, 1))
                self.assertEqual([a[2] for a in ledger['attempts']], ['initial'])

    def test_documented_stream_api_and_timeout_errors_share_the_transient_rule(self):
        for cause in ('api_error', 'timeout_error'):
            with self.subTest(cause=cause):
                failed = START + frame('error', error={'type': cause})
                _, wire, sends, ledger = self.turn([response(failed), response(DONE)])
                self.assertEqual((wire, len(sends), ledger['outcome']), (DONE, 2, outcome.SUCCESS))

    def test_native_hosted_and_unknown_tools_never_replay(self):
        cases = [('claude-sonnet-5', [CLIENT]),
                 (MODEL, [{'name': 'search', 'type': 'web_search_20260209'}]),
                 (MODEL, [{**CLIENT, 'type': 'future_tool'}]),
                 (MODEL, [{'name': 'unknown'}]),
                 (MODEL, [{**CLIENT, 'input_schema': []}]),
                 (MODEL, {'name': 'not_an_array'}), (MODEL, {})]
        for model, tools in cases:
            with self.subTest(model=model, tools=tools):
                _, wire, sends, ledger = self.turn([response(START + OVERLOAD)], tools, model)
                self.assertEqual((wire, len(sends)), (START + OVERLOAD, 1))
                self.assertEqual(ledger['outcome'], outcome.TRANSIENT)

    def test_content_thinking_signatures_and_unknown_frames_commit(self):
        blocks = [
            frame('content_block_start', index=0, content_block={'type': 'text', 'text': ''}),
            frame('content_block_start', index=0, content_block={
                'type': 'tool_use', 'id': 'tool_original', 'name': 'Read', 'input': {}}),
            frame('content_block_delta', index=0, delta={'type': 'thinking_delta', 'thinking': 'x'}),
            frame('content_block_delta', index=0, delta={'type': 'signature_delta', 'signature': 'fixture'}),
            frame('content_block_start', index=0, content_block={'type': 'redacted_thinking', 'data': 'fixture'}),
            frame('future_extension', value='fixture'),
            START,  # A duplicate setup cannot be replaced.
        ]
        for block in blocks:
            with self.subTest(block=block):
                _, wire, sends, ledger = self.turn([response(START + block + OVERLOAD)])
                self.assertEqual(len(sends), 1)
                self.assertTrue(wire.endswith(OVERLOAD))
                self.assertTrue(ledger['committed'])

    def test_removed_empty_thinking_still_prohibits_replay(self):
        empty = (frame('content_block_start', index=0,
                       content_block={'type': 'thinking', 'thinking': ''})
                 + frame('content_block_delta', index=0,
                         delta={'type': 'signature_delta', 'signature': 'fixture'})
                 + frame('content_block_stop', index=0))
        _, wire, sends, ledger = self.turn([response(START + empty + OVERLOAD)])
        self.assertEqual(len(sends), 1)
        self.assertEqual(wire, START + OVERLOAD)
        self.assertIn('stream_replay:committed', ledger['decisions'])

    def test_thinking_fence_with_no_setup_survives_a_truncated_block(self):
        thinking = frame('content_block_start', index=0,
                         content_block={'type': 'thinking', 'thinking': ''})
        for suffix in (OVERLOAD, b'data: incomplete'):
            with self.subTest(suffix=suffix):
                _, _, sends, ledger = self.turn([response(thinking + suffix)])
                self.assertEqual(len(sends), 1)
                self.assertNotEqual(ledger['outcome'], outcome.SUCCESS)

    def test_native_quota_never_names_external_key_billing(self):
        raw = b'{"error":{"code":"insufficient_quota"}}'
        status, wire, sends, ledger = self.turn(
            [response(raw, 429, 'application/json')], model='claude-sonnet-5')
        self.assertEqual((status, len(sends)), (429, 1))
        self.assertEqual(ledger['outcome'], outcome.QUOTA)
        self.assertIn('Claude subscription', json.loads(wire)['error']['message'])
        self.assertNotIn(b'OpenRouter', wire)

    def test_unknown_final_and_missing_verdicts_do_not_replay(self):
        for failure in (frame('error', error={'type': 'future_error'}),
                        frame('error', error={'type': 'invalid_request_error'}),
                        ending('max_tokens'), b''):
            with self.subTest(failure=failure):
                _, _, sends, ledger = self.turn([response(START + failure)])
                self.assertEqual(len(sends), 1)
                self.assertNotEqual(ledger['outcome'], outcome.SUCCESS)

    def test_retry_transport_status_or_representation_failure_keeps_first_verdict(self):
        for retry in (OSError('synthetic connection failure'),
                      response(b'{}', 500, 'application/json'),
                      response(b'{}', 200, 'application/json')):
            with self.subTest(retry=retry):
                _, wire, sends, ledger = self.turn([response(START + OVERLOAD), retry])
                self.assertEqual((wire, len(sends)), (START + OVERLOAD, 2))
                self.assertEqual(ledger['outcome'], outcome.TRANSIENT)
                self.assertEqual(ledger['terminal_source'], outcome.UPSTREAM)

    def test_retry_eof_without_a_terminal_renders_one_messages_error(self):
        _, wire, sends, ledger = self.turn([response(START + OVERLOAD), response(START)])
        self.assertEqual(len(sends), 2)
        events = [json.loads(line[5:]) for line in wire.splitlines() if line.startswith(b'data:')]
        self.assertEqual([e['type'] for e in events], ['message_start', 'error'])
        self.assertEqual(events[-1]['error']['type'], 'api_error')
        self.assertEqual(ledger['outcome'], outcome.UNKNOWN)
        self.assertEqual(ledger['terminal_source'], outcome.ROUTER)

    def test_http_failures_are_messages_errors_without_router_retries(self):
        for model in (MODEL, 'claude-sonnet-5'):
            for status, cause, expected in ((500, 'api_error', outcome.TRANSIENT),
                                            (504, 'timeout_error', outcome.TRANSIENT),
                                            (529, 'overloaded_error', outcome.TRANSIENT),
                                            (400, 'invalid_request_error', outcome.REFUSED)):
                with self.subTest(model=model, status=status):
                    raw = json.dumps({'type': 'error', 'error': {
                        'type': cause, 'message': 'synthetic'}}).encode()
                    actual, wire, sends, ledger = self.turn(
                        [response(raw, status, 'application/json')], model=model)
                    self.assertEqual((actual, len(sends)), (status, 1))
                    body = json.loads(wire)
                    self.assertEqual(body['type'], 'error')
                    self.assertEqual(body['error']['type'], cause)
                    self.assertEqual(ledger['outcome'], expected)
                    self.assertNotIn('Do not retry', body['error']['message'])
