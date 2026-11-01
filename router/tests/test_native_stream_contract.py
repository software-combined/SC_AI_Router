"""Native outcomes require a readable terminal, without changing its bytes."""
import gzip
import io
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from ai_router import outcome, provider_defs, router, sse, stream_relay, transport
from tests.fakes import FakeUpstream, install_fake
from tests.harness import auth_file, post, start_server, test_state


def frame(kind, **fields):
    return sse.frame(json.dumps({'type': kind, **fields}).encode())


class NativeStreamContractTests(unittest.TestCase):
    def _turn(self, wire, content_type=None, encoding=None, stream=True):
        headers = []
        if content_type:
            headers.append(('Content-Type', content_type))
        if encoding:
            headers.append(('Content-Encoding', encoding))
        sends = install_fake(self, lambda: FakeUpstream(200, wire, headers))
        state = test_state(auth_file(self))
        state['openai_models'] = ['gpt-6-luna']
        server = start_server(state)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        payload = {'model': 'gpt-6-luna', 'stream': stream, 'input': [], 'tools': []}
        with mock.patch.object(router, 'log_event') as logged:
            response = post(server.server_port, '/test-token/responses', payload,
                            {'Authorization': 'Bearer subscription-fixture'})
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), wire)
        self.assertEqual(len(sends), 1, 'Native streams must not acquire replay authority')
        self.assertEqual(sends[0][0], provider_defs.OPENAI.host)
        self.assertEqual(sends[0][3], json.dumps(payload).encode())
        forwarded = {key.lower(): value for key, value in sends[0][4].items()}
        self.assertEqual(forwarded['authorization'], 'Bearer subscription-fixture')
        ledger = next(call.kwargs for call in logged.call_args_list
                      if call.args[0] == 'attempt_ledger')
        terminal = next(call.kwargs for call in logged.call_args_list
                        if call.args[0] in ('request_completed', 'request_failed'))
        self.assertTrue(ledger['committed'])
        self.assertEqual(terminal['forwarded_delta_bytes'], len(wire))
        return ledger, terminal

    def test_unlabelled_stream_preserves_native_extensions_and_classifies_completion(self):
        wire = b': keepalive\r\n\r\n' + b''.join((
            frame('response.created', response={'id': 'r', 'output': []}),
            frame('response.reasoning_text.delta', delta='synthetic reasoning'),
            frame('response.output_item.done', item={
                'type': 'reasoning', 'encrypted_content': 'SYNTHETIC-OPAQUE'}),
            frame('response.future_extension', signature='SYNTHETIC-SIGNATURE'),
            frame('response.output_text.delta', delta='synthetic answer'),
            frame('response.completed', response={
                'status': 'completed', 'error': None, 'output': []})))
        ledger, terminal = self._turn(wire)
        self.assertEqual(ledger['outcome'], outcome.SUCCESS)
        self.assertEqual(terminal['outcome_phase'], outcome.STREAM)
        self.assertGreater(terminal['reasoning_delta_bytes'], 0)
        self.assertGreater(terminal['unattributed_delta_bytes'], 0)
        self.assertLess(terminal['content_delta_bytes'], len(wire))

    def test_unlabelled_native_failures_are_observed_without_rewrite_or_replay(self):
        for kind, response, expected in (
                ('response.failed', {'error': {'code': 'overloaded'}}, outcome.TRANSIENT),
                ('response.failed', {'error': {'code': 'context_length_exceeded'}},
                 outcome.CONTEXT_OVERFLOW),
                ('response.incomplete', {'incomplete_details': {'reason': 'max_output_tokens'}},
                 outcome.INCOMPLETE)):
            with self.subTest(kind=kind, outcome=expected):
                ledger, terminal = self._turn(frame(kind, response=response))
                self.assertEqual(ledger['outcome'], expected)
                self.assertEqual(terminal['terminal_source'], outcome.UPSTREAM)
                self.assertEqual(terminal['outcome_phase'], outcome.STREAM)

    def test_unlabelled_stream_without_a_terminal_stays_unknown(self):
        for wire in (b'opaque bytes', frame('response.future_extension'),
                     b'data: {"type":"response.completed","response":{"output":[]}}\n'):
            with self.subTest(wire=wire):
                ledger, terminal = self._turn(wire)
                self.assertEqual(ledger['outcome'], outcome.UNKNOWN)
                self.assertEqual(terminal['content_delta_bytes'], 0)

    def test_encoded_json_is_opaque_and_not_a_success_at_eof(self):
        wire = gzip.compress(b'{"status":"completed","output":[]}')
        ledger, terminal = self._turn(wire, 'application/json', 'gzip')
        self.assertEqual(ledger['outcome'], outcome.UNKNOWN)
        self.assertEqual(terminal['content_delta_bytes'], 0)
        self.assertEqual(terminal['unattributed_delta_bytes'], len(wire))

    def test_unknown_nonstream_representation_is_opaque(self):
        ledger, terminal = self._turn(b'opaque bytes', stream=False)
        self.assertEqual(ledger['outcome'], outcome.UNKNOWN)
        self.assertEqual(terminal['content_delta_bytes'], 0)

    def test_known_nonstream_json_keeps_its_existing_eof_success(self):
        ledger, terminal = self._turn(
            b'{"status":"completed","output":[]}', 'application/json', stream=False)
        self.assertEqual(ledger['outcome'], outcome.SUCCESS)
        self.assertEqual(terminal['outcome_phase'], outcome.STATUS)

    def test_unlabelled_partial_frame_is_forwarded_before_next_upstream_read(self):
        client = SimpleNamespace(wfile=io.BytesIO())
        first = b'data: {"type":"response.completed",'
        last = b'"response":{"status":"completed","error":null,"output":[]}}\n\n'

        def chunks(*args):
            yield first
            self.assertEqual(client.wfile.getvalue(), first)
            yield last

        provider = SimpleNamespace(defn=provider_defs.OPENAI, adapt=chunks)
        metrics = {'protocol': provider_defs.RESPONSES, 'stream': True,
                   'response_kind': 'other', 'response_encoding': 'identity'}
        record = stream_relay.StreamRecord(transport.ResponseFormat(
            provider_defs.RESPONSES, '/v1/responses', True, 'other', 'identity'))
        stream_relay.relay_stream(client, provider, None, SimpleNamespace(tool_names=set()),
                                  metrics, 0.0, 0.0, record)
        self.assertEqual(client.wfile.getvalue(), first + last)
        self.assertEqual(record.outcome.category, outcome.SUCCESS)
        self.assertEqual(record.outcome.phase, outcome.STREAM)
        self.assertFalse(record.hold.frames)


if __name__ == '__main__':
    unittest.main()
