"""Shared byte budget waiting, growth and ownership without large allocations."""
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

from ai_router import errors, request_lease, transport

MIB = 1024 * 1024


class RequestBudgetStateTests(unittest.TestCase):
    def setUp(self):
        self.server = SimpleNamespace(lock=threading.Lock(), draining=False)
        request_lease.initialize(self.server)
        self.events = []
        patcher = mock.patch.object(request_lease, 'LARGE_REQUEST_BUDGET_BYTES', 40 * MIB)
        patcher.start()
        self.addCleanup(patcher.stop)

    def log(self, event, **fields):
        self.assertTrue(self.server.lock.acquire(blocking=False), 'logging under lock')
        self.server.lock.release()
        self.events.append(dict(event=event, **fields))

    def handler(self):
        handler = SimpleNamespace(server=self.server, headers={})
        request_lease.begin(handler, 'test')
        self.addCleanup(request_lease.release, handler, 'request_end', self.log)
        return handler

    def take(self, handler, size):
        return request_lease.acquire(handler, 'wire', self.log, wire_bytes=size)

    def waiting_request(self, handler, size):
        waiting, done = threading.Event(), threading.Event()
        result = []
        original_wait = self.server.large_request_condition.wait

        def wait(timeout):
            waiting.set()
            return original_wait(timeout)

        def run():
            try:
                result.append(self.take(handler, size))
            except errors.OversizeBusy as exc:
                result.append(exc.error.code)
            finally:
                done.set()

        patcher = mock.patch.object(self.server.large_request_condition, 'wait', wait)
        patcher.start()
        self.addCleanup(patcher.stop)
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.assertTrue(waiting.wait(2), 'request never waited for budget')
        return result, done

    def test_release_wakes_a_third_request_after_two_fill_budget(self):
        first, second, third = self.handler(), self.handler(), self.handler()
        self.assertTrue(self.take(first, 20 * MIB))
        self.assertTrue(self.take(second, 20 * MIB))
        result, done = self.waiting_request(third, 20 * MIB)
        self.assertFalse(done.is_set())
        request_lease.release(first, 'request_end', self.log)
        self.assertTrue(done.wait(2))
        self.assertEqual(result, [True])
        self.assertEqual(self.server.large_request_bytes, 40 * MIB)
        acquired = next(e for e in self.events if e['event'] == 'oversize_slot_acquired'
                        and e['request_id'] == third.lease_facts['request_id'])
        self.assertEqual(acquired['holders'], 2)
        self.assertIn('waited_ms', acquired)

    def test_timeout_snapshots_budget_and_oldest_holder(self):
        first, blocked = self.handler(), self.handler()
        self.assertTrue(self.take(first, 40 * MIB))
        with mock.patch.object(request_lease, 'LARGE_REQUEST_WAIT_S', 0.05):
            result, done = self.waiting_request(blocked, 20 * MIB)
            self.assertTrue(done.wait(2))
        self.assertEqual(result, [False])
        facts = blocked.lease_busy
        self.assertEqual((facts['holders'], facts['budget_used_bytes']), (1, 40 * MIB))
        self.assertGreaterEqual(facts['waited_ms'], 40)
        self.assertGreaterEqual(facts['owner_held_ms'], facts['waited_ms'])
        request_lease.release(first, 'request_end', self.log)
        self.assertEqual(facts['holders'], 1, 'failure snapshot followed live state')

    def test_drain_wakes_waiters_and_returns_the_drain_error(self):
        holder, blocked = self.handler(), self.handler()
        self.assertTrue(self.take(holder, 40 * MIB))
        result, done = self.waiting_request(blocked, 20 * MIB)
        with self.server.large_request_condition:
            self.server.draining = True
            self.server.large_request_condition.notify_all()
        self.assertTrue(done.wait(2))
        self.assertEqual(result, ['SERVER_DRAINING'])
        self.assertEqual(len(self.server.large_request_reservations), 1)

    def test_growth_exceeds_budget_without_waiting_and_never_shrinks_early(self):
        first, second = self.handler(), self.handler()
        self.assertTrue(self.take(first, 20 * MIB))
        self.assertTrue(self.take(second, 20 * MIB))
        with mock.patch.object(self.server.large_request_condition, 'wait',
                               side_effect=AssertionError('holder waited for itself')):
            self.assertTrue(self.take(first, 60 * MIB))
            self.assertTrue(self.take(first, 30 * MIB))
        self.assertEqual(self.server.large_request_bytes, 80 * MIB)
        request_lease.release(first, 'request_end', self.log)
        self.assertEqual(self.events[-1]['reserved_bytes'], 60 * MIB)
        self.assertEqual(self.server.large_request_bytes, 20 * MIB)

    def test_one_request_over_budget_runs_only_when_alone(self):
        first, second = self.handler(), self.handler()
        self.assertTrue(self.take(first, 50 * MIB))
        with mock.patch.object(request_lease, 'LARGE_REQUEST_WAIT_S', 0):
            self.assertFalse(self.take(second, 50 * MIB))
        request_lease.release(first, 'request_end', self.log)
        self.assertTrue(self.take(second, 50 * MIB))

    def test_unknown_request_and_double_release_preserve_other_reservations(self):
        first, second, unknown = self.handler(), self.handler(), self.handler()
        self.assertTrue(self.take(first, 20 * MIB))
        self.assertTrue(self.take(second, 20 * MIB))
        request_lease.release(unknown, 'request_end', self.log)
        request_lease.release(first, 'request_end', self.log)
        request_lease.release(first, 'request_end', self.log)
        self.assertEqual(self.server.large_request_bytes, 20 * MIB)
        self.assertEqual(list(self.server.large_request_reservations),
                         [second.lease_facts['request_id']])

    def test_small_prepared_body_does_not_reserve_even_when_budget_is_full(self):
        first, small = self.handler(), self.handler()
        self.assertTrue(self.take(first, 40 * MIB))
        prepared = transport.Prepared('test.example', '/responses', {}, b'{}', {}, 'openai')
        with mock.patch.object(self.server.large_request_condition, 'wait',
                               side_effect=AssertionError('small body waited')):
            request_lease.admit(small, prepared, None, 16 * MIB, self.log)
        self.assertEqual(self.server.large_request_bytes, 40 * MIB)
        self.assertEqual(len(self.server.large_request_reservations), 1)

    def test_downgrade_frees_bytes_and_wakes_waiters(self):
        first, blocked = self.handler(), self.handler()
        self.assertTrue(self.take(first, 40 * MIB))
        result, done = self.waiting_request(blocked, 20 * MIB)
        prepared = transport.Prepared('test.example', '/responses', {}, b'{}', {}, 'openai')
        request_lease.downgrade(first, prepared, 16 * MIB, self.log)
        self.assertTrue(done.wait(2))
        self.assertEqual(result, [True])
        release = next(e for e in self.events if e['event'] == 'oversize_slot_released')
        self.assertEqual(release['release_reason'], 'prepared_small')
        self.assertEqual((release['budget_used_bytes'], release['holders']), (0, 0))


if __name__ == '__main__':
    unittest.main()
