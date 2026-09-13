"""A client that vanished mid-reply must not raise out of the handler.

A GET poller (health, model listing) that closes before its JSON reply is
flushed used to surface a BrokenPipeError traceback through socketserver's
default error printer, which wrote it to the service log. The writers now
absorb the disconnect and always close the connection.
"""
import json
import unittest

from ai_router import ingress


class _FakeWriter:
    def __init__(self, error):
        self.error = error
        self.written = []

    def write(self, body):
        if self.error is not None:
            raise self.error
        self.written.append(body)


class _FakeHandler:
    """Just enough of BaseHTTPRequestHandler for the reply writers."""

    def __init__(self, write_error=None, header_error=None):
        self.wfile = _FakeWriter(write_error)
        self.header_error = header_error
        self.close_connection = False
        self.status = None
        self.headers = []

    def send_response(self, status):
        self.status = status

    def send_header(self, key, value):
        self.headers.append((key, value))

    def end_headers(self):
        if self.header_error is not None:
            raise self.header_error


class ClientDisconnectReplyTests(unittest.TestCase):
    def test_send_json_survives_a_dropped_connection(self):
        for error in (BrokenPipeError(32, 'Broken pipe'),
                      ConnectionResetError(54, 'Connection reset by peer')):
            with self.subTest(error=error):
                handler = _FakeHandler(write_error=error)
                ingress.send_json(handler, 200, {'status': 'ok'})
                self.assertTrue(handler.close_connection)
                self.assertEqual(handler.status, 200)

    def test_send_json_survives_a_header_flush_failure(self):
        handler = _FakeHandler(header_error=BrokenPipeError(32, 'Broken pipe'))
        ingress.send_json(handler, 200, {'status': 'ok'})
        self.assertTrue(handler.close_connection)

    def test_connected_client_still_receives_the_body(self):
        handler = _FakeHandler()
        ingress.send_json(handler, 200, {'status': 'ok'})
        self.assertEqual(handler.wfile.written, [json.dumps({'status': 'ok'}).encode()])
        self.assertTrue(handler.close_connection)

    def test_context_error_stream_survives_a_dropped_connection(self):
        handler = _FakeHandler(write_error=BrokenPipeError(32, 'Broken pipe'))
        ingress.context_error(handler, True, log_event=lambda *a, **k: None)
        self.assertTrue(handler.close_connection)


if __name__ == '__main__':
    unittest.main()
