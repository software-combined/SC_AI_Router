"""Select plugin contracts only for proven documentation/version-only changes."""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
TEST_PATTERNS = (
    'test_plugin*.py', 'test_agent_skills*.py', 'test_prototypes*.py',
    'test_review_export.py', 'test_security_review.py', 'test_packaging.py',
    'test_router_worker_no_result.py', 'test_windows_agent_skills.py',
)
FULL_TESTS = ['discover', '-s', 'tests', '-t', '.']


def git(root, *args):
    return subprocess.check_output(['git', '--no-pager', *args], cwd=root,
                                   stderr=subprocess.DEVNULL)


def transitions(root, base):
    """Keep each state: opposing staged and unstaged edits must not cancel."""
    changes = []
    for args in ((base, 'HEAD'), ('--cached', 'HEAD'), ()):
        fields = git(root, 'diff', '--raw', '-z', '--no-abbrev', '--no-renames',
                     '--no-ext-diff', '--no-textconv', *args).split(b'\0')
        for index in range(0, len(fields) - 1, 2):
            old_mode, new_mode, old_blob, new_blob, status = fields[index][1:].decode().split()
            changes.append((os.fsdecode(fields[index + 1]), old_mode, new_mode,
                            old_blob, new_blob, status))
    for path in git(root, 'ls-files', '--others', '--exclude-standard', '-z').split(b'\0'):
        if not path:
            continue
        name = os.fsdecode(path)
        mode = (root / name).lstat().st_mode
        regular = stat.S_ISREG(mode) and not mode & 0o111
        changes.append((name, '000000', '100644' if regular else 'unknown', '', '', 'A'))
    return changes


def registered_plugins(root, base):
    registry = json.loads(git(root, 'show', f'{base}:.agents/plugins/marketplace.json'))
    names = set()
    for entry in registry['plugins']:
        name = entry['name']
        if entry['source']['path'] != './plugins/' + name or '/' in name or name in ('.', '..'):
            raise ValueError('unknown marketplace ownership')
        names.add(name)
    if not names:
        raise ValueError('empty marketplace')
    return names


def documentation(parts):
    if parts[:1] == ('references',):
        return len(parts) >= 2 and parts[-1].endswith('.md')
    return (len(parts) >= 3 and parts[0] == 'skills'
            and (parts[2:] == ('SKILL.md',)
                 or (len(parts) >= 4 and parts[2] == 'references'
                     and parts[-1].endswith('.md'))))


def version_only(root, change):
    def unique_fields(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('ambiguous manifest fields')
            value[key] = item
        return value

    name, _old_mode, _new_mode, old_blob, new_blob, _status = change
    before = json.loads(git(root, 'cat-file', 'blob', old_blob), object_pairs_hook=unique_fields)
    after = json.loads(git(root, 'cat-file', 'blob', new_blob)
                       if new_blob.strip('0') else (root / name).read_bytes(),
                       object_pairs_hook=unique_fields)
    if not isinstance(before, dict) or not isinstance(after, dict):
        return False
    if not isinstance(before.get('version'), str) or not isinstance(after.get('version'), str):
        return False
    return ({key: value for key, value in before.items() if key != 'version'}
            == {key: value for key, value in after.items() if key != 'version'})


def narrow_change(root, change, names):
    name, old_mode, new_mode, _old_blob, _new_blob, status = change
    if (status not in ('A', 'M') or new_mode != '100644'
            or old_mode not in ('000000', new_mode)):
        return False
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts:
        return False
    if name == 'plugins/CHANGELOG.md':
        return True
    parts = path.parts
    if len(parts) < 4 or parts[0] != 'plugins' or parts[1] not in names:
        return False
    relative = parts[2:]
    if relative in (('.codex-plugin', 'plugin.json'), ('.claude-plugin', 'plugin.json')):
        return old_mode != '000000' and version_only(root, change)
    return documentation(relative)


def plugin_tests(root):
    modules = set()
    for pattern in TEST_PATTERNS:
        files = sorted((root / 'tests').glob(pattern))
        if not files:
            raise ValueError(f'missing verification suite: {pattern}')
        for path in files:
            if not path.is_file() or path.is_symlink():
                raise ValueError(f'missing verification suite: {path.name}')
            modules.add('tests.' + path.stem)
    return sorted(modules)


def plan(root, base, full=False):
    result = {'mode': 'full', 'reason': 'explicit full verification' if full else
              'unavailable comparison history', 'base': None, 'paths': [], 'tests': FULL_TESTS}
    if full:
        return result
    try:
        revision = git(root, 'rev-parse', '--verify', '--end-of-options',
                       base + '^{commit}').decode().strip()
        git(root, 'merge-base', '--is-ancestor', revision, 'HEAD')
        result['base'] = revision
        changes = transitions(root, revision)
        result['paths'] = sorted({change[0] for change in changes})
        if not changes:
            result['reason'] = 'empty change set requires full verification'
            return result
        names = registered_plugins(root, revision)
        for change in changes:
            if not narrow_change(root, change, names):
                result['reason'] = 'full verification required for ' + change[0]
                return result
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError, TypeError):
        result['reason'] = 'comparison history or changed input could not be verified'
        return result
    result.update(mode='plugins', reason='registered plugin documentation and version-only metadata',
                  tests=plugin_tests(root))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='origin/development',
                        help='intended integration base; missing or uncertain history runs full tests')
    parser.add_argument('--full', action='store_true')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--workers', type=int, choices=(1, 2), default=1)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    if args.workers != 1 and args.report is None:
        parser.error('--workers 2 requires --report for the existing CI runner')
    try:
        selected = plan(ROOT, args.base, args.full)
    except ValueError as error:
        parser.exit(1, f'verification error: {error}\n')
    print(('Verification scope: ' if args.run else '') + json.dumps(selected), flush=True)
    if args.run:
        command = [sys.executable, '-m', 'unittest', *selected['tests']]
        if args.report is not None:
            command = [sys.executable, str(ROOT / 'tools/ci_unittest.py'), '--workers',
                       str(args.workers), '--report', str(args.report), '--', *selected['tests']]
        os.chdir(ROOT)
        os.execv(sys.executable, command)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
