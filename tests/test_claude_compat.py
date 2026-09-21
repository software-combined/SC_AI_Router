"""Claude Code repairs on the external Messages route.

Fake upstream only; never opens a real network connection. Two shapes that
Claude Code 2.1.223 cannot survive are repaired in flight, and every other
byte of the request and the stream must stay exactly as the client sent it.
The subscription route is untouched and is pinned as such here.
"""
import json
import unittest

from tests.fakes import FakeUpstream, install_fake
from tests.harness import (
    auth_file as _auth_file,
    post as _post,
    start_server as _start_server,
    test_state as _test_state,
)
from ai_router import claude as claude_mod
from ai_router import claude_compat as compat
from ai_router import provider_defs

FABLE = 'anthropic/claude-fable-5.1'
BILLING = 'x-anthropic-billing-header: cc_version=2.1.223.aeb; cc_entrypoint=sdk-cli;'


def _frame(kind, payload):
    return b'event: %s\ndata: %s\n\n' % (kind.encode(), json.dumps(payload).encode())


def _start(index, block_type):
    return _frame('content_block_start',
                  {'type': 'content_block_start', 'index': index,
                   'content_block': {'type': block_type}})


def _delta(index, delta):
    return _frame('content_block_delta',
                  {'type': 'content_block_delta', 'index': index, 'delta': delta})


def _stop(index):
    return _frame('content_block_stop', {'type': 'content_block_stop', 'index': index})


class BillingHeaderTests(unittest.TestCase):
    def test_billing_block_goes_and_the_rest_of_the_prompt_stays(self):
        payload = {'system': [{'type': 'text', 'text': BILLING},
                              {'type': 'text', 'text': 'You are an agent.'}]}
        self.assertTrue(compat.strip_billing_header(payload))
        self.assertEqual(payload['system'],
                         [{'type': 'text', 'text': 'You are an agent.'}])

    def test_lone_billing_block_removes_the_key_entirely(self):
        payload = {'system': [{'type': 'text', 'text': BILLING}]}
        self.assertTrue(compat.strip_billing_header(payload))
        self.assertNotIn('system', payload)

    def test_a_prompt_that_merely_names_the_field_is_kept(self):
        payload = {'system': [{'type': 'text',
                               'text': 'Explain the x-anthropic-billing-header: field.'}]}
        self.assertFalse(compat.strip_billing_header(payload))
        self.assertEqual(len(payload['system']), 1)

    def test_untouched_shapes_report_no_change(self):
        for payload in (None, 'text', {},
                        {'system': 'a plain string'},
                        {'system': [{'type': 'text', 'text': 'Be brief.'}]}):
            with self.subTest(payload=payload):
                self.assertFalse(compat.strip_billing_header(payload))


class ThinkingShapeTests(unittest.TestCase):
    def _shaped(self, frames):
        return b''.join(compat.shape(frames))

    def test_empty_thinking_after_a_tool_result_is_dropped(self):
        # The exact order OpenRouter sends on google/gemini-3.8-flash: the
        # empty block opens before the text block closes. Claude Code threw
        # the whole answer away when that reached it.
        frames = [_start(0, 'text'),
                  _delta(0, {'type': 'text_delta', 'text': 'SCGCC_OK'}),
                  _start(1, 'thinking'),
                  _stop(0),
                  _delta(1, {'type': 'signature_delta', 'signature': 'abc'}),
                  _stop(1)]
        self.assertEqual(self._shaped(frames),
                         b''.join([frames[0], frames[1], frames[3]]))

    def test_thinking_that_streams_content_is_forwarded_whole(self):
        frames = [_start(0, 'thinking'),
                  _delta(0, {'type': 'thinking_delta', 'thinking': 'hmm'}),
                  _stop(0),
                  _start(1, 'text'),
                  _delta(1, {'type': 'text_delta', 'text': 'done'}),
                  _stop(1)]
        self.assertEqual(self._shaped(frames), b''.join(frames))

    def test_a_stream_without_thinking_is_byte_identical(self):
        frames = [_start(0, 'text'),
                  _delta(0, {'type': 'text_delta', 'text': 'done'}),
                  _stop(0),
                  _frame('message_stop', {'type': 'message_stop'})]
        self.assertEqual(self._shaped(frames), b''.join(frames))

    def test_an_unfinished_empty_block_is_still_released(self):
        # A socket that dies mid-block must not swallow the frames it held.
        frames = [_start(0, 'thinking')]
        self.assertEqual(self._shaped(frames), b''.join(frames))


class ProviderSurfaceTests(unittest.TestCase):
    def _provider(self):
        return claude_mod.ExternalMessagesProvider(provider_defs.get('openrouter'))

    def test_streaming_response_is_shaped(self):
        frames = [_start(0, 'text'),
                  _delta(0, {'type': 'text_delta', 'text': 'hi'}),
                  _start(1, 'thinking'),
                  _stop(0),
                  _delta(1, {'type': 'signature_delta', 'signature': 'abc'}),
                  _stop(1)]
        source = FakeUpstream(200, b''.join(frames),
                              [('Content-Type', 'text/event-stream')])
        self.assertEqual(b''.join(self._provider().adapt(source, None)),
                         b''.join([frames[0], frames[1], frames[3]]))

    def test_json_response_is_handed_over_untouched(self):
        body = b'{"id":"msg_1","type":"message","content":[{"type":"text","text":"hi"}]}'
        source = FakeUpstream(200, body, [('Content-Type', 'application/json')])
        self.assertEqual(b''.join(self._provider().adapt(source, None)), body)


class IngressContractTests(unittest.TestCase):
    def _server(self):
        server = _start_server(_test_state(_auth_file(self)))
        self.addCleanup(server.shutdown)
        return server

    def _send(self, payload, headers=None):
        recorded = install_fake(self, lambda: FakeUpstream(
            200, b'{"id":"msg_1","type":"message","content":[]}', []))
        port = self._server().server_port
        response = _post(port, '/test-token/v1/messages', payload,
                         {'anthropic-version': '2023-06-01', **(headers or {})})
        response.read()
        return recorded, response.status

    def test_the_billing_block_never_reaches_openrouter(self):
        payload = {'model': FABLE, 'max_tokens': 8,
                   'system': [{'type': 'text', 'text': BILLING},
                              {'type': 'text', 'text': 'Be brief.'}],
                   'messages': [{'role': 'user',
                                 'content': [{'type': 'text', 'text': 'hi'}]}]}
        recorded, status = self._send(payload)
        self.assertEqual(status, 200)
        host, _, path, body, headers = recorded[0]
        self.assertEqual(host, 'openrouter.ai')
        self.assertEqual(path, '/api/v1/messages')
        sent = json.loads(body)
        self.assertEqual(sent['system'], [{'type': 'text', 'text': 'Be brief.'}])
        self.assertNotIn('x-anthropic-billing-header', body.decode())
        self.assertEqual(headers, {'Authorization': 'Bearer test-key',
                                   'Content-Type': 'application/json'})

    def test_a_request_without_the_block_stays_byte_identical(self):
        payload = {'model': FABLE, 'max_tokens': 8,
                   'system': [{'type': 'text', 'text': 'Be brief.'}],
                   'messages': [{'role': 'user',
                                 'content': [{'type': 'text', 'text': 'hi'}]}]}
        raw = json.dumps(payload)
        recorded, status = self._send(payload)
        self.assertEqual(status, 200)
        self.assertEqual(recorded[0][3].decode(), raw)

    def test_subscription_route_keeps_the_billing_block(self):
        payload = {'model': 'claude-sonnet-5', 'max_tokens': 8,
                   'system': [{'type': 'text', 'text': BILLING},
                              {'type': 'text', 'text': 'Be brief.'}],
                   'messages': [{'role': 'user',
                                 'content': [{'type': 'text', 'text': 'hi'}]}]}
        raw = json.dumps(payload)
        recorded, status = self._send(
            payload, {'Authorization': 'Bearer subscription-secret'})
        self.assertEqual(status, 200)
        host, _, _, body, _ = recorded[0]
        self.assertEqual(host, 'api.anthropic.com')
        self.assertEqual(body.decode(), raw)
