"""Plan 069: stream bytes must flow before identity inspection completes.

Pull-based proof, no threads or wall-clock timing: a consumption-counting
fake records how many upstream bytes were read when next(adapter) first
returns. A buffering adapter consumes the whole body before its first
yield; the observer must yield the first piece after bounded inspection.
Fully buffered fakes stay for byte-equality; these tests pin early forwarding.
"""
import gzip
import unittest

from compression import zstd

from ai_router.tool_adapter import snoop_response_identity
from tests.fakes import FakeUpstream


class CountingUpstream(FakeUpstream):
    """FakeUpstream that drips small pieces and records bytes consumed.

    read1 returns at most `piece` bytes per call so early forwarding is
    observable: a buffering adapter consumes everything before its
    first yield, a streaming one yields after the first piece.
    """

    def __init__(self, status, body_bytes, headers=(), piece=7):
        super().__init__(status, body_bytes, headers)
        self.consumed = 0
        self._piece = piece

    def read1(self, count):
        # Bypass FakeUpstream.read1 (it delegates to read, which would
        # double-tally): slice the buffer directly in small pieces.
        data = self._buf[self._pos:self._pos + min(count, self._piece)]
        self._pos += len(data)
        self.consumed += len(data)
        return data

    def read(self, amt=None):
        # Whole-body reads (the old buffering behavior) tally in full.
        data = super().read(amt)
        self.consumed += len(data)
        return data


class StreamingIdentityTests(unittest.TestCase):
    def test_first_yield_precedes_full_consumption(self):
        events = (b'event: response.completed\n'
                  b'data: {"type": "response.completed", '
                  b'"response": {"model": "x-ai/grok-4.6"}}\n\n')
        bodies = {
            'json': (b'{"id": "resp_1", "model": "x-ai/grok-4.6", "output": []}', []),
            'gzip': (gzip.compress(events),
                     [('Content-Type', 'text/event-stream'), ('Content-Encoding', 'gzip')]),
            'zstd': (zstd.compress(events),
                     [('Content-Type', 'text/event-stream'), ('Content-Encoding', 'zstd')]),
        }
        for name, (body, headers) in bodies.items():
            with self.subTest(body=name):
                upstream = CountingUpstream(200, body, headers)
                adapter = snoop_response_identity(upstream, {})
                first = next(adapter)
                self.assertTrue(first)
                self.assertLess(upstream.consumed, len(body))
                rest = b''.join(adapter)
                self.assertEqual(first + rest, body)

    def test_empty_body_yields_nothing_without_identity(self):
        upstream = CountingUpstream(200, b'', [])
        notes = {}
        out = b''.join(snoop_response_identity(upstream, notes))
        self.assertEqual(out, b'')
        self.assertEqual(notes, {})

    def test_partial_line_sse_first_yield_precedes_rest(self):
        # No newline in the first piece: a line-buffered inspector would
        # hold it waiting for LF that only arrives in the second piece.
        first_piece = b'data: {"type": "response.completed", "respo'
        second_piece = b'nse": {"model": "x"}}\n\n'
        upstream = CountingUpstream(
            200, first_piece + second_piece,
            [('Content-Type', 'text/event-stream')])
        adapter = snoop_response_identity(upstream, {})
        first = next(adapter)
        self.assertTrue(first)
        self.assertLessEqual(upstream.consumed, len(first_piece) + 1)
        rest = b''.join(adapter)
        self.assertEqual(first + rest, first_piece + second_piece)

    def test_oversized_json_disables_observation_not_forwarding(self):
        big = b'{"model": "x-ai/grok-4.6", "output": ["' + b'x' * 70000 + b'"]}'
        upstream = CountingUpstream(200, big, [])
        notes = {}
        out = b''.join(snoop_response_identity(upstream, notes))
        self.assertEqual(out, big)
        self.assertNotIn('served_model', notes)

    def test_malformed_json_forwards_without_identity(self):
        body = b'not json at all'
        upstream = CountingUpstream(200, body, [])
        notes = {}
        out = b''.join(snoop_response_identity(upstream, notes))
        self.assertEqual(out, body)
        self.assertEqual(notes, {})

    def test_identity_stays_fresh_across_responses(self):
        # A later response reporting a different model overwrites; an
        # unobservable one leaves the prior observation intact (freshness
        # means never substituting a stale entry for a new observation,
        # not clearing on unobservable bodies).
        notes = {}
        first = b'{"model": "model-a", "output": []}'
        out = b''.join(snoop_response_identity(
            CountingUpstream(200, first, []), notes))
        self.assertEqual(out, first)
        self.assertEqual(notes, {'served_model': 'model-a'})
        second = b'{"model": "model-b", "output": []}'
        out = b''.join(snoop_response_identity(
            CountingUpstream(200, second, []), notes))
        self.assertEqual(out, second)
        self.assertEqual(notes, {'served_model': 'model-b'})
        # An unobservable body afterwards leaves the prior entry intact.
        out = b''.join(snoop_response_identity(
            CountingUpstream(200, b'not json', []), notes))
        self.assertEqual(out, b'not json')
        self.assertEqual(notes, {'served_model': 'model-b'})

    def test_deeply_nested_json_never_breaks_forwarding(self):
        nested = b'[' * 2000 + b']' * 2000
        upstream = CountingUpstream(200, nested, [])
        notes = {}
        out = b''.join(snoop_response_identity(upstream, notes))
        self.assertEqual(out, nested)
        self.assertEqual(notes, {})

    def test_deeply_nested_sse_data_never_breaks_forwarding(self):
        frame = (b'data: ' + b'{"type": "x", "v": [' * 500 + b']}' + b'\n\n')
        upstream = CountingUpstream(
            200, frame, [('Content-Type', 'text/event-stream')])
        notes = {}
        out = b''.join(snoop_response_identity(upstream, notes))
        self.assertEqual(out, frame)
        self.assertEqual(notes, {})

    def test_never_terminated_sse_bounds_observation(self):
        body = b'data: ' + b'x' * (3 * 65536) + b'\n'
        upstream = CountingUpstream(
            200, body, [('Content-Type', 'text/event-stream')])
        notes = {}
        out = b''.join(snoop_response_identity(upstream, notes))
        self.assertEqual(out, body)
        self.assertEqual(notes, {})

    def test_aligned_truncated_prefix_is_not_parsed(self):
        # 64 KiB-aligned pieces: the first piece alone is valid JSON with
        # a model, but more body follows, so the prefix must not observe.
        prefix = b'{"model": "model-a"}' + b' ' * (65536 - 20)
        self.assertEqual(len(prefix), 65536)
        body = prefix + b'{"model": "model-b"}'
        upstream = CountingUpstream(200, body, [], piece=65536)
        notes = {}
        out = b''.join(snoop_response_identity(upstream, notes))
        self.assertEqual(out, body)
        self.assertEqual(notes, {})

    def test_truncated_prefix_is_not_parsed(self):
        prefix = b'{"model": "model-a", "pad": "'
        body = prefix + b'x' * (70000 - len(prefix)) + b'"]}'
        self.assertGreater(len(body), 65536)
        upstream = CountingUpstream(200, body, [])
        notes = {}
        out = b''.join(snoop_response_identity(upstream, notes))
        self.assertEqual(out, body)
        self.assertEqual(notes, {})


if __name__ == '__main__':
    unittest.main()
