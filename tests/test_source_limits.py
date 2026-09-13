"""The limits baseline is exact: stale, wrong and new overruns all fail.

Plan 156 item 4: the old check read the baseline only for files above the
soft cap, so a shrunken file or an edited count drifted silently. The tool
now also rejects nonexistent files, incorrect counts and exemptions that are
no longer needed.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'tools' / 'check_source_limits.py'
OVER = 251  # ai_router soft cap (250) + 1


def build(root, files, baseline):
    for rel, lines in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('x = 1\n' * lines)
    config = root / 'config'
    config.mkdir(parents=True, exist_ok=True)
    (config / 'source-limits-baseline.json').write_text(json.dumps(baseline))


def run_tool(root):
    return subprocess.run([sys.executable, str(TOOL), '--root', str(root)],
                          capture_output=True, text=True)


class SourceLimitsBaselineTests(unittest.TestCase):
    def fixture(self, files, baseline):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        build(root, files, baseline)
        return run_tool(root)

    def test_exact_exemption_passes(self):
        result = self.fixture({'ai_router/x.py': OVER}, {'ai_router/x.py': OVER})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('failures=0', result.stdout)

    def test_a_new_overrun_fails(self):
        result = self.fixture({'ai_router/x.py': OVER}, {})
        self.assertEqual(result.returncode, 1)
        self.assertIn('not in baseline', result.stdout)

    def test_a_baseline_for_a_missing_file_fails(self):
        result = self.fixture({'ai_router/x.py': 10}, {'ai_router/gone.py': 300})
        self.assertEqual(result.returncode, 1)
        self.assertIn('BASELINE ai_router/gone.py: no such file', result.stdout)

    def test_a_wrong_baseline_count_fails(self):
        result = self.fixture({'ai_router/x.py': OVER}, {'ai_router/x.py': OVER + 9})
        self.assertEqual(result.returncode, 1)
        self.assertIn('baseline says %d' % (OVER + 9), result.stdout)

    def test_a_baseline_below_the_soft_cap_fails(self):
        result = self.fixture({'ai_router/x.py': 10}, {'ai_router/x.py': 10})
        self.assertEqual(result.returncode, 1)
        self.assertIn('no longer over the soft cap', result.stdout)

    def test_an_unknown_baseline_area_fails(self):
        result = self.fixture({'config/x.py': 10}, {'config/x.py': 999})
        self.assertEqual(result.returncode, 1)
        self.assertIn('unknown area', result.stdout)

    def test_the_hard_cap_fails_even_with_an_exact_baseline(self):
        result = self.fixture({'ai_router/x.py': 401}, {'ai_router/x.py': 401})
        self.assertEqual(result.returncode, 1)
        self.assertIn('HARD ai_router/x.py: 401 lines', result.stdout)


if __name__ == '__main__':
    unittest.main()
