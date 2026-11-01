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
    def __init__(self, error, flush_error=None):
        self.error = error
        self.flush_error = flush_error
        self.written = []

    def write(self, body):
        if self.error is not None:
            raise self.error
        self.written.append(body)
        return len(body)

    def flush(self):
        if self.flush_error is not None:
            raise self.flush_error


class _FakeHandler:
    """Just enough of BaseHTTPRequestHandler for the reply writers."""

    def __init__(self, write_error=None, header_error=None, flush_error=None):
        self.wfile = _FakeWriter(write_error, flush_error)
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
                self.assertFalse(ingress.send_json(handler, 200, {'status': 'ok'}))
                self.assertTrue(handler.close_connection)
                self.assertEqual(handler.status, 200)
                self.assertTrue(handler.response_committed)

    def test_send_json_survives_a_header_flush_failure(self):
        handler = _FakeHandler(header_error=BrokenPipeError(32, 'Broken pipe'))
        self.assertFalse(ingress.send_json(handler, 200, {'status': 'ok'}))
        self.assertTrue(handler.close_connection)
        self.assertFalse(handler.response_committed)

    def test_connected_client_still_receives_the_body(self):
        handler = _FakeHandler()
        self.assertTrue(ingress.send_json(handler, 200, {'status': 'ok'}))
        self.assertEqual(handler.wfile.written, [json.dumps({'status': 'ok'}).encode()])
        self.assertTrue(handler.close_connection)

    def test_context_error_stream_survives_a_dropped_connection(self):
        handler = _FakeHandler(write_error=BrokenPipeError(32, 'Broken pipe'))
        self.assertFalse(ingress.context_error(
            handler, True, log_event=lambda *a, **k: None))
        self.assertTrue(handler.close_connection)

    def test_reply_writers_contain_closed_writer_value_error(self):
        for write in (
                lambda handler: ingress.send_json(handler, 200, {'status': 'ok'}),
                lambda handler: ingress.context_error(
                    handler, True, log_event=lambda *a, **k: None),
                lambda handler: ingress.send_compaction_stream(
                    handler, [{'type': 'compaction', 'summary': 'synthetic'}]),
        ):
            with self.subTest(write=write):
                handler = _FakeHandler(flush_error=ValueError('closed file'))
                self.assertIn(write(handler), (None, False))
                self.assertTrue(handler.close_connection)


if __name__ == '__main__':
    unittest.main()
