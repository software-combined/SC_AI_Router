"""Plan 188: a large turn holds the single large-request slot to its last send.

Before, the slot covered reading and preparing only and was released before
relay, which assumed every prepared body was under the ordinary threshold.
Now the turn keeps it through the stream, a rejected-request repair and the
helper fallback (each sized with the original still held), and every exit
releases it once. Small turns and the in-flight ceiling are untouched.
"""
import http.client
import json
import threading
import unittest

from tests.fakes import FakeUpstream, install_fake
from tests.harness import scaled_limits
from tests.test_request_admission import (CAP, CEILING, CONTEXT_RESET, SIGNATURE,
                                          ServerCase, _turn, _wire)

ENCRYPTED = json.dumps({'error': {'message': 'the request was rejected',
                                  'code': 'invalid_encrypted_content'}}).encode()
HELPER = {'x-codex-turn-metadata': json.dumps({'thread_source': 'thread_title'})}


def _upstream(*responses, stalled=None):
    """One (status, body) per send, the last repeating; send `stalled` waits."""
    reached, release, sends = threading.Event(), threading.Event(), []

    class Stalled(FakeUpstream):
        def read(self, amt=None):
            reached.set()
            release.wait(5)
            return super().read(amt)

    def responder():
        index = len(sends)
        sends.append(index)
        status, body = responses[min(index, len(responses) - 1)]
        return (Stalled if index == stalled else FakeUpstream)(
            status, body, [('Content-Type', 'application/json')])
    return responder, reached, release


class RequestLeaseTests(ServerCase):
    def background(self, route, body, extra=None):
        result = {}

        def run():
            result['status'] = self.send(route, body, extra=extra).status
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        return thread, result

    def assert_held(self):
        held = not self.lock.acquire(blocking=False)
        if not held:
            self.lock.release()
        self.assertTrue(held, 'the large-request slot was released early')

    def test_preparation_growth_past_the_threshold_takes_the_slot(self):
        payload = _turn('native responses', 10, text='é' * 600)
        payload['input'].append(CONTEXT_RESET)
        raw, _ = _wire(payload)
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        with scaled_limits(CAP, CEILING):
            self.assertLess(len(raw), CAP)
            self.assertTrue(self.lock.acquire(blocking=False))
            try:
                response = self.send('native responses', raw)
                self.assertEqual(response.getheader('Retry-After'), '2')
                self.answer(response, 503, 'OVERSIZE_BUSY')
                self.assertEqual(recorded, [])
            finally:
                self.lock.release()
            self.answer(self.send('native responses', raw), 200)
        self.assertGreater(len(recorded[0][3]), CAP)
        self.assert_released()

    def test_the_lease_is_held_through_relay_repair_and_fallback(self):
        large = _turn('native responses', 1400)
        helper = dict(large, model='gpt-5.6-luna')
        cases = (('relay', large, None, [(200, b'{}')], 0),
                 ('repair', large, None, [(400, ENCRYPTED), (200, b'{}')], 1),
                 ('fallback', helper, HELPER, [(429, b'{}'), (200, b'{"output": []}')], 1))
        for name, payload, extra, responses, stalled in cases:
            with self.subTest(name=name):
                responder, reached, release = _upstream(*responses, stalled=stalled)
                self.addCleanup(release.set)
                recorded = install_fake(self, responder)
                with scaled_limits(CAP, CEILING):
                    thread, result = self.background('native responses', _wire(payload)[0],
                                                     extra)
                    self.assertTrue(reached.wait(5), 'the stalled send never started')
                    self.assert_held()
                    if name == 'relay':
                        # Small turns still run; another large one is told to retry.
                        small = _turn('external responses', 10)
                        self.answer(self.send('external responses', _wire(small)[0]), 200)
                        response = self.send('native responses', _wire(large)[0])
                        self.assertEqual(response.getheader('Retry-After'), '2')
                        self.answer(response, 503, 'OVERSIZE_BUSY')
                    release.set()
                    thread.join(5)
                self.assertEqual(result.get('status'), 200)
                self.assertEqual(len(recorded), 2)
                if name == 'repair':
                    self.assertNotIn(SIGNATURE.encode(), recorded[1][3])
                self.assert_released()

    def test_a_repair_or_fallback_that_needs_the_busy_slot_is_not_sent(self):
        # Under the threshold alone, past it with the original still held.
        turn = _turn('native responses', 600)
        cases = (('repair', turn, None, [(400, ENCRYPTED)], 'OVERSIZE_BUSY'),
                 ('fallback', dict(turn, model='gpt-5.6-luna'), HELPER, [(429, b'{}')],
                  'UPSTREAM_RATE_LIMITED'))
        for name, payload, extra, responses, code in cases:
            with self.subTest(name=name):
                raw = _wire(payload)[0]
                recorded = install_fake(self, _upstream(*responses)[0])
                with scaled_limits(CAP, CEILING):
                    self.assertLess(len(raw), CAP)
                    # The repaired or twin body is well over half the original.
                    self.assertLess(CAP, len(raw) * 3 // 2)
                    self.assertTrue(self.lock.acquire(blocking=False))
                    try:
                        response = self.send('native responses', raw, extra=extra)
                        self.answer(response, 503, code)
                    finally:
                        self.lock.release()
                self.assertEqual([record[0] for record in recorded], ['chatgpt.com'])

    def test_failures_and_disconnects_release_the_slot_and_the_inflight_count(self):
        raw = _wire(_turn('native responses', 1400))[0]

        def unreachable():
            raise ConnectionRefusedError('synthetic upstream down')
        install_fake(self, unreachable)
        with scaled_limits(CAP, CEILING):
            self.answer(self.send('native responses', raw), 502)
            self.assert_released()
            responder, reached, release = _upstream((200, b'{}'), stalled=0)
            self.addCleanup(release.set)
            install_fake(self, responder)
            conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
            conn.request('POST', '/test-token/responses', body=raw,
                         headers={'Content-Type': 'application/json'})
            self.assertTrue(reached.wait(5))
            conn.close()  # the client leaves while the upstream answer is stalled
            release.set()
            self.assert_released()
        for _ in range(50):
            with self.server.lock:
                if self.server.inflight == 0:
                    break
            threading.Event().wait(0.1)
        self.assertEqual(self.server.inflight, 0)



if __name__ == '__main__':
    unittest.main()
