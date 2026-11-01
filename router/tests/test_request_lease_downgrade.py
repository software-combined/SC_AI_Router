"""Large ingress histories that become small may stream concurrently."""
import threading
import unittest
from unittest import mock

from ai_router import providers, request_lease
from tests.fakes import FakeUpstream, install_fake
from tests.harness import scaled_limits
from tests.test_request_admission import ServerCase, _turn, _wire
from tests.test_oversize_ingress import _repeated_search_payload

CAP, CEILING = 8000, 64000


class LeaseServerCase(ServerCase):
    def background(self, route, body, encoding=None):
        result, finished = {}, threading.Event()

        def run():
            try:
                response = self.send(route, body, encoding)
                result['status'] = response.status
                response.read()
            except Exception as exc:
                result['error'] = type(exc).__name__
            finally:
                finished.set()
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        return thread, result, finished


class RequestLeaseDowngradeTests(LeaseServerCase):
    def test_reduced_history_does_not_block_another_large_request(self):
        for encoding in (None, 'zstd'):
            with self.subTest(encoding=encoding):
                reached, release = threading.Event(), threading.Event()
                self.addCleanup(release.set)
                sends = []

                class Stalled(FakeUpstream):
                    def read(inner, amt=None):
                        reached.set()
                        if not release.wait(5):
                            raise TimeoutError('test did not release the first response')
                        return super().read(amt)

                def responder():
                    first = not sends
                    sends.append(True)
                    return (Stalled if first else FakeUpstream)(
                        200, b'{}', [('Content-Type', 'application/json')])

                recorded = install_fake(self, responder)
                raw, body = _wire(_repeated_search_payload(12, 1000), encoding)
                self.assertGreater(len(raw), CAP)

                with scaled_limits(CAP, CEILING):
                    thread, result, finished = self.background('external responses', body, encoding)
                    self.assertTrue(reached.wait(5), 'first request never reached upstream')
                    try:
                        self.assertLess(len(recorded[0][3]), CAP)
                        self.answer(self.send('external responses', body, encoding), 200)
                        self.assertFalse(finished.is_set(), 'first response ended too early')
                        self.assertEqual(len(recorded), 2)
                    finally:
                        release.set()
                        thread.join(5)
                    self.assertTrue(finished.is_set())
                    self.assertEqual(result, {'status': 200})
                self.assert_released()

    def test_preparation_keeps_the_slot_until_large_locals_leave_scope(self):
        reached, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        original = providers.ExternalResponsesProvider.prepare

        def prepare(*args, **kwargs):
            prepared = original(*args, **kwargs)
            reached.set()
            if not release.wait(5):
                raise TimeoutError('test did not finish preparation')
            return prepared

        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        body = _wire(_repeated_search_payload(12, 1000))[0]
        with scaled_limits(CAP, CEILING), mock.patch.object(
                providers.ExternalResponsesProvider, 'prepare', prepare), mock.patch.object(
                request_lease, 'LARGE_REQUEST_BUDGET_BYTES', 1), mock.patch.object(
                request_lease, 'LARGE_REQUEST_WAIT_S', 0):
            thread, result, _ = self.background('external responses', body)
            self.assertTrue(reached.wait(5))
            try:
                response = self.send('external responses', body)
                self.assertEqual(response.getheader('Retry-After'), '2')
                self.answer(response, 503, 'OVERSIZE_BUSY')
                self.assertEqual(recorded, [])
            finally:
                release.set()
                thread.join(5)
            self.assertEqual(result, {'status': 200})
        self.assert_released()

    def test_finishing_reduced_request_does_not_release_the_new_owner(self):
        reached = [threading.Event(), threading.Event()]
        release = [threading.Event(), threading.Event()]
        for event in release:
            self.addCleanup(event.set)
        sends = []

        def responder():
            index = len(sends)
            sends.append(index)

            class Stalled(FakeUpstream):
                def read(inner, amt=None):
                    reached[index].set()
                    if not release[index].wait(5):
                        raise TimeoutError('test did not release response')
                    return super().read(amt)
            return Stalled(200, b'{}', [('Content-Type', 'application/json')])

        install_fake(self, responder)
        reduced = _wire(_repeated_search_payload(12, 1000))[0]
        large = _wire(_turn('native responses', 5000))[0]
        with scaled_limits(CAP, CEILING), mock.patch.object(
                request_lease, 'LARGE_REQUEST_BUDGET_BYTES', 1), mock.patch.object(
                request_lease, 'LARGE_REQUEST_WAIT_S', 0):
            first, first_result, first_done = self.background('external responses', reduced)
            self.assertTrue(reached[0].wait(5))
            second, second_result, _ = self.background('native responses', large)
            self.assertTrue(reached[1].wait(5))
            try:
                release[0].set()
                self.assertTrue(first_done.wait(5))
                self.assertEqual(len(self.server.large_request_reservations), 1,
                                 'previous owner released the new reservation')
                self.answer(self.send('native responses', large), 503, 'OVERSIZE_BUSY')
            finally:
                release[1].set()
                first.join(5)
                second.join(5)
            self.assertEqual(first_result, {'status': 200})
            self.assertEqual(second_result, {'status': 200})
        self.assert_released()


if __name__ == '__main__':
    unittest.main()
