"""Ingress guard coverage (Plan 092): websocket, Transfer-Encoding, zstd bound.

Fake upstream only; never opens a real network connection. Each test
asserts the rejection status plus the stable error code and that no
upstream call is recorded, so removing its guard branch fails the test.
Reuses the shared helpers in tests/harness.py.
"""
import http.client
import json
import socket
import threading
import unittest
from unittest import mock
from compression import zstd
from ai_router import router as router_mod
from tests.fakes import FakeUpstream, install_fake
from tests.harness import (
    auth_file as _auth_file,
    start_server as _start_server,
    test_state as _test_state,
)


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

    def test_a_foreign_host_is_forbidden_before_routing(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        server = self._server()
        for host in ('evil.example', '127.0.0.1.evil.example',
                     'localhost.evil.example', '[::1]'):
            with self.subTest(host=host):
                conn = http.client.HTTPConnection('127.0.0.1', server.server_port,
                                                  timeout=10)
                self.addCleanup(conn.close)
                conn.request('GET', '/test-token/health', headers={'Host': host})
                response = conn.getresponse()
                self.assertEqual(response.status, 403)
                self.assertEqual(json.loads(response.read())['error']['code'],
                                 'FORBIDDEN')
        self.assertEqual(recorded, [])

    def test_a_foreign_host_is_refused_even_with_a_loopback_origin(self):
        # The guard runs before the Origin exemption, so a page that does send
        # an Origin still cannot reach a route through a rebound name.
        server = self._server()
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        self.addCleanup(conn.close)
        conn.request('GET', '/test-token/health', headers={
            'Host': 'evil.example',
            'Origin': f'http://127.0.0.1:{server.server_port}'})
        response = conn.getresponse()
        self.assertEqual(response.status, 403)
        self.assertEqual(json.loads(response.read())['error']['code'], 'FORBIDDEN')

    def test_loopback_hosts_still_answer(self):
        server = self._server()
        for host in (f'127.0.0.1:{server.server_port}',
                     f'localhost:{server.server_port}', '127.0.0.1',
                     'LOCALHOST'):
            with self.subTest(host=host):
                conn = http.client.HTTPConnection('127.0.0.1', server.server_port,
                                                  timeout=10)
                self.addCleanup(conn.close)
                conn.request('GET', '/test-token/health', headers={'Host': host})
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read())['status'], 'ok')

    def test_a_hostless_http10_request_still_answers(self):
        server = self._server()
        raw = self._raw_request(
            server.server_port, b'GET /test-token/health HTTP/1.0\r\n\r\n')
        self.assertIn(b'200', raw.split(b'\r\n', 1)[0])

    def test_a_non_json_content_type_is_415_before_parsing(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        server = self._server()
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        self.addCleanup(conn.close)
        conn.request('POST', '/test-token/responses',
                     body=json.dumps({'model': 'z-ai/glm-5.3', 'input': []}),
                     headers={'Content-Type': 'text/plain'})
        response = conn.getresponse()
        self.assertEqual(response.status, 415)
        self.assertEqual(json.loads(response.read())['error']['code'],
                         'UNSUPPORTED_MEDIA_TYPE')
        self.assertEqual(recorded, [])

    def test_a_json_charset_parameter_is_still_accepted(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{"output": []}', []))
        server = self._server()
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        self.addCleanup(conn.close)
        conn.request('POST', '/test-token/responses',
                     body=json.dumps({'model': 'z-ai/glm-5.3', 'input': []}),
                     headers={'Content-Type': 'application/json; charset=utf-8'})
        self.assertEqual(conn.getresponse().status, 200)
        self.assertEqual(len(recorded), 1)

    def test_the_concurrency_cap_answers_429_with_retry_after(self):
        server = self._server()
        server.max_inflight = 0
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        self.addCleanup(conn.close)
        conn.request('POST', '/test-token/responses',
                     body=json.dumps({'model': 'z-ai/glm-5.3', 'input': []}),
                     headers={'Content-Type': 'application/json'})
        response = conn.getresponse()
        self.assertEqual(response.status, 429)
        self.assertEqual(response.getheader('Retry-After'), '1')
        self.assertEqual(json.loads(response.read())['error']['code'],
                         'TOO_MANY_REQUESTS')

    def test_health_reports_the_concurrency_cap_and_count(self):
        server = self._server()
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        self.addCleanup(conn.close)
        conn.request('GET', '/test-token/health')
        body = json.loads(conn.getresponse().read())
        self.assertEqual(body['max_inflight'], router_mod.MAX_INFLIGHT)
        self.assertEqual(body['inflight'], 0)

    def test_a_second_request_over_the_cap_is_rejected_while_one_is_in_flight(self):
        released = threading.Event()
        started = threading.Event()

        class Blocking(FakeUpstream):
            def read(self, amt=None):
                started.set()
                released.wait(5)
                return super().read(amt)

        install_fake(self, lambda: Blocking(200, b'{"output": []}', []))
        server = self._server()
        server.max_inflight = 1
        first = {}

        def slow_request():
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
            conn.request('POST', '/test-token/responses',
                         body=json.dumps({'model': 'z-ai/glm-5.3', 'input': []}),
                         headers={'Content-Type': 'application/json'})
            first['status'] = conn.getresponse().status
            conn.close()

        thread = threading.Thread(target=slow_request, daemon=True)
        thread.start()
        try:
            self.assertTrue(started.wait(5), 'the first request never reached upstream')
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
            self.addCleanup(conn.close)
            conn.request('POST', '/test-token/responses',
                         body=json.dumps({'model': 'z-ai/glm-5.3', 'input': []}),
                         headers={'Content-Type': 'application/json'})
            response = conn.getresponse()
            self.assertEqual(response.status, 429)
            response.read()
        finally:
            released.set()
            thread.join(5)
        self.assertEqual(first.get('status'), 200)

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
