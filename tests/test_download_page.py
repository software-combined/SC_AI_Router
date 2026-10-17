"""Browser boundary checks use Node's built-in sandbox, without a network."""
import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'browser contract checks require Node')
class DownloadPageTests(unittest.TestCase):
    def test_browser_signin_and_download_boundaries(self):
        script = Path(__file__).with_name('download_page_contract.cjs')
        result = subprocess.run(['node', str(script)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
