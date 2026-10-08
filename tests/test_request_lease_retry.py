"""Real HTTP retry admission and content-free lease lifecycle evidence."""
import http.client
import json
import threading
import unittest
from unittest import mock

from ai_router import providers, router
from tests.fakes import FakeUpstream, install_fake
from tests.harness import scaled_limits
from tests.test_oversize_ingress import _repeated_search_payload
from tests.test_request_admission import _turn, _wire
from tests.test_request_lease_downgrade import CAP, CEILING, LeaseServerCase
from tests.test_strip_retry import UNNAMED


class RequestLeaseRetryTests(LeaseServerCase):
    def reduced(self):
        payload = _repeated_search_payload(12, 1000)
        payload['store'] = False  # The real rejected-request repair strips this.
        return _wire(payload)[0]

    def test_repair_after_downgrade_reacquires_or_refuses_before_send(self):
        for busy in (False, True):
            with self.subTest(busy=busy):
                rejected, repair = threading.Event(), threading.Event()
                resume, release = threading.Event(), threading.Event()
                self.addCleanup(resume.set)
                self.addCleanup(release.set)
                sends, events = [], []

                class Rejected(FakeUpstream):
                    def read(inner, amt=None):
                        rejected.set()
                        if not resume.wait(5):
                            raise TimeoutError('rejection not released')
                        return super().read(amt)

                class Held(FakeUpstream):
                    def read(inner, amt=None):
                        repair.set()
                        if not release.wait(5):
                            raise TimeoutError('response not released')
                        return super().read(amt)

                def responder():
                    sends.append(True)
                    return (Rejected(400, UNNAMED, []) if len(sends) == 1
                            else Held(200, b'{}', []))

                recorded = install_fake(self, responder)
                with scaled_limits(CAP, CEILING), mock.patch.object(
                        router, 'log_event', lambda event, **fields:
                        events.append(dict(event=event, **fields))):
                    first, result, done = self.background('external responses', self.reduced())
                    self.assertTrue(rejected.wait(5))
                    self.assertFalse(self.lock.locked(), 'ingress lease did not downgrade')
                    if busy:
                        second, second_result, _ = self.background(
                            'native responses', _wire(_turn('native responses', 5000))[0])
                        self.assertTrue(repair.wait(5))
                        repair.clear()
                    resume.set()
                    try:
                        if busy:
                            self.assertTrue(done.wait(5))
                            self.assertEqual(result, {'status': 503})
                            self.assertEqual(len(recorded), 2)  # Original A and owning B only.
                            refusal = next(e for e in events if e.get('code') == 'OVERSIZE_BUSY')
                            self.assertEqual(refusal['stage'], 'retry')
                            self.assertGreater(refusal['retained_accounted_bytes'], CAP)
                            self.assertEqual(refusal['owner_stage'], 'wire')
                        else:
                            self.assertTrue(repair.wait(5))
                            self.assertTrue(self.lock.locked())
                            self.assertLess(len(recorded[0][3]), CAP)
                            self.assertLess(len(recorded[1][3]), CAP)
                            self.assertGreater(sum(len(r[3]) for r in recorded), CAP)
                            self.assertEqual(self.server.oversize_owner['stage'], 'retry')
                    finally:
                        release.set()
                        first.join(5)
                        if busy:
                            second.join(5)
                            self.assertEqual(second_result, {'status': 200})
                    if not busy:
                        self.assertEqual(result, {'status': 200})
                self.assert_released()

    def test_failures_and_disconnect_have_balanced_correlated_diagnostics(self):
        original_post = router.Handler.do_POST
        original_prepare = providers.ExternalResponsesProvider.prepare
        thread_id = '11111111-1111-4111-8111-111111111111'
        for failure in ('prepare', 'upstream', 'retry', 'disconnect'):
            with self.subTest(failure=failure):
                events, sends = [], []
                done, reached, release = (threading.Event() for _ in range(3))
                self.addCleanup(release.set)

                def completed(handler):
                    try:
                        return original_post(handler)
                    finally:
                        done.set()  # After the real final in-flight decrement.

                def prepare(*args, **kwargs):
                    if failure == 'prepare':
                        raise ValueError('synthetic preparation failure')
                    return original_prepare(*args, **kwargs)

                class Response(FakeUpstream):
                    def read(inner, amt=None):
                        if failure == 'upstream':
                            raise ConnectionResetError('synthetic upstream failure')
                        if failure == 'disconnect':
                            reached.set()
                            if not release.wait(5):
                                raise TimeoutError('disconnect response not released')
                        return super().read(amt)

                def responder():
                    sends.append(True)
                    if failure == 'retry':
                        if len(sends) == 2:
                            raise ConnectionRefusedError('synthetic repair failure')
                        return Response(400, UNNAMED, [])
                    return Response(200, b'{}', [])

                install_fake(self, responder)
                with scaled_limits(CAP, CEILING), mock.patch.object(
                        router.Handler, 'do_POST', completed), mock.patch.object(
                        providers.ExternalResponsesProvider, 'prepare', prepare), mock.patch.object(
                        router, 'log_event', lambda event, **fields:
                        events.append(dict(event=event, **fields))):
                    body = self.reduced()
                    if failure == 'disconnect':
                        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
                        self.addCleanup(conn.close)
                        conn.request('POST', '/test-token/responses', body=body,
                                     headers={'Content-Type': 'application/json', 'thread-id': thread_id})
                        self.assertTrue(reached.wait(5))
                        conn.close()
                        release.set()
                    else:
                        response = self.send('external responses', body, extra={'thread-id': thread_id})
                        response.read()
                    self.assertTrue(done.wait(5))
                self.assertEqual(self.server.inflight, 0)
                self.assert_released()
                acquired = [e for e in events if e['event'] == 'oversize_slot_acquired']
                released = [e for e in events if e['event'] == 'oversize_slot_released']
                self.assertEqual(len(acquired), 2 if failure == 'retry' else 1)
                self.assertEqual(len(released), len(acquired))
                request_id = acquired[0]['request_id']
                for event in acquired + released:
                    self.assertEqual(event['request_id'], request_id)
                    self.assertEqual(event['thread_id'], thread_id)
                    self.assertEqual(event['router_version'], router.VERSION)
                correlated = [e for e in events if e['event'] in ('request_started', 'attempt_ledger')]
                self.assertEqual(len(correlated), 0 if failure == 'prepare' else 2)
                self.assertTrue(all(e['request_id'] == request_id for e in correlated))
                refusals = [e for e in events if e['event'] == 'request_rejected']
                self.assertTrue(all(e['request_id'] == request_id for e in refusals))
                self.assertNotIn('subscription-secret', json.dumps(events))
                self.assertNotIn('test-key', json.dumps(events))
                self.assertNotIn('test-token', json.dumps(events))


if __name__ == '__main__':
    unittest.main()
