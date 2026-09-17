"""Every `Plan NNN` reference in source resolves (Plan 157).

A number resolves through a live plan file, a parked file, an archived file,
the renumbering map or the removal log in `plans/README.md`. `plans/` is
gitignored, so the walk skips on a checkout without it; the non-vacuity
checks below keep that skip from hiding a broken resolver.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLANS = ROOT / 'plans'
README = PLANS / 'README.md'
DIRS = ('ai_router', 'packaging', 'tools', 'tests')
REFERENCE = re.compile(r'[Pp]lan (\d{3})')


def readme_text():
    return README.read_text()


def renumbered_numbers(text):
    """Numbers the renumbering map resolves: `084->098, 046->099, ...`."""
    return {old for old, _new in re.findall(r'(\d{3})\u2192(\d{3})', text)}


def logged_numbers(text):
    """Numbers the removal log records, in its own section only."""
    section = text[text.index('## Completed and removed'):].split('\n## ', 1)[0]
    return set(re.findall(r'\b(\d{3})\b', section))


def resolves(number, text):
    for field in ('', 'parked', 'archived'):
        if list((PLANS / field).glob(f'{number}-*.md')):
            return True
    return number in renumbered_numbers(text) or number in logged_numbers(text)


def source_lines():
    for name in DIRS:
        for path in sorted((ROOT / name).rglob('*.py')):
            for line_no, line in enumerate(path.read_text().splitlines(), 1):
                yield f'{path.relative_to(ROOT)}:{line_no}', line


@unittest.skipUnless(README.exists(), 'plans/ is gitignored and not present')
class PlanReferenceTests(unittest.TestCase):
    def test_every_reference_resolves(self):
        text = readme_text()
        unresolved = []
        references = 0
        for where, line in source_lines():
            for number in REFERENCE.findall(line):
                references += 1
                if not resolves(number, text):
                    unresolved.append(f'{where}: Plan {number}')
        # Proven non-vacuous: the walk must actually find the source's own
        # references, or an empty sweep would pass as a clean tree.
        self.assertGreater(references, 100)
        self.assertEqual(unresolved, [])

    def test_resolver_is_not_vacuous(self):
        text = readme_text()
        # A fabricated number resolves to nothing; each real resolution
        # channel answers for a number it owns.
        self.assertFalse(resolves('999', text))
        self.assertTrue(resolves('166', text), 'a live plan file')
        self.assertTrue(resolves('039', text), 'a parked plan file')
        self.assertTrue(resolves('059', text), 'the renumbering map')
        self.assertTrue(resolves('090', text), 'the removal log')


if __name__ == '__main__':
    unittest.main()
