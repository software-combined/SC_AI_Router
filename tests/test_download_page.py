"""Download-page browser and publication checks, without a network."""
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from .test_publish_feed import ROOT, publish


@unittest.skipUnless(shutil.which('node'), 'browser contract checks require Node')
class DownloadPageTests(unittest.TestCase):
    def test_browser_signin_and_download_boundaries(self):
        script = Path(__file__).with_name('download_page_contract.cjs')
        result = subprocess.run(['node', str(script)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class DownloadPagePublicationTests(unittest.TestCase):
    def test_install_page_publishes_shared_fonts_and_their_licences(self):
        with mock.patch.object(publish, '_aws') as aws:
            publish.publish_setup_page('feed-bucket')
        calls = [call.args[0] for call in aws.call_args_list]
        for name, content_type in (('inter-400.woff2', 'font/woff2'),
                                   ('space-grotesk-400.woff2', 'font/woff2'),
                                   ('inter-OFL.txt', 'text/plain'),
                                   ('space-grotesk-OFL.txt', 'text/plain')):
            row, = [args for args in calls if args[3] == 's3://feed-bucket/install/' + name]
            self.assertEqual(Path(row[2]), ROOT / 'packaging/assets' / name)
            self.assertEqual(row[row.index('--content-type') + 1], content_type)


if __name__ == '__main__':
    unittest.main()
