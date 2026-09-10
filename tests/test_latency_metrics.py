"""Plan 068: phase-separated latency fields with fake clocks.

Fake upstream + patched monotonic clock: each phase (read, prepare,
connect, send, header wait, first upstream data, first downstream
write) advances the clock by a fixed step, so the logged
request_completed event must carry the exact per-phase durations while
response bytes and statuses stay unchanged. Fails until the handler
records phase boundaries; the baseline handler/provider/safe-diagnostic
suites stay green throughout.
"""
import http.client
import itertools
import json
import logging
import time
import unittest
from unittest import mock

from ai_router.runtime import LOG
from tests.fakes import FakeUpstream, install_fake
from tests.test_handler import _auth_file, _post
from tests.test_mixed_router import _start_server, _test_state


class _ListHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        try:
            self.records.append(json.loads(record.getMessage()))
        except ValueError:
            pass


def _capture(test):
    handler = _ListHandler()
    # LOG defaults to NOTSET with no handlers: without an explicit level
    # the root WARNING gate drops INFO records before they reach us.
    old_level = LOG.level
    LOG.setLevel(logging.INFO)
    test.addCleanup(LOG.setLevel, old_level)
    LOG.addHandler(handler)
    test.addCleanup(LOG.removeHandler, handler)
    return handler


def _wait_for(handler, event, clock=time.monotonic, timeout_s=10):
    # The response reaches the client before the handler thread emits
    # its completion record; poll briefly instead of racing it. The
    # clock is injectable so fake-clock tests can pass the real clock:
    # polling with fake ticks would steal handler-thread readings and
    # flake the exact-duration asserts.
    deadline = clock() + timeout_s
    while clock() < deadline:
        found = [r for r in handler.records
                 if isinstance(r, dict) and r.get('event') == event]
        if found:
            return found
        time.sleep(0.001)
    return [r for r in handler.records
            if isinstance(r, dict) and r.get('event') == event]


class LatencyMetricTests(unittest.TestCase):
    def _server(self):
        server = _start_server(_test_state(_auth_file(self)))
        self.addCleanup(server.shutdown)
        return server

    def test_phase_fields_present_with_exact_fake_durations(self):
        install_fake(self, lambda: FakeUpstream(200, b'{"output": []}', []))
        handler = _capture(self)
        server = self._server()
        ticks = (1000 + i * 0.005 for i in itertools.count())
        real_clock = time.monotonic
        with mock.patch('ai_router.router.time.monotonic',
                        side_effect=lambda: next(ticks)):
            response = _post(server.server_port, '/test-token/responses',
                             {'model': 'z-ai/glm-5.3', 'input': []})
            self.assertEqual(response.status, 200)
            # Poll inside the fake-clock window: the completion record is
            # emitted after the response reaches the client, and readings
            # after the patch exits would mix real time into fake phases.
            done = _wait_for(handler, 'request_completed', real_clock)
        self.assertEqual(len(done), 1)
        event = done[0]
        # Transport phases are fully controlled: exactly one clock step
        # each. first_data/first_write are exact too, derived from
        # relay's own reads between headers_done and the markers:
        # upstream_headers_ms (+1 tick), first_chunk_ms (+1), then the
        # marker read itself (+1) = 3 ticks = 15ms; first_write adds the
        # wfile round trip (+1) = 20ms. Neither tool_adapter nor
        # providers.adapt calls the clock, so adapter internals cannot
        # shift these; moving any relay boundary fails this test by
        # design. (A buffering adapter's reads are still not network
        # TTFB; these fields mean headers-to-first-chunk-availability.)
        for phase in ('read_ms', 'prepare_ms', 'connect_ms', 'send_ms',
                      'headers_ms'):
            self.assertIn(phase, event)
            self.assertEqual(event[phase], 5.0)
        self.assertEqual(event['first_data_ms'], 15.0)
        self.assertEqual(event['first_write_ms'], 20.0)
        # Old cumulative fields keep their meaning.
        self.assertIn('local_prepare_ms', event)
        self.assertIn('total_ms', event)

    def test_response_shape_uses_fixed_categories(self):
        from ai_router.transport import describe_response
        from tests.fakes import FakeUpstream
        kind, encoding = describe_response(
            FakeUpstream(200, b'{}', [('Content-Type', 'text/event-stream')]))
        self.assertEqual((kind, encoding), ('sse', 'identity'))
        kind, encoding = describe_response(
            FakeUpstream(200, b'{}', [('Content-Type', 'application/json; charset=utf-8'),
                                      ('Content-Encoding', 'gzip')]))
        self.assertEqual((kind, encoding), ('json', 'gzip'))
        # Arbitrary upstream values map to generic buckets, never logs.
        kind, encoding = describe_response(
            FakeUpstream(200, b'{}', [('Content-Type', 'SYNTH-CANARY-068-TYPE'),
                                      ('Content-Encoding', 'SYNTH-CANARY-068-ENC')]))
        self.assertEqual((kind, encoding), ('other', 'other'))

    def test_canary_headers_never_reach_logs(self):
        marker = 'SYNTH-CANARY-068-9f2c'
        install_fake(self, lambda: FakeUpstream(
            200, b'{"output": []}',
            [('Content-Type', 'application/json'),
             ('X-Synth-Canary', 'prefix-%s-suffix' % marker)]))
        handler = _capture(self)
        server = self._server()
        response = _post(server.server_port, '/test-token/responses',
                         {'model': 'z-ai/glm-5.3', 'input': []})
        self.assertEqual(response.status, 200)
        done = _wait_for(handler, 'request_completed')
        self.assertEqual(len(done), 1)
        self.assertEqual(done[0]['response_kind'], 'json')
        text = '\n'.join(json.dumps(r) for r in handler.records)
        self.assertNotIn(marker, text)

    def test_failed_connect_records_phase_durations(self):
        class RefusedConn:
            def __init__(self, host, *args, **kwargs):
                pass

            def connect(self):
                raise OSError('SYNTH-CONNECT-REFUSED')

            def close(self):
                pass

        with mock.patch.object(http.client, 'HTTPSConnection', RefusedConn):
            handler = _capture(self)
            server = self._server()
            ticks = (2000 + i * 0.005 for i in itertools.count())
            real_clock = time.monotonic
            with mock.patch('ai_router.router.time.monotonic',
                            side_effect=lambda: next(ticks)):
                response = _post(server.server_port, '/test-token/responses',
                                 {'model': 'z-ai/glm-5.3', 'input': []})
                self.assertEqual(response.status, 502)
                errors = _wait_for(handler, 'transport_error', real_clock)
            self.assertEqual(len(errors), 1)
            for phase in ('read_ms', 'prepare_ms', 'connect_ms'):
                self.assertIn(phase, errors[0])
                self.assertEqual(errors[0][phase], 5.0)
            self.assertNotIn('send_ms', errors[0])
            self.assertNotIn('headers_ms', errors[0])

    def test_failed_send_records_phases_through_send(self):
        class SendFailsConn:
            def __init__(self, host, *args, **kwargs):
                pass

            def connect(self):
                pass

            def request(self, *args, **kwargs):
                raise OSError('SYNTH-SEND-RESET')

            def close(self):
                pass

        with mock.patch.object(http.client, 'HTTPSConnection', SendFailsConn):
            handler = _capture(self)
            server = self._server()
            ticks = (3000 + i * 0.005 for i in itertools.count())
            real_clock = time.monotonic
            with mock.patch('ai_router.router.time.monotonic',
                            side_effect=lambda: next(ticks)):
                response = _post(server.server_port, '/test-token/responses',
                                 {'model': 'z-ai/glm-5.3', 'input': []})
                self.assertEqual(response.status, 502)
                errors = _wait_for(handler, 'transport_error', real_clock)
            self.assertEqual(len(errors), 1)
            for phase in ('read_ms', 'prepare_ms', 'connect_ms', 'send_ms'):
                self.assertIn(phase, errors[0])
            self.assertNotIn('headers_ms', errors[0])

    def test_response_bytes_unchanged_with_phases(self):
        install_fake(self, lambda: FakeUpstream(200, b'{"output": []}', []))
        _capture(self)
        server = self._server()
        response = _post(server.server_port, '/test-token/responses',
                         {'model': 'z-ai/glm-5.3', 'input': []})
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(response.read()), {'output': []})


if __name__ == '__main__':
    unittest.main()
