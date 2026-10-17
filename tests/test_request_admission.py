"""Plan 188: one local request ceiling on every route and encoding.

The 2026-09-25 native gpt-6-astra turn (17 images, 10.5 MB on the wire,
18.2 MB decoded) was read by ingress and then refused before any send: the
final gate still held every prepared body to the 16 MiB ordinary threshold.
Every route and encoding now forwards a turn whole below the local 256 MiB
ceiling and counts decoded bytes on every send; test_request_lease covers
the reservation such a turn holds. Limits are scaled (the parent's reproduction used
2000 and 12000); one case crosses the real 16 MiB.
"""
import http.client
import json
import random
import unittest
from unittest import mock
from compression import zstd

from ai_router import (errors, provider_defs, rejected_repair, sse, transport,
                       turn_budget, wire_shape)
from ai_router import router as router_mod
from tests.fakes import FakeUpstream, install_fake
from tests.harness import auth_file, scaled_limits, start_server, test_state

CAP, CEILING = 2000, 12000
SIGNATURE = 'gAAAA-opaque-signature'
SUB_AUTH = {'Authorization': 'Bearer subscription-secret', 'ChatGPT-Account-Id': 'acct-1'}
# route: (path, model, upstream host, client headers)
ROUTES = {
    'native responses': ('/test-token/responses', 'gpt-6-astra', 'chatgpt.com', SUB_AUTH),
    'external responses': ('/test-token/responses', 'deepseek/deepseek-v4.1-flash-1017',
                           'openrouter.ai', {}),
    'native messages': ('/test-token/v1/messages', 'claude-opus-4-6', 'api.anthropic.com',
                        {'Authorization': 'Bearer subscription-secret'}),
    'external messages': ('/test-token/v1/messages', 'z-ai/glm-5.3-flash', 'openrouter.ai', {}),
}
NATIVE = ('native responses', 'native messages')
# A developer block naming a previous context window: the native adapter
# rewrites the body (it appends recovery guidance) and keeps every item.
CONTEXT_RESET = {'type': 'message', 'role': 'developer', 'content': [{
    'type': 'input_text', 'text': '<context_window>\nCurrent context window id: '
    '22222222-2222-4222-8222-222222222222\nPrevious context window id: '
    '11111111-1111-4111-8111-111111111111\n</context_window>'}]}


def _turn(route, pad, text='look', image=None):
    """An image and tool history turn for `route`, `pad` bytes per image."""
    model = ROUTES[route][1]
    image = image or 'iVBORw0KGgo' + 'A' * pad
    if ROUTES[route][0].endswith('/messages'):
        block = {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png',
                                             'data': image}}
        return {'model': model, 'max_tokens': 64,
                'tools': [{'name': 'get_time', 'input_schema': {'type': 'object'}}],
                'messages': [
                    {'role': 'user', 'content': [{'type': 'text', 'text': text}, block]},
                    {'role': 'assistant', 'content': [
                        {'type': 'thinking', 'thinking': 'plan', 'signature': SIGNATURE},
                        {'type': 'tool_use', 'id': 't1', 'name': 'get_time', 'input': {}}]},
                    {'role': 'user', 'content': [
                        {'type': 'tool_result', 'tool_use_id': 't1', 'content': [block]}]}]}
    block = {'type': 'input_image', 'image_url': 'data:image/png;base64,' + image}
    return {'model': model, 'input': [
        {'type': 'message', 'role': 'user',
         'content': [{'type': 'input_text', 'text': text}, block]},
        {'type': 'reasoning', 'id': 'rs_1', 'summary': [], 'encrypted_content': SIGNATURE},
        {'type': 'function_call', 'call_id': 'c1', 'name': 'exec_command', 'arguments': '{}'},
        {'type': 'function_call_output', 'call_id': 'c1', 'output': [block]}]}


def _wire(payload, encoding=None):
    raw = json.dumps(payload, ensure_ascii=False).encode()
    return raw, zstd.compress(raw) if encoding == 'zstd' else raw


def _sent(record):
    """The JSON a recorded send carries, decoded as its own headers declare."""
    body, headers = record[3], record[4]
    return json.loads(zstd.decompress(body) if transport.encoded(headers) else body)


class ServerCase(unittest.TestCase):
    """A router with the native rows registered; no tests of its own."""

    def setUp(self):
        state = test_state(auth_file(self))
        state.update(openai_models=['gpt-6-astra', 'gpt-6-luna'], openai_helper_fallback=True)
        self.server = start_server(state)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def send(self, route, body, encoding=None, extra=None):
        path, _, _, auth = ROUTES[route]
        headers = {'Content-Type': 'application/json', **auth, **(extra or {})}
        if encoding:
            headers['Content-Encoding'] = encoding
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
        self.addCleanup(conn.close)
        conn.request('POST', path, body=body, headers=headers)
        return conn.getresponse()

    def answer(self, response, status, code=None):
        self.assertEqual(response.status, status)
        body = json.loads(response.read() or b'{}')
        if code is not None:
            self.assertEqual(body['error']['code'], code)
        return body

    def assert_released(self):
        with self.server.large_request_condition:
            self.assertTrue(self.server.large_request_condition.wait_for(
                lambda: not self.server.large_request_reservations, timeout=5),
                'large-request reservations leaked')
            self.assertEqual(self.server.large_request_bytes, 0)


class RequestAdmissionTests(ServerCase):
    def test_a_native_compressed_image_history_turn_is_forwarded_whole(self):
        # The incident shape: small on the wire, past the threshold decoded.
        raw, packed = _wire(_turn('native responses', 1400), 'zstd')
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        with scaled_limits(CAP, CEILING):
            self.assertLess(len(packed), CAP)
            self.assertLess(CAP, len(raw))
            self.answer(self.send('native responses', packed, 'zstd'), 200)
        self.assertEqual(len(recorded), 1)
        host, _, _, body, headers = recorded[0]
        self.assertEqual((host, body), ('chatgpt.com', packed))
        self.assertEqual(headers.get('Content-Encoding'), 'zstd')
        self.assertLessEqual(SUB_AUTH.items(), headers.items())
        self.assert_released()

    def test_every_route_and_encoding_forwards_a_large_turn_without_trimming(self):
        for route, (_, _, host, auth) in ROUTES.items():
            for encoding in (None, 'zstd'):
                with self.subTest(route=route, encoding=encoding):
                    payload = _turn(route, 1400)
                    raw, body = _wire(payload, encoding)
                    recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
                    with scaled_limits(CAP, CEILING):
                        self.assertLess(CAP, len(raw))
                        self.answer(self.send(route, body, encoding), 200)
                    self.assertEqual([record[0] for record in recorded], [host])
                    sent, headers = _sent(recorded[0]), recorded[0][4]
                    rendered = json.dumps(sent)
                    self.assertEqual(rendered.count('A' * 1400), 2)
                    if route in NATIVE:
                        self.assertEqual(recorded[0][3], body)
                        self.assertEqual(headers.get('Content-Encoding'), encoding)
                        self.assertLessEqual(auth.items(), headers.items())
                    else:
                        self.assertEqual(headers['Authorization'], 'Bearer test-key')
                        self.assertNotIn('subscription-secret', json.dumps(headers))
                        self.assertNotIn('Content-Encoding', headers)
                    if route == 'external messages':
                        self.assertEqual(sent, payload)
                    self.assert_released()

    def test_a_native_rewrite_keeps_every_item_and_counts_its_serialized_size(self):
        payload = _turn('native responses', 1400)
        payload['input'].append(CONTEXT_RESET)
        _, packed = _wire(payload, 'zstd')
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        with scaled_limits(CAP, CEILING):
            self.answer(self.send('native responses', packed, 'zstd'), 200)
        _, _, _, body, headers = recorded[0]
        sent = json.loads(body)
        self.assertEqual(sent['input'][:len(payload['input'])], payload['input'])
        self.assertGreater(len(sent['input']), len(payload['input']))
        self.assertNotIn('Content-Encoding', headers)
        self.assertLessEqual(SUB_AUTH.items(), headers.items())

    def test_wire_decoded_and_prepared_bodies_past_the_ceiling_are_never_sent(self):
        # Prepared growth: a rewrite escapes each two-byte character to six.
        grown = {'native responses': [CONTEXT_RESET], 'external responses': [],
                 'external messages': []}
        for route in ROUTES:
            cases = [('wire', _wire(_turn(route, CEILING))[1], None),
                     ('decoded', _wire(_turn(route, 2 * CEILING), 'zstd')[1], 'zstd')]
            if route in grown:
                payload = _turn(route, 10, text='é' * 2500)
                payload.get('input', []).extend(grown[route])
                raw, body = _wire(payload, 'zstd' if route == 'external messages' else None)
                self.assertLess(len(raw), CEILING)
                cases.append(('prepared', body, 'zstd' if route == 'external messages' else None))
            for stage, body, encoding in cases:
                with self.subTest(route=route, stage=stage):
                    recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
                    with scaled_limits(CAP, CEILING), \
                            mock.patch.object(router_mod, 'log_event') as logged:
                        response = self.send(route, body, encoding)
                        body = self.answer(response, 400, 'BODY_TOO_LARGE')
                    self.assertIn('256 MiB', body['error']['message'])
                    self.assertEqual(recorded, [])
                    self.assert_released()
                    if stage == 'prepared':
                        facts = [c.kwargs for c in logged.call_args_list
                                 if c.args[0] == 'turn_refused'][0]
                        self.assertGreater(facts['prepared_bytes'], CEILING)
                        self.assertLess(facts['decoded_bytes'], CEILING)

    def test_a_real_turn_past_16_mib_on_decode_is_forwarded_byte_for_byte(self):
        # Unscaled, as in the incident: under 16 MiB compressed, over it decoded.
        image = random.Random(188).randbytes(6_600_000).hex()[:8_800_000]
        _, packed = _wire(_turn('native responses', 0, image=image), 'zstd')
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        self.assertLess(len(packed), router_mod.MAX_BODY)
        self.answer(self.send('native responses', packed, 'zstd'), 200)
        self.assertEqual(recorded[0][3], packed)
        self.assert_released()


class AccountingTests(unittest.TestCase):
    def test_the_ceiling_is_local_and_response_bounds_do_not_move(self):
        self.assertEqual(transport.MAX_REQUEST_BYTES, 256 * 1024 * 1024)
        self.assertEqual(wire_shape.DECODE_LIMIT, transport.MAX_REQUEST_BYTES)
        self.assertEqual(rejected_repair.ZSTD_DECODE_LIMIT, transport.MAX_REQUEST_BYTES)
        for bound in (router_mod.MAX_BODY, transport.MAX_UPSTREAM_BODY,
                      sse.MAX_FRAME_BYTES, turn_budget.BODY_BUDGET):
            self.assertEqual(bound, 16 * 1024 * 1024)
        self.assertEqual(transport.ERROR_BODY_LIMIT, 1024 * 1024)

    def test_every_send_counts_decoded_bytes_and_refuses_before_connecting(self):
        packed = zstd.compress(b'{"input": []}' + b' ' * 5000)
        zstd_headers = {'Content-Encoding': 'zstd'}
        cases = (({}, b'{}', None, None), (zstd_headers, packed, 5013, None),
                 ({'content-encoding': 'identity'}, b'{}', None, None),
                 (zstd_headers, packed, None, 'Invalid request size'),
                 (zstd_headers, packed, 5000 * 6, 'Decoded request is too large'),
                 ({}, b' ' * 25001, None, 'Decoded request is too large'))
        for headers, body, decoded, refusal in cases:
            with self.subTest(headers=headers, decoded=decoded, refusal=refusal):
                prepared = transport.Prepared('upstream.example', '/responses', headers,
                                              body, set(), provider_defs.OPENAI.id,
                                              decoded_body_bytes=decoded)
                conn = mock.Mock()
                conn.getresponse.return_value = FakeUpstream(200, b'{}')
                with mock.patch.object(transport, 'MAX_REQUEST_BYTES', 5000 * 5):
                    if refusal is None:
                        transport.post_with_phases(conn, prepared, {})
                        self.assertEqual(conn.request.call_args.kwargs['body'], body)
                        continue
                    with self.assertRaises(errors.InvalidSize) as caught:
                        transport.post_with_phases(conn, prepared, {})
                self.assertEqual(str(caught.exception), refusal)
                conn.connect.assert_not_called()
                conn.request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
