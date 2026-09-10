"""Plan 059 Stage 1: one runtime lock, validated offline.

Missing/duplicate targets, bad digests, table drift, and unpinned entries
fail closed. The shipped lock carries reviewed live pins (CPython 3.14.7,
astral-sh build 20260814, verified against the downloaded archives:
byte sizes, GNU-safe member paths, interpreter and licence paths);
synthetic data only elsewhere. No staff machine.
"""
import copy
import hashlib
import importlib.util
import io
import json
import tarfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        'router_runtime_lock', ROOT / 'packaging' / 'runtime_lock.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


runtime_lock = _load()


def _doc():
    return json.loads((ROOT / 'packaging' / 'runtime.lock').read_text())


def _escapes(name):
    """True when a tar member path escapes its extraction root."""
    norm = name.replace('\\', '/')
    parts = norm.split('/')
    return (norm.startswith('/')
            or (len(parts[0]) == 2 and parts[0][1] == ':'
                and parts[0][0].isalpha())
            or '..' in parts)


class RuntimeLockTests(unittest.TestCase):
    def test_shipped_lock_validates(self):
        doc = runtime_lock.validate(_doc())
        self.assertEqual(len(doc['targets']), 4)

    def test_missing_targets_fails_closed(self):
        doc = _doc()
        del doc['targets']
        with self.assertRaises(SystemExit):
            runtime_lock.validate(doc)

    def test_duplicate_target_fails_closed(self):
        doc = _doc()
        doc['targets'].append(copy.deepcopy(doc['targets'][0]))
        with self.assertRaisesRegex(SystemExit, 'duplicates target'):
            runtime_lock.validate(doc)

    def test_unsupported_target_fails_closed(self):
        doc = _doc()
        entry = copy.deepcopy(doc['targets'][0])
        entry.update({'os': 'linux', 'cpu': 'arm64'})
        doc['targets'].append(entry)
        with self.assertRaisesRegex(SystemExit, 'unsupported target'):
            runtime_lock.validate(doc)

    def test_missing_field_fails_closed(self):
        doc = _doc()
        del doc['targets'][0]['sha256']
        with self.assertRaisesRegex(SystemExit, 'missing field'):
            runtime_lock.validate(doc)

    def test_unpinned_entry_refuses_to_provision(self):
        entry = copy.deepcopy(_doc()['targets'][0])
        entry.update(url='', sha256='')
        self.assertFalse(runtime_lock.provisionable(entry))
        entry.update(url='https://example.invalid/r.tar.gz',
                     sha256='0' * 64)
        self.assertTrue(runtime_lock.provisionable(entry))

    def test_shipped_lock_is_fully_pinned(self):
        for entry in _doc()['targets']:
            self.assertTrue(runtime_lock.provisionable(entry),
                            (entry['os'], entry['cpu']))

    def test_shipped_pins_match_verified_archives(self):
        # Sizes and paths below were read from the downloaded archives.
        expected = {
            ('darwin', 'arm64'): (26671536, 'python/bin/python3.14',
                                  'python/lib/python3.14/LICENSE.txt'),
            ('darwin', 'x86_64'): (26723319, 'python/bin/python3.14',
                                   'python/lib/python3.14/LICENSE.txt'),
            ('linux', 'x86_64'): (123986414, 'python/bin/python3.14',
                                  'python/lib/python3.14/LICENSE.txt'),
            ('windows', 'x86_64'): (49587410, 'python/python.exe',
                                    'python/LICENSE.txt'),
        }
        for entry in _doc()['targets']:
            size, exe, licence = expected[(entry['os'], entry['cpu'])]
            # The lock's own exec/licence paths must match the proof table:
            # otherwise a partial pin update leaves provisioning or audit
            # reading stale paths while this test stays green.
            self.assertEqual(entry['exec'], exe, entry['url'])
            self.assertEqual(entry['licences'], [licence], entry['url'])
            try:
                with urllib.request.urlopen(entry['url'], timeout=30) as r:
                    # Cap the read: a typo'd URL serving an unbounded body
                    # must fail closed, not OOM the runner before the size
                    # assertion runs.
                    blob = r.read(size + 1024 * 1024)
            except urllib.error.HTTPError:
                # Reachable server refusing the URL is a broken pin, not
                # missing network: fail, never skip. (HTTPError subclasses
                # OSError, so this must precede the OSError arm.)
                raise
            except OSError:
                self.skipTest('network unavailable for ' + entry['url'])
            self.assertEqual(len(blob), size, entry['url'])
            self.assertEqual(hashlib.sha256(blob).hexdigest(),
                             entry['sha256'], entry['url'])
            with tarfile.open(fileobj=io.BytesIO(blob), mode='r:gz') as tar:
                members = tar.getmembers()
            names = [m.name for m in members]
            self.assertIn(exe, names)
            self.assertIn(licence, names)
            for member in members:
                # Recorded as GNU-safe evidence for the future extractor:
                # POSIX and Windows separators, drive-absolute paths, and
                # symlink/hardlink targets are all in scope. Checked
                # per path: the member name itself, plus any link target
                # resolved against the member's directory.
                self.assertFalse(_escapes(member.name),
                                 'unsafe member ' + member.name)
                if member.issym() or member.islnk():
                    # Resolve the target against the member's directory
                    # the way extraction does (true dirname: '' at top
                    # level), then judge the resolved path with the same
                    # helper as member names plus a depth walk: absolute
                    # targets fail the helper, sibling-relative ../a/x
                    # passes the walk, ../../evil does not.
                    norm_name = member.name.replace('\\', '/')
                    base = norm_name.rpartition('/')[0]
                    link = member.linkname.replace('\\', '/')
                    if (link.startswith('/')
                            or (len(link) > 1 and link[1] == ':'
                                and link[0].isalpha())):
                        # Absolute target escapes wherever it points.
                        self.fail('unsafe link ' + member.name)
                    target = base + '/' + link if base else link
                    depth = 0
                    for seg in (s for s in target.split('/')
                                if s not in ('', '.')):
                        depth = depth - 1 if seg == '..' else depth + 1
                        self.assertGreaterEqual(
                            depth, 0, 'unsafe link ' + member.name)

    def test_select_maps_each_target_once(self):
        doc = _doc()
        for os_name, cpu in (('darwin', 'arm64'), ('darwin', 'x86_64'),
                             ('linux', 'x86_64'), ('windows', 'x86_64')):
            entry = runtime_lock.select(doc, os_name, cpu)
            self.assertIsNotNone(entry, (os_name, cpu))
            self.assertEqual((entry['os'], entry['cpu']), (os_name, cpu))
        self.assertIsNone(runtime_lock.select(doc, 'linux', 'arm64'))
        self.assertIsNone(runtime_lock.select(doc, 'windows', 'arm32'))

    def test_wrapper_table_covers_every_target(self):
        doc = _doc()
        table = runtime_lock.wrapper_table(doc)
        self.assertEqual(len(table), len(doc['targets']))
        for (os_name, cpu), (mirror, fmt, exe) in table.items():
            entry = runtime_lock.select(doc, os_name, cpu)
            self.assertEqual((mirror, fmt, exe),
                             (entry['mirror'], entry['format'], entry['exec']))


if __name__ == '__main__':
    unittest.main()
