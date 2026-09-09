"""Plan 059 Stage 1: one runtime lock, validated offline.

Missing/duplicate targets, bad digests, table drift, and unpinned entries
fail closed. Synthetic data only; no download, no staff machine.
"""
import copy
import importlib.util
import json
import unittest
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
        doc = _doc()
        for entry in doc['targets']:
            self.assertFalse(runtime_lock.provisionable(entry))
        pinned = copy.deepcopy(doc['targets'][0])
        pinned.update({'url': 'https://example.invalid/r.tar.gz',
                       'sha256': '0' * 64})
        self.assertTrue(runtime_lock.provisionable(pinned))

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
