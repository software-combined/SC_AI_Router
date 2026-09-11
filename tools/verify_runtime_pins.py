"""Verify pinned CPython runtime archives (Plan 092).

Reads packaging/runtime.lock and downloads each pinned archive with a
capped read, asserting byte size, sha256, interpreter/licence members,
and tar-member path safety. Network OSError is a hard failure, never a
skip. --dry-run prints the four URLs without fetching.
"""
import argparse
import hashlib
import io
import json
import sys
import tarfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Sizes were read from the downloaded archives (see Plan 059 Stage 1).
EXPECTED = {
    ('darwin', 'arm64'): (26671536, 'python/bin/python3.14',
                          'python/lib/python3.14/LICENSE.txt'),
    ('darwin', 'x86_64'): (26723319, 'python/bin/python3.14',
                           'python/lib/python3.14/LICENSE.txt'),
    ('linux', 'x86_64'): (123986414, 'python/bin/python3.14',
                          'python/lib/python3.14/LICENSE.txt'),
    ('windows', 'x86_64'): (49587410, 'python/python.exe',
                            'python/LICENSE.txt'),
}


def _escapes(name):
    """True when a tar member path escapes its extraction root."""
    norm = name.replace('\\', '/')
    parts = norm.split('/')
    return (norm.startswith('/')
            or (len(parts[0]) == 2 and parts[0][1] == ':'
                and parts[0][0].isalpha())
            or '..' in parts)


def _fail(message):
    print('verify_runtime_pins: FAILED: ' + message)
    raise SystemExit(1)


def lock_doc():
    try:
        return json.loads((ROOT / 'packaging' / 'runtime.lock').read_text())
    except (OSError, ValueError) as exc:
        _fail('cannot read packaging/runtime.lock: %s' % exc)


def check_entry(entry):
    key = (entry['os'], entry['cpu'])
    if key not in EXPECTED:
        _fail('unexpected lock target %s/%s' % key)
    size, exe, licence = EXPECTED[key]
    if entry['exec'] != exe:
        _fail('exec drift for %s: lock has %r, expected %r'
              % (entry['url'], entry['exec'], exe))
    if entry['licences'] != [licence]:
        _fail('licence drift for %s: lock has %r, expected %r'
              % (entry['url'], entry['licences'], [licence]))
    try:
        with urllib.request.urlopen(entry['url'], timeout=30) as resp:
            # Cap the read: a typo'd URL serving an unbounded body
            # must fail closed, not OOM the runner before the size
            # assertion runs.
            blob = resp.read(size + 1024 * 1024)
    except urllib.error.HTTPError as exc:
        _fail('HTTP %s for %s' % (exc.code, entry['url']))
    except OSError as exc:
        _fail('network error for %s: %s' % (entry['url'], exc))
    if len(blob) != size:
        _fail('size mismatch for %s: got %d, expected %d'
              % (entry['url'], len(blob), size))
    digest = hashlib.sha256(blob).hexdigest()
    if digest != entry['sha256']:
        _fail('sha256 mismatch for %s' % entry['url'])
    with tarfile.open(fileobj=io.BytesIO(blob), mode='r:gz') as tar:
        members = tar.getmembers()
    names = [m.name for m in members]
    if exe not in names:
        _fail('missing exec member %s in %s' % (exe, entry['url']))
    if licence not in names:
        _fail('missing licence member %s in %s' % (licence, entry['url']))
    for member in members:
        if _escapes(member.name):
            _fail('unsafe member ' + member.name)
        if member.issym() or member.islnk():
            norm_name = member.name.replace('\\', '/')
            base = norm_name.rpartition('/')[0]
            link = member.linkname.replace('\\', '/')
            if (link.startswith('/')
                    or (len(link) > 1 and link[1] == ':'
                        and link[0].isalpha())):
                _fail('unsafe link ' + member.name)
            target = base + '/' + link if base else link
            depth = 0
            for seg in (s for s in target.split('/')
                        if s not in ('', '.')):
                depth = depth - 1 if seg == '..' else depth + 1
                if depth < 0:
                    _fail('unsafe link ' + member.name)
    print('ok %s/%s %d bytes' % (entry['os'], entry['cpu'], size))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true',
                        help='print the pinned URLs without fetching')
    args = parser.parse_args(argv)
    doc = lock_doc()
    targets = doc.get('targets', [])
    if not targets:
        _fail('runtime.lock declares no targets')
    if args.dry_run:
        for entry in targets:
            print(entry['url'])
        return 0
    for entry in targets:
        check_entry(entry)
    print('verify_runtime_pins: all %d pins verified' % len(targets))
    return 0


if __name__ == '__main__':
    sys.exit(main())
