"""Ingress input-shape coverage (Plan 156 item 5): paths, auth, sizes, encodings.

Contract-only: every case asserts the existing rejection status and code and
that a rejected request never reaches upstream. Plan 146 owns the guards; this
module adds deterministic coverage of their input shapes.
"""
import gzip
import http.client
import json
import unittest
from unittest import mock
from compression import zstd

from ai_router import providers as providers_mod
from ai_router import router as router_mod
from tests.fakes import FakeUpstream, install_fake
from tests.harness import (
    auth_file as _auth_file,
    start_server as _start_server,
    test_state as _test_state,
)

TOKEN = 'test-token'
PAYLOAD = {'model': 'deepseek/deepseek-v4.1-flash', 'input': []}
JSON_HEADERS = {'Content-Type': 'application/json'}


class IngressShapeTests(unittest.TestCase):
    def setUp(self):
        self.server = _start_server(_test_state(_auth_file(self)))
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, path, headers=None, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
        self.addCleanup(conn.close)
        conn.request('POST', path, body=body, headers=headers or {})
        return conn.getresponse()

    def raw_request(self, path, header_lines, body=b''):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
        self.addCleanup(conn.close)
        conn.putrequest('POST', path)
        for line in header_lines:
            key, _, value = line.partition(': ')
            conn.putheader(key, value)
        conn.endheaders()
        if body:
            conn.send(body)
        return conn.getresponse()

    def rejected(self, response, status, code, recorded):
        self.assertEqual(response.status, status)
        self.assertEqual(json.loads(response.read())['error']['code'], code)
        self.assertEqual(recorded, [])

    def test_wrong_or_malformed_credentials_are_forbidden(self):
        # Header-only shape: the path token is absent, so the Bearer header
        # is the only credential and every malformed variant must be refused.
        header_only = '/backend-api/codex/responses'
        cases = (
            ('wrong path token', '/wrong-token/responses', {}),
            ('token prefix attack', '/test-token-extra/responses', {}),
            ('token case variant', '/TEST-TOKEN/responses', {}),
            ('wrong bearer', header_only,
             {'Authorization': 'Bearer not-the-token'}),
            ('lowercase bearer', header_only,
             {'Authorization': 'bearer %s' % TOKEN}),
            ('bearer with a tail', header_only,
             {'Authorization': 'Bearer %s extra' % TOKEN}),
        )
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        for name, path, extra in cases:
            with self.subTest(name=name):
                response = self.request(path, {**JSON_HEADERS, **extra},
                                        json.dumps(PAYLOAD))
                self.rejected(response, 403, 'FORBIDDEN', recorded)

    def test_a_bearer_header_still_authorizes(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        response = self.request('/backend-api/codex/responses',
                                {**JSON_HEADERS,
                                 'Authorization': 'Bearer %s' % TOKEN},
                                json.dumps(PAYLOAD))
        self.assertEqual(response.status, 200)
        response.read()
        self.assertEqual(len(recorded), 1)

    def test_unknown_and_dot_routes_are_404(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        for path in ('/test-token/unknown', '/test-token/', '/test-token/../responses'):
            with self.subTest(path=path):
                response = self.request(path, JSON_HEADERS, json.dumps(PAYLOAD))
                self.rejected(response, 404, 'UNSUPPORTED_ROUTE', recorded)

    def test_a_query_string_still_routes(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        response = self.request('/%s/responses?debug=1' % TOKEN, JSON_HEADERS,
                                json.dumps(PAYLOAD))
        self.assertEqual(response.status, 200)
        response.read()
        self.assertEqual(len(recorded), 1)

    def test_missing_negative_or_oversized_lengths_are_400(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        big = json.dumps({'model': 'm' * 80}).encode()
        cases = (
            ('missing', ['Content-Type: application/json'], b''),
            ('negative', ['Content-Type: application/json', 'Content-Length: -1'], b'{}'),
            ('oversized', ['Content-Type: application/json',
                           'Content-Length: %d' % len(big)], big),
        )
        with mock.patch.object(router_mod, 'MAX_BODY', 64):
            for name, headers, body in cases:
                with self.subTest(name=name):
                    response = self.raw_request('/%s/responses' % TOKEN, headers, body)
                    self.rejected(response, 400, 'INVALID_REQUEST_SIZE', recorded)

    def test_a_malformed_length_is_a_payload_rejection(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        response = self.raw_request(
            '/%s/responses' % TOKEN,
            ['Content-Type: application/json', 'Content-Length: not-a-number'], b'{}')
        self.rejected(response, 400, 'INVALID_PAYLOAD', recorded)

    def test_valid_zstd_is_decoded(self):
        wire = json.dumps(PAYLOAD).encode()
        packed = zstd.compress(wire)
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        response = self.raw_request(
            '/%s/responses' % TOKEN,
            ['Content-Type: application/json', 'Content-Encoding: zstd',
             'Content-Length: %d' % len(packed)], packed)
        self.assertEqual(response.status, 200)
        response.read()
        self.assertEqual(len(recorded), 1)

    def test_zstd_tool_search_history_is_slimmed_before_the_size_cap(self):
        schema = 'x' * 80
        tool = {'type': 'function', 'name': 'echo', 'description': 'Echo',
                'parameters': {'type': 'object', 'properties': {'q': {'type': 'string',
                               'description': schema}}}}
        items = []
        for i in range(8):
            items.append({'type': 'tool_search_call', 'call_id': 's%d' % i,
                          'arguments': {'query': 'echo'}})
            items.append({'type': 'tool_search_output', 'call_id': 's%d' % i,
                          'tools': [tool]})
        payload = {'model': 'z-ai/glm-5.3', 'input': items,
                   'tools': [{'type': 'tool_search',
                              'parameters': {'type': 'object'}}]}
        wire = json.dumps(payload).encode()
        packed = zstd.compress(wire)
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        cap = 2700
        with mock.patch.object(router_mod, 'MAX_BODY', cap):
            self.assertGreater(len(wire), cap)
            self.assertLess(len(packed), cap)
            self.assertLess(len(wire), cap * 4)
            response = self.raw_request(
                '/%s/responses' % TOKEN,
                ['Content-Type: application/json', 'Content-Encoding: zstd',
                 'Content-Length: %d' % len(packed)], packed)
            self.assertEqual(response.status, 200)
            response.read()
        self.assertEqual(len(recorded), 1)
        sent = json.loads(recorded[0][3])
        self.assertLess(len(recorded[0][3]), 2700)
        self.assertTrue(any(item.get('type') == 'function_call_output'
                            for item in sent['input']))
        self.assertFalse(any(item.get('type') == 'tool_search_output'
                             for item in sent['input']))

    def test_zstd_body_still_too_large_after_prepare_is_400(self):
        payload = {'model': 'z-ai/glm-5.3',
                   'input': [{'type': 'message', 'role': 'user',
                              'content': 'x' * 1200}]}
        packed = zstd.compress(json.dumps(payload).encode())
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        with mock.patch.object(router_mod, 'MAX_BODY', 900):
            response = self.raw_request(
                '/%s/responses' % TOKEN,
                ['Content-Type: application/json', 'Content-Encoding: zstd',
                 'Content-Length: %d' % len(packed)], packed)
            self.rejected(response, 400, 'BODY_TOO_LARGE', recorded)

    def test_zstd_passthrough_still_uses_decoded_size(self):
        payload = {'model': 'gpt-6-astra',
                   'input': [{'type': 'message', 'role': 'user',
                              'content': 'x' * 1200}]}
        packed = zstd.compress(json.dumps(payload).encode())
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        state = _test_state(_auth_file(self))
        state['openai_models'] = ['gpt-6-astra']
        server = _start_server(state)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with mock.patch.object(router_mod, 'MAX_BODY', 900):
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
            self.addCleanup(conn.close)
            conn.putrequest('POST', '/%s/responses' % TOKEN)
            conn.putheader('Content-Type', 'application/json')
            conn.putheader('Content-Encoding', 'zstd')
            conn.putheader('Content-Length', str(len(packed)))
            conn.endheaders()
            conn.send(packed)
            self.rejected(conn.getresponse(), 400, 'BODY_TOO_LARGE', recorded)

    def test_zstd_decoded_beyond_four_times_the_cap_is_400(self):
        payload = {'model': 'z-ai/glm-5.3',
                   'input': [{'type': 'message', 'role': 'user',
                              'content': 'x' * 5000}]}
        packed = zstd.compress(json.dumps(payload).encode())
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        with mock.patch.object(router_mod, 'MAX_BODY', 200):
            response = self.raw_request(
                '/%s/responses' % TOKEN,
                ['Content-Type: application/json', 'Content-Encoding: zstd',
                 'Content-Length: %d' % len(packed)], packed)
            self.rejected(response, 400, 'BODY_TOO_LARGE', recorded)

    def test_zstd_compaction_trigger_under_decode_ceiling_succeeds(self):
        # A zstd V2 trigger decoded over the cap but under 4x summarizes
        # locally: one compaction item, no full-turn upstream call.
        payload = {'model': 'z-ai/glm-5.3',
                   'input': [{'type': 'message', 'role': 'user',
                              'content': 'x' * 1200},
                             {'type': 'compaction_trigger'}]}
        wire = json.dumps(payload).encode()
        packed = zstd.compress(wire)
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        with mock.patch.object(router_mod, 'MAX_BODY', 900):
            self.assertGreater(len(wire), 900)
            self.assertLess(len(packed), 900)
            self.assertLess(len(wire), 900 * 4)
            with mock.patch.object(
                    providers_mod.ExternalResponsesProvider,
                    'summarize', return_value='handoff done'):
                response = self.raw_request(
                    '/%s/responses' % TOKEN,
                    ['Content-Type: application/json',
                     'Content-Encoding: zstd',
                     'Content-Length: %d' % len(packed)], packed)
            self.assertEqual(response.status, 200)
            body = json.loads(response.read())
            self.assertEqual(len(body['output']), 1)
            self.assertEqual(body['output'][0]['type'], 'compaction')
        self.assertEqual(recorded, [])

    def test_zstd_v1_compact_under_decode_ceiling_succeeds(self):
        # V1 /responses/compact gets the same ceiling: summarize, not 400.
        payload = {'model': 'z-ai/glm-5.3',
                   'input': [{'type': 'message', 'role': 'user',
                              'content': 'do the task ' + 'x' * 1200}]}
        wire = json.dumps(payload).encode()
        packed = zstd.compress(wire)
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        with mock.patch.object(router_mod, 'MAX_BODY', 900):
            self.assertGreater(len(wire), 900)
            self.assertLess(len(packed), 900)
            self.assertLess(len(wire), 900 * 4)
            with mock.patch.object(
                    providers_mod.ExternalResponsesProvider,
                    'summarize', return_value='handoff done'):
                response = self.raw_request(
                    '/%s/responses/compact' % TOKEN,
                    ['Content-Type: application/json',
                     'Content-Encoding: zstd',
                     'Content-Length: %d' % len(packed)], packed)
            self.assertEqual(response.status, 200)
            body = json.loads(response.read())
            self.assertIn('handoff done',
                          json.dumps(body['output']))
        self.assertEqual(recorded, [])

    def test_zstd_compaction_beyond_decode_ceiling_is_400(self):
        # Past 4x the cap the compact still refuses without summarizing.
        payload = {'model': 'z-ai/glm-5.3',
                   'input': [{'type': 'message', 'role': 'user',
                              'content': 'x' * 5000},
                             {'type': 'compaction_trigger'}]}
        packed = zstd.compress(json.dumps(payload).encode())
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        with mock.patch.object(router_mod, 'MAX_BODY', 200):
            response = self.raw_request(
                '/%s/responses' % TOKEN,
                ['Content-Type: application/json', 'Content-Encoding: zstd',
                 'Content-Length: %d' % len(packed)], packed)
            self.rejected(response, 400, 'BODY_TOO_LARGE', recorded)

    def test_garbage_zstd_and_unknown_encodings_are_rejected(self):
        cases = (
            ('garbage zstd', 'zstd', b'not-a-zstd-frame'),
            ('unknown gzip', 'gzip', gzip.compress(json.dumps(PAYLOAD).encode())),
        )
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        for name, encoding, packed in cases:
            with self.subTest(name=name):
                response = self.raw_request(
                    '/%s/responses' % TOKEN,
                    ['Content-Type: application/json',
                     'Content-Encoding: %s' % encoding,
                     'Content-Length: %d' % len(packed)], packed)
                self.rejected(response, 400, 'INVALID_PAYLOAD', recorded)


if __name__ == '__main__':
    unittest.main()
