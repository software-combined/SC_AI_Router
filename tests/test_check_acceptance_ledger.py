"""Offline checks for the acceptance-ledger staleness gate (Plan 185 step 4)."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from tools import check_acceptance_ledger as checker

# The checker reads backticked names only, so the unbackticked mention of a
# later Claude Code release must not become the newest client.
PAGE = ('Codex desktop `26.917.62051` with bundled `codex-cli 0.155.0-alpha.16.3`; '
        'Claude Code `2.1.223`.\nEarlier: Codex desktop `26.915.31945`. An app '
        'bundling Claude Code 2.1.247 or later sends the shape itself.\n')


def run_of(cell, result='pass', codex='26.917.62051', claude='2.1.223',
           date='2026-09-24 12:58 AEST'):
    return {'cell': cell, 'date_aest': date, 'router_version': '0.6.122.118',
            'codex_version': codex, 'claude_code_version': claude,
            'rows': ['deepseek/deepseek-v4.1-flash', 'gpt-6-luna'],
            'requested_effort': 'low', 'served': ['deepseek/deepseek-v4.1-flash', None],
            'calls': 4, 'result': result, 'notes': ''}


def check(runs, page=PAGE):
    """(exit code, stdout, stderr) for one ledger and compatibility page."""
    with tempfile.TemporaryDirectory() as tmp:
        ledger, compat = Path(tmp) / 'ledger.json', Path(tmp) / 'compatibility.md'
        ledger.write_text(runs if isinstance(runs, str) else json.dumps(runs))
        compat.write_text(page)
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            code = checker.main(['--ledger', str(ledger), '--compatibility', str(compat)])
    return code, out.getvalue(), err.getvalue()


class StalenessTests(unittest.TestCase):
    def test_current_p1_cells_pass_and_a_missing_c5_is_reported_only(self):
        code, out, _ = check([run_of(cell) for cell in ('C1', 'C2', 'C3', 'C4')])
        self.assertEqual(code, 0)
        self.assertIn('newest named clients: Codex desktop 26.917.62051, Claude Code 2.1.223', out)
        self.assertIn('C4 current: latest pass 2026-09-24 12:58 AEST', out)
        self.assertIn('C5 missing: no pass recorded (P2, reported only)', out)
        self.assertIn('every P1 cell is current', out)

    def test_a_missing_p1_cell_fails(self):
        code, out, _ = check([run_of(cell) for cell in ('C1', 'C2', 'C4')])
        self.assertEqual(code, 1)
        self.assertIn('C3 missing: no pass recorded', out)
        self.assertIn('stale or missing P1 cells: C3', out)

    def test_a_pass_on_an_older_client_is_stale(self):
        for older in ({'codex': '26.915.31945'}, {'claude': '2.1.200'}):
            with self.subTest(older=older):
                code, out, _ = check([run_of('C1'), run_of('C2', **older),
                                      run_of('C3'), run_of('C4')])
                self.assertEqual(code, 1)
                self.assertIn('C2 stale: latest pass', out)
                self.assertIn('stale or missing P1 cells: C2', out)

    def test_a_newer_client_named_across_a_line_wrap_still_counts(self):
        code, out, _ = check([run_of(cell) for cell in ('C1', 'C2', 'C3', 'C4')],
                             PAGE + 'Updated to Claude\nCode\n`2.1.230`.\n')
        self.assertEqual(code, 1)
        self.assertIn('Claude Code 2.1.230', out)
        self.assertIn('C1 stale', out)

    def test_versions_compare_numerically_not_as_text(self):
        # As text '26.1000.1' sorts before '26.917.62051'; numerically it is newer.
        page = PAGE + 'Then Codex desktop `26.1000.1`.\n'
        code, out, _ = check([run_of(cell, codex='26.1000.1') for cell in ('C1', 'C2', 'C3', 'C4')], page)
        self.assertEqual(code, 0, out)
        code, out, _ = check([run_of(cell) for cell in ('C1', 'C2', 'C3', 'C4')], page)
        self.assertEqual(code, 1)
        self.assertIn('C1 stale', out)

    def test_the_latest_pass_decides_and_a_later_failure_does_not_count(self):
        old = dict(codex='26.915.31945', date='2026-09-20 09:00 AEST')
        runs = [run_of('C1', **old), run_of('C1'), run_of('C2'), run_of('C3'),
                run_of('C4', **old), run_of('C4', result='fail', date='2026-09-25 09:00 AEST')]
        code, out, _ = check(runs)
        self.assertIn('C1 current', out)
        self.assertIn('C4 stale: latest pass 2026-09-20 09:00 AEST', out)
        self.assertEqual(code, 1)


class MalformedInputTests(unittest.TestCase):
    def assert_rejected(self, runs, page=PAGE):
        code, out, err = check(runs, page)
        self.assertEqual(code, 1)
        self.assertEqual(out, '')
        self.assertIn('acceptance-ledger: unreadable or malformed input', err)

    def test_malformed_ledgers_fail_closed(self):
        extra = dict(run_of('C1'), operator='x')
        missing = {k: v for k, v in run_of('C1').items() if k != 'notes'}
        for runs in ('not json', '{"cell": "C1"}', [missing], [extra],
                     [run_of('C6')], [run_of('C1', date='24 Sep 2026')],
                     [run_of('C1', codex='26.917.62051 (build 10789)')],
                     [run_of('C1', claude=None)], [dict(run_of('C1'), calls='4')]):
            with self.subTest(runs=runs):
                self.assert_rejected(runs)

    def test_a_page_naming_no_backticked_client_version_fails_closed(self):
        self.assert_rejected([run_of('C1')], page='Codex desktop `26.917.62051` only.\n')


class RepositoryLedgerTests(unittest.TestCase):
    def test_the_repository_ledger_is_well_formed_and_c1_passed(self):
        root = Path(__file__).resolve().parents[1]
        entries = checker.load((root / 'docs' / 'acceptance-ledger.json').read_text())
        clients = checker.newest((root / 'docs' / 'compatibility.md').read_text())
        self.assertTrue(any(e['cell'] == 'C1' and e['result'] == 'pass' for e in entries))
        self.assertEqual(set(clients), set(checker.CLIENTS))


if __name__ == '__main__':
    unittest.main()
