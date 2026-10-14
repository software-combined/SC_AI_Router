"""Lease accounting, ownership and diagnostic contracts, without sockets."""
import json
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

from ai_router import errors, ingress, request_lease, transport
from ai_router.subscription_fallback import Plan

CAP = 2000
THREAD = '11111111-1111-4111-8111-111111111111'


class RequestLeaseStateTests(unittest.TestCase):
    def setUp(self):
        self.server = SimpleNamespace(lock=threading.Lock(), draining=False,
                                      state={'token': 'secret-url'})
        request_lease.initialize(self.server)
        for name, value in (('LARGE_REQUEST_BUDGET_BYTES', 3000), ('LARGE_REQUEST_WAIT_S', 0)):
            patcher = mock.patch.object(request_lease, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.events = []

    def log(self, event, **fields):
        self.assertTrue(self.server.lock.acquire(blocking=False), 'logging under server lock')
        self.server.lock.release()
        self.events.append(dict(event=event, **fields))

    def handler(self):
        handler = SimpleNamespace(server=self.server, headers={
            'thread-id': THREAD, 'x-codex-parent-thread-id': 'bad-secret-id',
            'Authorization': 'secret-auth'}, path='/secret-url/responses')
        request_lease.begin(handler, 'test-version')
        return handler

    def prepared(self, size, **extras):
        return transport.Prepared('test.example', '/responses', {}, b'x' * size,
                                  {}, 'openai', decoded_body_bytes=size, **extras)

    def take(self, handler):
        self.assertTrue(request_lease.acquire(handler, 'wire', self.log, wire_bytes=3000))

    def held(self, handler):
        return handler.lease_facts['request_id'] in self.server.large_request_reservations

    def test_small_prepared_boundary_and_retained_data(self):
        # A real lazy fallback plan retains the original history until a refusal.
        fallback = Plan(None, '/responses', {'input': 'secret-content' * 1000},
                        b'raw-history' * 1000, {}, None)
        cases = ((CAP, {}, True), (CAP + 1, {}, False),
                 (100, {'fallback': fallback}, False),
                 (100, {'response_adapter': object()}, False))
        for size, extras, releases in cases:
            with self.subTest(size=size, extras=list(extras)):
                handler = self.handler()
                self.take(handler)
                request_lease.downgrade(handler, self.prepared(size, **extras), CAP, self.log)
                self.assertEqual(self.held(handler), not releases)
                request_lease.release(handler, 'request_end', self.log)
                self.assertEqual(self.server.large_request_bytes, 0)

    def test_small_wire_with_large_decoded_body_keeps_the_lease(self):
        handler = self.handler()
        self.take(handler)
        prepared = self.prepared(20)
        prepared.headers = {'Content-Encoding': 'zstd'}
        prepared.decoded_body_bytes = CAP + 1
        request_lease.downgrade(handler, prepared, CAP, self.log)
        self.assertTrue(self.held(handler))
        request_lease.release(handler, 'request_end', self.log)

    def test_real_sixteen_mib_boundary(self):
        threshold = 16 * 1024 * 1024
        for size in (threshold, threshold + 1):
            handler = self.handler()
            self.take(handler)
            request_lease.downgrade(handler, self.prepared(size), threshold, self.log)
            self.assertEqual(self.held(handler), size > threshold)
            request_lease.release(handler, 'request_end', self.log)

    def test_retry_reacquires_or_refuses_before_send(self):
        for busy in (False, True):
            with self.subTest(busy=busy):
                first, second = self.handler(), self.handler()
                self.take(first)
                request_lease.downgrade(first, self.prepared(1200), CAP, self.log)
                if busy:
                    self.take(second)
                    with self.assertRaises(errors.OversizeBusy):
                        request_lease.admit(first, self.prepared(1100),
                                            self.prepared(1200), CAP, self.log)
                    self.assertFalse(self.held(first))
                    self.assertEqual(first.lease_busy['stage'], 'retry')
                    self.assertEqual(first.lease_busy['retained_accounted_bytes'], 2300)
                    request_lease.release(second, 'request_end', self.log)
                else:
                    request_lease.admit(first, self.prepared(1100),
                                        self.prepared(1200), CAP, self.log)
                    self.assertTrue(self.held(first))
                    self.assertEqual(self.server.large_request_reservations[
                        first.lease_facts['request_id']]['stage'], 'retry')
                    request_lease.release(first, 'request_end', self.log)
                self.assertEqual(self.server.large_request_bytes, 0)

    def test_busy_snapshot_and_previous_borrower_do_not_follow_new_owner(self):
        first, rejected, next_owner = self.handler(), self.handler(), self.handler()
        self.take(first)
        self.assertFalse(request_lease.acquire(rejected, 'decode', self.log,
                                              wire_bytes=10, decoded_lower_bound_bytes=2001))
        request_lease.release(first, 'prepared_small', self.log)
        self.take(next_owner)
        request_lease.release(first, 'request_end', self.log)
        self.assertTrue(self.held(next_owner))
        rejected.send_json = lambda *_args: True
        ingress.error(rejected, errors.oversize_busy(), log_event=self.log, retry_after='2')
        refusal = self.events[-1]
        self.assertEqual((refusal['holders'], refusal['budget_used_bytes']), (1, 3000))
        self.assertGreaterEqual(refusal['owner_held_ms'], 0)
        self.assertEqual(refusal['decoded_lower_bound_bytes'], 2001)
        self.assertNotIn('decoded_bytes', refusal)
        self.assertNotIn('model', refusal)
        self.assertEqual(refusal['thread_id'], THREAD)
        self.assertNotIn('parent_thread_id', refusal)
        self.assertNotIn('secret-', json.dumps(self.events))
        request_lease.release(next_owner, 'request_end', self.log)

    def test_new_post_resets_facts_and_each_acquisition_releases_once(self):
        handler = self.handler()
        old_id = handler.lease_facts['request_id']
        self.take(handler)
        request_lease.release(handler, 'request_end', self.log)
        request_lease.release(handler, 'request_end', self.log)
        handler.lease_busy = {'owner_request_id': 'stale'}
        handler.lease_facts['decoded_lower_bound_bytes'] = 2001
        request_lease.begin(handler, 'next-version')
        self.assertNotEqual(handler.lease_facts['request_id'], old_id)
        self.assertEqual(handler.lease_busy, {})
        self.assertNotIn('decoded_lower_bound_bytes', handler.lease_facts)
        self.take(handler)
        request_lease.read_complete(handler, 20, 3000)
        request_lease.release(handler, 'request_end', self.log)
        acquired = [e['request_id'] for e in self.events if e['event'] == 'oversize_slot_acquired']
        released = [e['request_id'] for e in self.events if e['event'] == 'oversize_slot_released']
        self.assertEqual(acquired, released)
        self.assertEqual(len(released), 2)


if __name__ == '__main__':
    unittest.main()
