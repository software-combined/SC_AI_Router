"""Oversized routed turns: decode headroom, one read at a time, attribution.

The 2026-09-16 thread (01a0ab7c) died at ingress: 2,690 released-tool search
results carried 67 MB of decoded history, past the four-times decode ceiling
that exists so prepare can slim exactly that shape. These cases pin the two
answers: a bigger, single-slot headroom, and a refusal line that names what
the turn carried.

The 2026-09-18 thread (01a0b155) died one gate earlier: ten attached images
compressed to 17.6 MB, past the 16 MiB cap on the wire, so the declared-size
check answered a framing error and the trim that could have served the turn
never ran. A zstd body is read up to the decode ceiling and decided on the
size it decodes to, which is what these cases now hold it to.
"""
import http.client
import json
import random
import string
import unittest
from unittest import mock
from compression import zstd

from ai_router import router as router_mod
from tests.fakes import FakeUpstream, install_fake
from tests.harness import (
    auth_file as _auth_file, scaled_limits,
    start_server as _start_server,
    test_state as _test_state,
)

TOKEN = 'test-token'
MODEL = 'deepseek/deepseek-v4.1-flash'


def _search_payload(description):
    return {'model': MODEL,
            'input': [{'type': 'tool_search_output', 'call_id': 's1',
                       'tools': [{'type': 'namespace', 'name': 'probe',
                                  'description': 'probe tools',
                                  'tools': [{'type': 'function', 'name': 'echo',
                                             'description': description,
                                             'parameters': {'type': 'object'}}]}]}],
            'tools': [{'type': 'tool_search', 'description': 'search',
                       'parameters': {'type': 'object'}}]}


def _paired(outputs):
    call = {'type': 'tool_search_call', 'execution': 'client', 'arguments': {'query': 'echo'}}
    return [part for out in outputs for part in (dict(call, call_id=out['call_id']), out)]


def _repeated_search_payload(copies, schema_pad):
    """The 2026-09-16 shape: the same released tool, searched again and again.

    Prepare hoists one copy into the tool list and keeps the rest as names and
    descriptions, so the turn is oversized while reading and small upstream.
    """
    item = _search_payload('d' * 40)['input'][0]
    item['tools'][0]['tools'][0]['parameters'] = {
        'type': 'object',
        'properties': {'q': {'type': 'string', 'description': 'p' * schema_pad}}}
    return {'model': MODEL,
            'input': _paired(dict(item, call_id='s%d' % index) for index in range(copies)),
            'tools': [{'type': 'tool_search', 'description': 'search',
                       'parameters': {'type': 'object'}}]}


def _noise(seed, size):
    """Deterministic text with no repeats, so zstd barely shrinks it."""
    alphabet = string.ascii_letters + string.digits
    return ''.join(random.Random(seed).choices(alphabet, k=size))


def _noisy_search_payload(copies, pad):
    """The 2026-09-18 shape: every released copy carries its own schema text.

    The padding is incompressible and unique per copy, so the body stays past
    the ordinary cap on the wire while prepare still collapses every copy but
    the newest.
    """
    def listing(index):
        tool = {'type': 'function', 'name': 'echo', 'description': 'Echo',
                'parameters': {'type': 'object',
                               'properties': {'q': {'type': 'string',
                                                    'description': _noise(index, pad)}}}}
        return {'type': 'tool_search_output', 'call_id': 's%d' % index,
                'tools': [{'type': 'namespace', 'name': 'probe',
                           'description': 'probe tools', 'tools': [tool]}]}

    return {'model': MODEL,
            'input': _paired(listing(index) for index in range(copies)),
            'tools': [{'type': 'tool_search', 'description': 'search',
                       'parameters': {'type': 'object'}}]}


class OversizeIngressTests(unittest.TestCase):
    def setUp(self):
        self.server = _start_server(_test_state(_auth_file(self)))
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def raw_request(self, header_lines, body=b''):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
        self.addCleanup(conn.close)
        conn.putrequest('POST', '/%s/responses' % TOKEN)
        for line in header_lines:
            key, _, value = line.partition(': ')
            conn.putheader(key, value)
        conn.endheaders()
        if body:
            conn.send(body)
        return conn.getresponse()

    def zstd_headers(self, packed):
        return ['Content-Type: application/json', 'Content-Encoding: zstd',
                'Content-Length: %d' % len(packed)]

    def refusals(self, logged):
        return [call for call in logged.call_args_list
                if call.args and call.args[0] == 'turn_refused']

    def test_a_body_past_the_decode_ceiling_is_refused_with_its_sizes(self):
        payload = _search_payload('x' * 4000)
        wire = json.dumps(payload).encode()
        packed = zstd.compress(wire)
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        cap, ceiling = 600, 3600
        with scaled_limits(cap, ceiling), \
                mock.patch.object(router_mod, 'log_event') as logged:
            self.assertGreater(len(wire), ceiling)
            self.assertLess(len(packed), cap)
            response = self.raw_request(self.zstd_headers(packed), packed)
            self.assertEqual(response.status, 400)
            self.assertEqual(json.loads(response.read())['error']['code'], 'BODY_TOO_LARGE')
        self.assertEqual(recorded, [])
        refusals = self.refusals(logged)
        self.assertEqual(len(refusals), 1)
        facts = refusals[0].kwargs
        self.assertEqual(facts['code'], 'BODY_TOO_LARGE')
        self.assertEqual(facts['compressed_bytes'], len(packed))
        self.assertEqual(facts['decode_limit_bytes'], ceiling)
        self.assertNotIn('decoded_bytes', facts)

    def test_a_prepared_body_past_the_ceiling_names_the_carried_classes(self):
        # Prepare re-serializes with escapes, so two bytes of 'é' become six.
        wire = json.dumps(_search_payload('é' * 1300), ensure_ascii=False).encode()
        packed = zstd.compress(wire)
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        cap, ceiling = 2000, 4000
        with scaled_limits(cap, ceiling), \
                mock.patch.object(router_mod, 'log_event') as logged:
            self.assertTrue(cap < len(wire) < ceiling)
            response = self.raw_request(self.zstd_headers(packed), packed)
            self.assertEqual(response.status, 400)
            self.assertEqual(json.loads(response.read())['error']['code'], 'BODY_TOO_LARGE')
        self.assertEqual(recorded, [])
        refusals = self.refusals(logged)
        self.assertEqual(len(refusals), 1)
        facts = refusals[0].kwargs
        self.assertEqual(facts['decoded_bytes'], len(wire))
        self.assertEqual(facts['tool_search_output'], 1)
        self.assertGreater(facts['tool_search_output_bytes'], 0)
        self.assertGreater(facts['prepared_bytes'], ceiling)

    def test_only_one_oversized_read_runs_at_a_time(self):
        # The slot is taken on decoded bytes, not the declared size: these
        # bodies compress far too well for a declared-size gate to hold.
        payload = _repeated_search_payload(copies=8, schema_pad=500)
        packed = zstd.compress(json.dumps(payload).encode())
        headers = self.zstd_headers(packed)
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        cap = 3500
        with mock.patch.object(router_mod, 'MAX_BODY', cap):
            self.assertGreater(len(json.dumps(payload).encode()), cap)
            self.assertTrue(self.server.oversize_lock.acquire(blocking=False))
            try:
                response = self.raw_request(headers, packed)
                self.assertEqual(response.status, 503)
                self.assertEqual(response.getheader('Retry-After'), '2')
                self.assertEqual(json.loads(response.read())['error']['code'],
                                 'OVERSIZE_BUSY')
                self.assertEqual(recorded, [])
            finally:
                self.server.oversize_lock.release()
            response = self.raw_request(headers, packed)
            self.assertEqual(response.status, 200)
            response.read()
            self.assertEqual(len(recorded), 1)
            # Oversized while reading, small by the time upstream sees it.
            self.assertLess(len(recorded[0][3]), cap)
            # The slot is free again once the turn has finished.
            self.assertTrue(self.server.oversize_lock.acquire(timeout=5))
            self.server.oversize_lock.release()

    def test_a_small_zstd_body_never_waits_on_the_slot(self):
        payload = {'model': MODEL, 'input': [], 'note': 'x' * 40}
        packed = zstd.compress(json.dumps(payload).encode())
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        self.assertTrue(self.server.oversize_lock.acquire(blocking=False))
        try:
            response = self.raw_request(self.zstd_headers(packed), packed)
            self.assertEqual(response.status, 200)
            response.read()
        finally:
            self.server.oversize_lock.release()
        self.assertEqual(len(recorded), 1)

    def test_a_zstd_body_past_the_cap_on_the_wire_is_read_and_served(self):
        # The 2026-09-18 refusal: 17.6 MB compressed against the 16 MiB cap.
        # The declared size is past the cap and so is the decoded size, so the
        # slot is taken on the way in and kept when the decode asks again.
        payload = _noisy_search_payload(copies=12, pad=800)
        wire = json.dumps(payload).encode()
        packed = zstd.compress(wire)
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        cap = 5000
        with scaled_limits(cap):
            self.assertGreater(len(packed), cap)
            self.assertGreater(len(wire), cap)
            self.assertLess(len(wire), cap * 6)
            response = self.raw_request(self.zstd_headers(packed), packed)
            self.assertEqual(response.status, 200)
            response.read()
        self.assertEqual(len(recorded), 1)
        self.assertLess(len(recorded[0][3]), cap)
        # The pre-read acquire is released with the turn, not left held.
        self.assertTrue(self.server.oversize_lock.acquire(timeout=5))
        self.server.oversize_lock.release()

    def test_a_zstd_body_decoding_past_the_ceiling_is_refused_as_too_large(self):
        # Reading to the decode ceiling is not raising it: a body past the cap
        # on the wire that decodes past the ceiling is refused on the size it
        # decodes to, before any upstream call.
        payload = {'model': MODEL,
                   'input': [{'type': 'message', 'role': 'user',
                              'content': 'x' * 20000 + _noise(13, 1000)}]}
        wire = json.dumps(payload).encode()
        packed = zstd.compress(wire)
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        cap = 700
        with scaled_limits(cap):
            self.assertGreater(len(packed), cap)
            self.assertGreater(len(wire), cap * 6)
            response = self.raw_request(self.zstd_headers(packed), packed)
            self.assertEqual(response.status, 400)
            self.assertEqual(json.loads(response.read())['error']['code'],
                             'BODY_TOO_LARGE')
            # Refused after the read, so the slot it took is free again; the
            # handler frees it just after answering, so allow it a moment.
            self.assertTrue(self.server.oversize_lock.acquire(timeout=5))
            self.server.oversize_lock.release()
        self.assertEqual(recorded, [])

    def test_a_zstd_body_past_the_ceiling_on_the_wire_is_too_large_not_malformed(self):
        # Refused before the read, but on the size the turn carries, not as a
        # framing error the client cannot act on.
        payload = {'model': MODEL,
                   'input': [{'type': 'message', 'role': 'user',
                              'content': _noise(11, 4000)}]}
        packed = zstd.compress(json.dumps(payload).encode())
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        cap, ceiling = 900, 2000
        with scaled_limits(cap, ceiling):
            self.assertGreater(len(packed), ceiling)
            response = self.raw_request(self.zstd_headers(packed), packed)
            self.assertEqual(response.status, 400)
            self.assertEqual(json.loads(response.read())['error']['code'],
                             'BODY_TOO_LARGE')
            # Refused before the slot is asked for, so none is left held.
            self.assertTrue(self.server.oversize_lock.acquire(timeout=5))
            self.server.oversize_lock.release()
        self.assertEqual(recorded, [])

    def test_a_body_past_the_cap_on_the_wire_waits_for_the_slot(self):
        # The read is the other half of the slot's job: a body this size is not
        # read while another oversized turn holds it, so it answers the same
        # retryable 503 rather than queueing the bytes in memory.
        payload = _noisy_search_payload(copies=12, pad=800)
        packed = zstd.compress(json.dumps(payload).encode())
        headers = self.zstd_headers(packed)
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        cap = 4000
        with mock.patch.object(router_mod, 'MAX_BODY', cap):
            self.assertGreater(len(packed), cap)
            self.assertTrue(self.server.oversize_lock.acquire(blocking=False))
            try:
                response = self.raw_request(headers, packed)
                self.assertEqual(response.status, 503)
                self.assertEqual(response.getheader('Retry-After'), '2')
                self.assertEqual(json.loads(response.read())['error']['code'],
                                 'OVERSIZE_BUSY')
                self.assertEqual(recorded, [])
                # Headers alone prove the ask precedes the read: with the slot
                # held, this is answered without the body ever being sent.
                response = self.raw_request(headers)
                self.assertEqual(response.status, 503)
                self.assertEqual(json.loads(response.read())['error']['code'],
                                 'OVERSIZE_BUSY')
            finally:
                self.server.oversize_lock.release()
