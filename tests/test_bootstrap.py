"""Bootstrap token handling: off argv and persist-after-verify (Plan 054 T)."""
import json
import os
import platform
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests._platform import unix_only

_ROOT = Path(__file__).resolve().parents[1]

# Stand-in for curl: logs its argv, answers the runtimes.json fetch only.
_CURL_FAKE = '''#!/usr/bin/env python3
import os
import sys

args = sys.argv[1:]
with open(os.environ['CURL_ARGV_LOG'], 'a') as stream:
    stream.write(' '.join(args) + '\\n')
out = ''
url = ''
i = 0
while i < len(args):
    if args[i] == '-o':
        out = args[i + 1]
        i += 2
    elif args[i] == '-H':
        i += 2
    elif args[i].startswith('-'):
        i += 1
    else:
        url = args[i]
        i += 1
if (os.environ.get('CURL_MODE') == 'ok-first'
        and url.endswith('/runtimes.json') and out):
    with open(out, 'w') as stream:
        stream.write(os.environ['RUNTIMES_JSON'])
    sys.exit(0)
sys.exit(1)
'''


@unix_only
class BootstrapTokenTests(unittest.TestCase):
    def _run(self, tmp, mode, token='tok-new', mirror='runtimes/x.tar.gz'):
        home = Path(tmp) / 'home'
        bin_dir = Path(tmp) / 'bin'
        bin_dir.mkdir()
        curl = bin_dir / 'curl'
        curl.write_text(_CURL_FAKE)
        curl.chmod(0o755)
        os_name = {'Darwin': 'darwin', 'Linux': 'linux'}[platform.system()]
        arch = {'arm64': 'arm64', 'aarch64': 'arm64',
                'x86_64': 'x86_64', 'amd64': 'x86_64'}[platform.machine().lower()]
        argv_log = Path(tmp) / 'argv.log'
        env = {
            **os.environ,
            'PATH': str(bin_dir) + os.pathsep + os.environ['PATH'],
            'ROUTER_HOME': str(home),
            'SCG_FEED_TOKEN': token,
            'FEED_ORIGIN': 'https://feed.example',
            'CURL_MODE': mode,
            'CURL_ARGV_LOG': str(argv_log),
            'RUNTIMES_JSON': json.dumps({'targets': {
                f'{os_name}/{arch}': {'mirror': mirror,
                                      'sha256': '00', 'exec': 'python/bin/python3.14'}}}),
        }
        proc = subprocess.run(
            ['sh', str(_ROOT / 'packaging' / 'bootstrap.sh')],
            env=env, capture_output=True, text=True)
        return proc, home, argv_log

    def test_failed_fetch_persists_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir(parents=True)
            (home / 'feed-token').write_text('tok-old\n')
            proc, home, argv_log = self._run(tmp, mode='fail-all')
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual((home / 'feed-token').read_text(), 'tok-old\n')
            self.assertFalse((home / 'feed-token.previous').exists())
            self.assertNotIn('tok-new', argv_log.read_text())
            self.assertFalse((home / 'feed-headers.tmp').exists())

    def test_successful_fetch_persists_and_keeps_previous(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir(parents=True)
            (home / 'feed-token').write_text('tok-old\n')
            proc, home, argv_log = self._run(tmp, mode='ok-first')
            # The fake fails the runtime download after the token proof
            # point, so the script exits later without running install.py.
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual((home / 'feed-token').read_text(), 'tok-new\n')
            self.assertEqual((home / 'feed-token.previous').read_text(), 'tok-old\n')
            self.assertNotIn('tok-new', argv_log.read_text())
            self.assertFalse((home / 'feed-headers.tmp').exists())

    def test_runtime_url_percent_encodes_the_mirror(self):
        """A raw '+' in an S3 key is decoded as a space and denied at the edge."""
        with tempfile.TemporaryDirectory() as tmp:
            mirror = 'runtimes/cpython-3.14.7+20260814-aarch64-test.tar.gz'
            proc, _, argv_log = self._run(tmp, mode='ok-first', mirror=mirror)
            self.assertNotEqual(proc.returncode, 0)
            log = argv_log.read_text()
            self.assertIn('cpython-3.14.7%2B20260814', log)
            self.assertNotIn('+20260814', log)


if __name__ == '__main__':
    unittest.main()
