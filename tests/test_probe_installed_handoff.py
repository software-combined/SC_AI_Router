"""Installed acceptance must use the daemon's final, complete send ledger."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tools import probe_desktop_handoff as desktop


class InstalledVerdictTests(unittest.TestCase):
    def record(self, rows):
        args = SimpleNamespace(record=None)

        def client_run(args, probe_type):
            probe = probe_type(False, desktop.MAX_CALLS, True)
            probe.installed = True
            probe.live_calls = probe.budget.calls = 8
            probe.child_agents = {('synthetic-child', '/root/matrix_child')}
            readable = {'namespace': 'canonical', 'marker': 'empty', 'message_shape': 'readable'}
            probe.facts.update(child_receipts=list(probe.markers),
                client_calls=[{'turn': 1, 'tool': 'spawn_agent', **readable}, {'turn': 2, 'tool': 'followup_task', **readable}])
            probe.facts['gates'] = probe.gates()  # Client verification precedes final daemon readback.
            return 0

        with patch.object(desktop.handoffs, 'run', client_run), \
                patch.object(desktop, 'installed_rows', return_value=rows), \
                patch.object(desktop, 'emit', side_effect=lambda record, path: record):
            return desktop.run_case(args, desktop.DesktopProbe, 'desktop', 'installed')

    def rows(self, sends=8):
        return [row for index in range(8) for row in (
            {'event': 'request_started', 'request_id': str(index)},
            {'event': 'attempt_ledger', 'request_id': str(index), 'sends': sends - 7 if index == 0 else 1})]

    def test_complete_bounded_daemon_evidence_passes(self):
        result = self.record(self.rows())
        self.assertEqual((result['outcome'], result['upstream_sends']), ('passed', 8))

    def test_refusal_in_final_readback_cannot_use_cached_success(self):
        result = self.record(self.rows() + [{'event': 'upstream_rejected', 'code': 'UPSTREAM_INVALID_REQUEST'}])
        self.assertEqual(result['outcome'], 'refused')
        self.assertFalse(result['gates']['no_refusals'])

    def test_actual_sends_above_cap_cannot_pass(self):
        result = self.record(self.rows(13))
        self.assertNotEqual(result['outcome'], 'passed')
        self.assertFalse(result['gates']['within_attempt_cap'])

    def test_missing_or_zero_send_ledger_cannot_pass(self):
        for rows in (self.rows()[:-1], self.rows(7)):
            with self.subTest(rows=rows):
                result = self.record(rows)
                self.assertNotEqual(result['outcome'], 'passed')
                self.assertFalse(result['gates']['complete_send_ledger'])

    def test_unused_reserved_sends_return_only_after_complete_readback(self):
        probe = desktop.DesktopProbe(False, desktop.MAX_CALLS, True)
        probe.installed, probe.budget = True, desktop.CaseBudget(None)
        rows = [{'event': 'request_started', 'request_id': 'synthetic'},
                {'event': 'attempt_ledger', 'request_id': 'synthetic', 'sends': 1}]
        with patch.object(desktop.handoffs.Probe, 'forward', return_value=b'ok'), \
                patch.object(desktop, 'installed_rows', return_value=rows):
            self.assertEqual(probe.forward({'model': desktop.PARENT}, {}, role='parent'), b'ok')
        self.assertEqual(probe.budget.calls, 1)
        with patch.object(desktop.handoffs.Probe, 'forward', return_value=b'ok'), \
                patch.object(desktop, 'installed_rows', return_value=[]):
            with self.assertRaisesRegex(ValueError, 'ledger incomplete'):
                probe.forward({'model': desktop.PARENT}, {}, role='parent')
        self.assertEqual(probe.budget.calls, 3)  # The incomplete request retains its two-send reservation.


if __name__ == '__main__':
    unittest.main()
