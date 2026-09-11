"""Ingress guard coverage (Plan 092): websocket, Transfer-Encoding, zstd bound.

Fake upstream only; never opens a real network connection. Each test
asserts the rejection status plus the stable error code and that no
upstream call is recorded, so removing its guard branch fails the test.
Reuses the handler helpers like tests/test_claude_ingress.py does.
"""
import http.client
import json
import socket
import unittest
from unittest import mock
from compression import zstd
from ai_router import router as router_mod
from tests.fakes import FakeUpstream, install_fake
from tests.test_handler import _auth_file
from tests.test_mixed_router import _start_server, _test_state


class IngressGuardTests(unittest.TestCase):
    def _server(self):
        state = _test_state(_auth_file(self))
        server = _start_server(state)
        self.addCleanup(server.shutdown)
        return server

    def test_websocket_upgrade_is_426_and_never_reaches_upstream(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        server = self._server()
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        conn.request('GET', '/test-token/responses', headers={'Upgrade': 'websocket'})
        response = conn.getresponse()
        self.assertEqual(response.status, 426)
        self.assertEqual(json.loads(response.read())['error']['code'], 'WEBSOCKET_REJECTED')
        self.assertEqual(recorded, [])

    def test_transfer_encoding_is_413_and_never_reaches_upstream(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        server = self._server()
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        payload = json.dumps({'model': 'z-ai/glm-5.3', 'input': []}).encode()
        conn.putrequest('POST', '/test-token/responses')
        conn.putheader('Content-Length', str(len(payload)))
        conn.putheader('Transfer-Encoding', 'chunked')
        conn.putheader('Content-Type', 'application/json')
        conn.endheaders()
        conn.send(payload)
        response = conn.getresponse()
        self.assertEqual(response.status, 413)
        self.assertEqual(json.loads(response.read())['error']['code'], 'INVALID_REQUEST_SIZE')
        self.assertEqual(recorded, [])

    def test_zstd_decoded_too_large_is_413_and_never_reaches_upstream(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        server = self._server()
        payload = {'model': 'z-ai/glm-5.3',
                   'input': [{'type': 'message', 'role': 'user', 'content': 'x' * 4096}]}
        body = zstd.compress(json.dumps(payload).encode())
        with mock.patch.object(router_mod, 'MAX_BODY', 4096):
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
            conn.request('POST', '/test-token/responses', body=body,
                         headers={'Content-Type': 'application/json',
                                  'Content-Encoding': 'zstd'})
            response = conn.getresponse()
            self.assertEqual(response.status, 413)
            self.assertEqual(json.loads(response.read())['error']['code'], 'BODY_TOO_LARGE')
        self.assertEqual(recorded, [])

    def _raw_request(self, port, request_bytes):
        """Read the full response: headers plus the declared Content-Length body.

        Stopping at the header terminator would race the body, so the body
        assertions below would flake.
        """
        sock = socket.create_connection(('127.0.0.1', port), timeout=10)
        self.addCleanup(sock.close)
        sock.sendall(request_bytes)
        data = b''
        while b'\r\n\r\n' not in data:
            chunk = sock.recv(4096)
            if not chunk:
                return data
            data += chunk
        head, body = data.split(b'\r\n\r\n', 1)
        want = 0
        for line in head.split(b'\r\n'):
            if line.lower().startswith(b'content-length:'):
                want = int(line.split(b':', 1)[1])
        while len(body) < want:
            chunk = sock.recv(4096)
            if not chunk:
                break
            body += chunk
        return head + b'\r\n\r\n' + body

    def test_non_ascii_path_is_rejected_not_crashed(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        server = _start_server(_test_state('/nonexistent'))
        self.addCleanup(server.shutdown)
        raw = self._raw_request(
            server.server_port, b'GET /\xff/x HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n')
        self.assertIn(b'403', raw.split(b'\r\n', 1)[0])
        # A real rejection, not merely a closed socket: the body carries the code.
        self.assertIn(b'"code": "FORBIDDEN"', raw.replace(b'"code":"FORBIDDEN"',
                                                         b'"code": "FORBIDDEN"'))
        self.assertEqual(recorded, [])
        # The handler thread is still alive: a valid request still answers.
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        conn.request('GET', '/test-token/health')
        self.assertEqual(conn.getresponse().status, 200)

    def test_non_ascii_bearer_is_rejected_not_crashed(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        server = _start_server(_test_state('/nonexistent'))
        self.addCleanup(server.shutdown)
        raw = self._raw_request(
            server.server_port,
            b'POST /responses HTTP/1.1\r\nHost: 127.0.0.1\r\n'
            b'Authorization: Bearer \xff\r\nContent-Length: 2\r\n\r\n{}')
        self.assertIn(b'403', raw.split(b'\r\n', 1)[0])
        self.assertIn(b'FORBIDDEN', raw)
        self.assertEqual(recorded, [])

    def test_image_stall_hint_uses_the_pre_strip_snapshot(self):
        # Plan 093 Step 2: has_image is snapshotted before prepare() strips
        # images, so the Grok stall hint can still fire for an image turn.
        def stall():
            raise TimeoutError('timed out')
        install_fake(self, stall)
        server = self._server()
        payload = {'model': 'x-ai/grok-4.6', 'input': [
            {'type': 'message', 'role': 'user', 'content': [
                {'type': 'input_text', 'text': 'look'},
                {'type': 'input_image', 'image_url': 'data:x'}]}]}
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        conn.request('POST', '/test-token/responses', body=json.dumps(payload),
                     headers={'Content-Type': 'application/json'})
        response = conn.getresponse()
        self.assertEqual(response.status, 502)
        message = json.loads(response.read())['error']['message']
        self.assertIn('retry text-only', message)


if __name__ == '__main__':
    unittest.main()
