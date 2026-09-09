"""Pinned private CPython runtime lock (Plan 059 Stage 1). Python 3.9-safe.

packaging/runtime.lock names one install-only distribution per qualified
target. Pins (URL, SHA-256) land only through reviewed lock changes: an
entry without both refuses to provision. Generates wrapper pin tables so
native bootstraps cannot drift from the lock.
"""
import json
import sys
from pathlib import Path

LOCK_NAME = 'runtime.lock'
REQUIRED_ENTRY_FIELDS = ('os', 'cpu', 'triple', 'url', 'mirror', 'format',
                         'sha256', 'exec', 'licences')
SUPPORTED_FORMATS = ('tar.gz',)
SUPPORTED_TARGETS = (
    ('darwin', 'arm64'), ('darwin', 'x86_64'),
    ('linux', 'x86_64'), ('windows', 'x86_64'),
)


def lock_path():
    return Path(__file__).resolve().parent / LOCK_NAME


def load(path=None):
    try:
        doc = json.loads(Path(path or lock_path()).read_text())
    except FileNotFoundError:
        raise SystemExit('runtime lock missing: %s' % (path or LOCK_NAME))
    except ValueError as exc:
        raise SystemExit('runtime lock is not valid JSON: %s (%s)'
                         % (path or LOCK_NAME, exc))
    return doc


def validate(doc):
    """Fail closed on a malformed, duplicate, or unsupported-target lock."""
    if not isinstance(doc, dict):
        raise SystemExit('runtime lock must be a JSON object')
    for field in ('cpython', 'build', 'targets'):
        if field not in doc:
            raise SystemExit('runtime lock missing field: ' + field)
    targets = doc['targets']
    if not isinstance(targets, list) or not targets:
        raise SystemExit('runtime lock has no targets')
    seen = set()
    for entry in targets:
        if not isinstance(entry, dict):
            raise SystemExit('runtime lock target must be an object')
        for field in REQUIRED_ENTRY_FIELDS:
            if field not in entry:
                raise SystemExit('runtime lock target missing field: ' + field)
        key = (entry['os'], entry['cpu'])
        if key in seen:
            raise SystemExit('runtime lock duplicates target: %s/%s' % key)
        seen.add(key)
        if key not in SUPPORTED_TARGETS:
            raise SystemExit('runtime lock has unsupported target: %s/%s' % key)
        if entry['format'] not in SUPPORTED_FORMATS:
            raise SystemExit('runtime lock has unsupported format: %s' % entry['format'])
        if entry['os'] == 'linux' and entry.get('libc') != 'glibc':
            raise SystemExit('runtime lock linux target must pin glibc')
        if not isinstance(entry['licences'], list) or not entry['licences']:
            raise SystemExit('runtime lock target names no licence files')
    return doc


def select(doc, os_name, cpu):
    """Lock entry for this machine, or None when the target is refused."""
    for entry in doc.get('targets', []):
        if entry.get('os') == os_name and entry.get('cpu') == cpu:
            return entry
    return None


def provisionable(entry):
    """True only when review has pinned an immutable source and digest."""
    return bool(entry.get('url')) and bool(entry.get('sha256'))


def wrapper_table(doc):
    """os/cpu -> (mirror, format, exec) for native bootstrap wrappers."""
    return {(e['os'], e['cpu']): (e['mirror'], e['format'], e['exec'])
            for e in doc.get('targets', [])}


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    doc = validate(load())
    if args == ['--check']:
        print('runtime lock ok: %d targets (cpython %s build %s)'
              % (len(doc['targets']), doc['cpython'], doc['build']))
        return 0
    if args[:1] == ['--table']:
        for (os_name, cpu), (mirror, fmt, exe) in sorted(wrapper_table(doc).items()):
            print('%s/%s %s %s %s' % (os_name, cpu, mirror, fmt, exe))
        return 0
    raise SystemExit('usage: python3 packaging/runtime_lock.py --check|--table')


if __name__ == '__main__':
    sys.exit(main())
