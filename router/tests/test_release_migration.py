"""Repository migration cannot publish a lower serial or omit its offset."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tests.test_workflows import run_block


@unittest.skipUnless(os.name == 'posix' and shutil.which('bash'),
                     'release workflow runs on Ubuntu')
class ReleaseMigrationTests(unittest.TestCase):
    def test_new_repository_cannot_build_without_a_migration_offset(self):
        env = {**os.environ, 'GITHUB_REPOSITORY': 'software-combined/SC_AI',
               'RELEASE_SERIAL_OFFSET': ''}
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(['bash', '-e', '-c', run_block('Build bundle')],
                                    cwd=temporary, env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Set RELEASE_SERIAL_OFFSET', result.stdout)
            self.assertFalse((Path(temporary) / 'dist').exists())
