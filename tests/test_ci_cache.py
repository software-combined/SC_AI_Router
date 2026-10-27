"""The CI dependency cache stays wired to the job that downloads wheels."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CiCacheTests(unittest.TestCase):
    def test_setup_action_exposes_a_passthrough_cache(self):
        action = _text('.github/actions/setup/action.yml')
        self.assertIn('  cache:\n', action)
        self.assertIn('  cache-dependency-path:\n', action)
        self.assertIn('cache: ${{ inputs.cache }}', action)
        self.assertIn(
            'cache-dependency-path: ${{ inputs.cache-dependency-path }}', action)

    def test_the_wheel_installing_job_keys_the_cache_on_its_pins(self):
        check = _text('.github/workflows/check.yml')
        blocks = [step.split('      - name:', 1)[0] for step
                  in check.split('      - uses: ./.github/actions/setup\n')[1:]]
        cached = [block for block in blocks
                  if 'cache: pip' in block
                  and 'cache-dependency-path: |' in block
                  and '.github/requirements-lint.txt' in block
                  and '.github/workflows/check.yml' in block]
        self.assertEqual(len(cached), 1)


def _text(relative):
    """Workflow text with LF endings, so a Windows checkout parses the same."""
    return (ROOT / relative).read_text().replace('\r\n', '\n')


if __name__ == '__main__':
    unittest.main()
