"""Policy scans with one owner (Plan 134).

Implements the two greps that used to be inline shell in
`.github/workflows/check.yml`, so they run identically locally
(`python3.14 tools/check_policy_scans.py`) and in CI:

- request-cap scan: the cap was removed by owner decision
  (`docs/operations.md`); any reintroduction fails.
- secrets scan: OpenRouter keys and bearer tokens must never be committed.

Both scans read files as bytes, matching historical `grep -r` behaviour
on text and binary files alike. This script necessarily names the
request-cap pattern, so it excludes its own path from that scan.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUEST_CAP_RE = re.compile(rb'request_cap|DEFAULT_REQUEST_CAP')
SECRET_RE = re.compile(rb'sk-or-v1-[A-Za-z0-9]{20,}|Bearer [A-Za-z0-9._-]{30,}')
# Historical `grep -r` matched any file, text or binary; nothing here may be
# narrower than the CI gate it replaced, or a committed key can hide in a
# file the scan never opened.
SCAN_ALL = ('.',)
# A same-repo local action cannot run before checkout, so the composite owns
# the pin and every workflow must reach setup through it (Plan 134).
SETUP_PIN_RE = re.compile(rb'actions/setup-python@[0-9a-f]{40}')
# A real step, not a comment or a substring elsewhere: either the inline
# `- uses:` form (optionally with a trailing comment) or a two-line step
# whose `uses:` line sits at step indent.
SETUP_STEP_RE = re.compile(
    rb'(?m)^\s*(?:-[ \t]+)?uses: \./\.github/actions/setup'
    rb'(?:[ \t]*#.*)?[ \t]*$')
WORKFLOWS = ('check.yml', 'release.yml', 'refresh.yml')

SELF = Path(__file__).resolve()


def _is_derived_bytecode(path):
    """True for a __pycache__ .pyc whose source file is present."""
    if path.suffix != '.pyc' or path.parent.name != '__pycache__':
        return False
    source = path.parent.parent / (path.name.split('.')[0] + '.py')
    return source.exists()


def _iter_files(dirs):
    for dirname in dirs:
        base = ROOT / dirname
        if not base.exists():
            raise SystemExit(f'policy-scans: scanned path is missing: {dirname}')
        for path in sorted(base.rglob('*')):
            # Derived bytecode is not source (see `_is_derived_bytecode`); a
            # `.pyc` with no corresponding source is scanned.
            if _is_derived_bytecode(path):
                continue
            # Git metadata is not repository content: a commit subject can
            # carry any word, and reading the object store is wasted work.
            if '.git' in path.parts:
                continue
            if path.is_file() and not path.is_symlink():
                yield path


def check_request_cap():
    hits = [str(p.relative_to(ROOT)) for p in _iter_files(SCAN_ALL)
        if p.resolve() != SELF and REQUEST_CAP_RE.search(p.read_bytes())]
    if hits:
        print('request cap removed by decision (docs/operations.md); '
              'do not reintroduce')
        for hit in hits:
            print(f'  {hit}')
        return False
    return True


def check_secrets():
    hits = [str(p.relative_to(ROOT)) for p in _iter_files(SCAN_ALL)
            if SECRET_RE.search(p.read_bytes())]
    if hits:
        print('possible secret committed')
        for hit in hits:
            print(f'  {hit}')
        return False
    return True


def check_setup_single_owner():
    """The composite owns the setup-python pin; workflows use it."""
    action = ROOT / '.github' / 'actions' / 'setup' / 'action.yml'
    if not action.exists():
        print(f'{action.relative_to(ROOT)} is missing: no owner for the setup pin')
        return False
    pins = SETUP_PIN_RE.findall(action.read_bytes())
    ok = True
    if len(set(pins)) != 1:
        print(f'{action.relative_to(ROOT)} must pin setup-python exactly once')
        ok = False
    workflows = sorted(set((ROOT / '.github' / 'workflows').glob('*.yml'))
                       | set((ROOT / '.github' / 'workflows').glob('*.yaml')))
    for workflow in workflows:
        name = workflow.name
        text = workflow.read_bytes()
        # Any workflow, present or future, must not carry its own pin.
        if b'actions/setup-python' in text:
            print(f'.github/workflows/{name} must use ./.github/actions/setup, '
                  'not its own setup-python pin')
            ok = False
    for name in WORKFLOWS:
        path = ROOT / '.github' / 'workflows' / name
        if not path.exists():
            print(f'.github/workflows/{name} is missing')
            ok = False
            continue
        if not SETUP_STEP_RE.search(path.read_bytes()):
            print(f'.github/workflows/{name} is missing the shared setup step')
            ok = False
    return ok


def main():
    # Every scan runs (no short-circuit) so one run reports all failures.
    results = (check_request_cap(), check_secrets(), check_setup_single_owner())
    ok = all(results)
    print(f'policy-scans: {"pass" if ok else "FAIL"}')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
