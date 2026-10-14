"""Large native requests can overlap without a local busy refusal."""
import threading
import unittest
from unittest import mock

from ai_router import request_lease
from tests.fakes import FakeUpstream, install_fake
from tests.harness import scaled_limits
from tests.test_request_admission import _turn, _wire
from tests.test_request_lease_downgrade import LeaseServerCase


class LargeRequestBudgetTests(LeaseServerCase):
    def test_two_twenty_mib_requests_reach_upstream_together(self):
        reached = [threading.Event(), threading.Event()]
        release = threading.Event()
        sends, send_lock = [], threading.Lock()
        self.addCleanup(release.set)

        def responder():
            with send_lock:
                index = len(sends)
                sends.append(index)

            class Held(FakeUpstream):
                def read(inner, amt=None):
                    reached[index].set()
                    if not release.wait(5):
                        raise TimeoutError('test did not release responses')
                    return super().read(amt)
            return Held(200, b'{}', [])

        recorded = install_fake(self, responder)
        body = _wire(_turn('native responses', 10 * 1024 * 1024))[0]
        self.assertGreater(len(body), 20 * 1024 * 1024)
        first, first_result, first_done = self.background('native responses', body)
        second = None
        try:
            self.assertTrue(reached[0].wait(3), 'first request did not reach upstream')
            second, second_result, _ = self.background('native responses', body)
            self.assertTrue(reached[1].wait(3), 'second request was refused or serialized')
            self.assertFalse(first_done.is_set())
            self.assertEqual(len(recorded), 2)
        finally:
            release.set()
            first.join(5)
            if second is not None:
                second.join(5)
        self.assertEqual(first_result, {'status': 200})
        self.assertEqual(second_result, {'status': 200})
        self.assert_released()

    def test_waiting_http_request_resumes_or_gets_drain_response(self):
        for draining in (False, True):
            with self.subTest(draining=draining):
                reached, release, waiting = (threading.Event() for _ in range(3))
                self.addCleanup(release.set)
                original_wait = self.server.large_request_condition.wait
                sends = []

                def wait(timeout):
                    waiting.set()
                    return original_wait(timeout)

                class Held(FakeUpstream):
                    def read(inner, amt=None):
                        reached.set()
                        if not release.wait(5):
                            raise TimeoutError('test did not release response')
                        return super().read(amt)

                def responder():
                    sends.append(True)
                    return (Held if len(sends) == 1 else FakeUpstream)(200, b'{}', [])

                install_fake(self, responder)
                body = _wire(_turn('native responses', 1400))[0]
                with scaled_limits(2000, 12000), mock.patch.object(
                        request_lease, 'LARGE_REQUEST_BUDGET_BYTES', 1), mock.patch.object(
                        self.server.large_request_condition, 'wait', wait):
                    first, first_result, _ = self.background('native responses', body)
                    self.assertTrue(reached.wait(2))
                    second, second_result, second_done = self.background('native responses', body)
                    self.assertTrue(waiting.wait(2))
                    self.assertFalse(second_done.is_set())
                    try:
                        if draining:
                            with self.server.large_request_condition:
                                self.server.draining = True
                                self.server.large_request_condition.notify_all()
                        else:
                            release.set()
                        self.assertTrue(second_done.wait(2))
                    finally:
                        release.set()
                        first.join(5)
                        second.join(5)
                self.assertEqual(first_result, {'status': 200})
                self.assertEqual(second_result, {'status': 503 if draining else 200})
                self.assertEqual(len(sends), 1 if draining else 2)
                self.assert_released()
                self.server.draining = False


if __name__ == '__main__':
    unittest.main()
