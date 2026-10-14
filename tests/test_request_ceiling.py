"""Large image histories and exact boundaries for the local request ceiling."""
import json
import unittest
from unittest import mock
from compression import zstd

from ai_router import errors, provider_defs, rejected_repair, transport, wire_shape
from ai_router import router as router_mod
from tests.fakes import FakeUpstream, install_fake
from tests.harness import scaled_limits
from tests.test_request_admission import ROUTES, ServerCase, _turn, _wire


THRESHOLD, CEILING = 256, 4096


def padded_turn(route, size):
    raw, _ = _wire(_turn(route, 10))
    return raw + b' ' * (size - len(raw))


class RequestCeilingTests(ServerCase):
    def test_image_history_over_the_old_96_mib_ceiling_passes_unchanged(self):
        # Two synthetic image blocks total 98 MiB before JSON overhead.
        raw, packed = _wire(_turn('native responses', 49 * 1024 * 1024), 'zstd')
        decoded_bytes = len(raw)
        del raw
        self.assertGreater(decoded_bytes, 96 * 1024 * 1024)
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        with mock.patch.object(router_mod, 'log_event') as logged:
            self.answer(self.send('native responses', packed, 'zstd'), 200)
            self.assert_released()
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0][3], packed)
        self.assertEqual(recorded[0][4]['Content-Encoding'], 'zstd')
        releases = [c.kwargs for c in logged.call_args_list
                    if c.args[0] == 'oversize_slot_released']
        self.assertEqual(len(releases), 1)
        self.assertEqual(releases[0]['reserved_bytes'], decoded_bytes)
        self.assertEqual(releases[0]['budget_used_bytes'], 0)

    def test_all_routes_accept_the_exact_wire_and_decoded_ceiling_only(self):
        recorded = install_fake(self, lambda: FakeUpstream(200, b'{}', []))
        for route in ROUTES:
            for encoding in (None, 'zstd'):
                for extra in (0, 1):
                    with self.subTest(route=route, encoding=encoding, extra=extra):
                        raw = padded_turn(route, CEILING + extra)
                        body = zstd.compress(raw) if encoding else raw
                        before = len(recorded)
                        with scaled_limits(THRESHOLD, CEILING):
                            response = self.send(route, body, encoding)
                            self.answer(response, 400 if extra else 200,
                                        'BODY_TOO_LARGE' if extra else None)
                        self.assertEqual(len(recorded), before + (not extra))
                        if not extra and route.startswith('native'):
                            self.assertEqual(recorded[-1][3], body)
                        self.assert_released()


class CeilingBoundaryTests(unittest.TestCase):
    def test_prepared_wire_and_decoded_sizes_are_checked_before_connect(self):
        for encoding in (None, 'zstd'):
            for extra in (0, 1):
                with self.subTest(encoding=encoding, extra=extra):
                    raw = b'{}' + b' ' * (CEILING + extra - 2)
                    body = zstd.compress(raw) if encoding else raw
                    headers = {'Content-Encoding': encoding} if encoding else {}
                    prepared = transport.Prepared(
                        'upstream.example', '/responses', headers, body, set(),
                        provider_defs.OPENAI.id, decoded_body_bytes=len(raw))
                    conn = mock.Mock()
                    with scaled_limits(THRESHOLD, CEILING):
                        if extra:
                            with self.assertRaises(errors.InvalidSize):
                                transport.post_with_phases(conn, prepared, {})
                            conn.connect.assert_not_called()
                            conn.request.assert_not_called()
                        else:
                            transport.post_with_phases(conn, prepared, {})
                            self.assertEqual(conn.request.call_args.kwargs['body'], body)

    def test_diagnostic_and_repair_decoders_share_the_boundary(self):
        for extra in (0, 1):
            with self.subTest(extra=extra):
                raw = padded_turn('native responses', CEILING + extra)
                body = zstd.compress(raw)
                prepared = transport.Prepared(
                    'upstream.example', '/responses', {'Content-Encoding': 'zstd'},
                    body, set(), provider_defs.OPENAI.id, decoded_body_bytes=len(raw))
                with mock.patch.object(wire_shape, 'DECODE_LIMIT', CEILING), \
                        mock.patch.object(rejected_repair, 'ZSTD_DECODE_LIMIT', CEILING):
                    facts = wire_shape.fingerprint(body)
                    proposal = rejected_repair.encrypted_content(
                        prepared, (None, None, 'invalid_encrypted_content'), b'{}')
                if extra:
                    self.assertEqual(facts, {})
                    self.assertIsNone(proposal.prepared)
                else:
                    self.assertEqual(facts['items'], 4)
                    repaired = json.loads(proposal.prepared.body)
                    self.assertEqual(len(repaired['input']), 3)


if __name__ == '__main__':
    unittest.main()
