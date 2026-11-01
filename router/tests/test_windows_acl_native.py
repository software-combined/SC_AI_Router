"""Actual Windows ACL APIs on disposable paths; skipped on other platforms."""
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_windows_acl import backend, winacl


@unittest.skipUnless(sys.platform == 'win32', 'requires native Windows ACL APIs')
class NativeAclTests(unittest.TestCase):
    def test_inherited_private_file_broad_grant_refusal_and_recovery(self):
        with tempfile.TemporaryDirectory(prefix='scg-acl-') as temporary:
            home = Path(temporary) / "é space [$name]; ' & (ACL)"
            home.mkdir()
            backend.protect_file(home, run=winacl._run)
            child = home / "inherited $name`[1]; & 'é'.key"
            child.write_text('synthetic test data', encoding='utf-8')
            winacl.check(child, fresh=True)
            doc = winacl._query(child)
            self.assertIn(doc['owner'], {doc['user'], 'S-1-5-18', 'S-1-5-32-544'})
            self.assertTrue(any(rule['sid'] == doc['user'] and rule['type'] == 0
                                and rule['flags'] & 16 for rule in doc['rules']))
            try:
                result = winacl._run(['icacls', str(child), '/grant', '*S-1-1-0:R'],
                                     capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                with self.assertRaisesRegex(SystemExit, 'readable by'):
                    winacl.check(child, fresh=True)
            finally:
                result = winacl._run(['icacls', str(child), '/remove:g', '*S-1-1-0'],
                                     capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
            winacl.check(child, fresh=True)
