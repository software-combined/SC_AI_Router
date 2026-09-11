"""Bootstrap token handling: off argv and persist-after-verify (Plan 054 T)."""
import hashlib
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

from tests._platform import unix_only

_ROOT = Path(__file__).resolve().parents[1]

# Stand-in for curl: logs its argv and serves the prepared downloads.
_CURL_FAKE = '''#!/usr/bin/env python3
import os
import shutil
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
if (out and os.environ.get('CURL_MODE') == 'ok-first'
        and url.endswith('/runtimes.json')):
    with open(out, 'w') as stream:
        stream.write(os.environ['RUNTIMES_JSON'])
    sys.exit(0)
name = ('runtimes.json' if url.endswith('/runtimes.json') else
        'mirror.bin' if '/runtimes/' in url else
        'latest.json' if url.endswith('/latest.json') else
        'bundle.bin' if '/bundles/' in url else '')
if os.environ.get('CURL_MODE') == 'full' and out and name:
    shutil.copyfile(os.path.join(os.environ.get('CURL_SERVE_DIR', ''), name), out)
    sys.exit(0)
sys.exit(1)
'''


def _tarball(files=()):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz') as tar:
        for name, text in files:
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


_FAKE_INSTALLER = (
    'import json, sys\n'
    'from pathlib import Path\n'
    'home = Path(__file__).resolve().parents[2]\n'
    "home.joinpath('installer-argv.txt').write_text(json.dumps(sys.argv))\n")
_FAKE_LANDED = (
    "home.joinpath('current').write_text(\n"
    "    json.loads(home.joinpath('latest.json').read_text())['version'])\n")


@unix_only
class BootstrapTokenTests(unittest.TestCase):
    def _env(self, tmp, mode, token='tok-new', mirror='runtimes/x.tar.gz',
             serve=None):
        bin_dir = Path(tmp) / 'bin'
        bin_dir.mkdir(exist_ok=True)
        curl = bin_dir / 'curl'
        curl.write_text(_CURL_FAKE)
        curl.chmod(0o755)
        os_name = {'Darwin': 'darwin', 'Linux': 'linux'}[platform.system()]
        arch = {'arm64': 'arm64', 'aarch64': 'arm64',
                'x86_64': 'x86_64', 'amd64': 'x86_64'}[platform.machine().lower()]
        return {
            **os.environ,
            'PATH': str(bin_dir) + os.pathsep + os.environ['PATH'],
            'ROUTER_HOME': str(Path(tmp) / 'home'),
            'SCG_FEED_TOKEN': token,
            'FEED_ORIGIN': 'https://feed.example',
            'CURL_MODE': mode,
            'CURL_ARGV_LOG': str(Path(tmp) / 'argv.log'),
            'CURL_SERVE_DIR': str(serve or ''),
            'RUNTIMES_JSON': json.dumps({'targets': {
                f'{os_name}/{arch}': {'mirror': mirror,
                                      'sha256': '00', 'exec': 'python/bin/python3.14'}}}),
        }

    def _run(self, tmp, mode, token='tok-new', mirror='runtimes/x.tar.gz',
             channel=None):
        home = Path(tmp) / 'home'
        env = self._env(tmp, mode, token=token, mirror=mirror)
        argv = ['sh', str(_ROOT / 'packaging' / 'bootstrap.sh')]
        if channel:
            argv.append('--channel=' + channel)
        proc = subprocess.run(argv, env=env, capture_output=True, text=True)
        return proc, home, Path(env['CURL_ARGV_LOG'])

    def _full_run(self, tmp, channel, installer_exit=0, land=True):
        """Serve every download so the bootstrap reaches install.py."""
        home = Path(tmp) / 'home'
        serve = Path(tmp) / 'serve'
        serve.mkdir()
        mirror = io.BytesIO()
        with tarfile.open(fileobj=mirror, mode='w:gz') as tar:
            link = tarfile.TarInfo('python/bin/python3.14')
            link.type, link.linkname, link.mode = tarfile.SYMTYPE, sys.executable, 0o755
            tar.addfile(link)
        (serve / 'mirror.bin').write_bytes(mirror.getvalue())
        body = _FAKE_INSTALLER + (_FAKE_LANDED if land else '')
        bundle = _tarball([('packaging/install.py',
                            body + 'sys.exit(%d)\n' % installer_exit)])
        (serve / 'bundle.bin').write_bytes(bundle)
        (serve / 'latest.json').write_text(json.dumps({
            'version': '9.9.9',
            'url': 'https://feed.example/bundles/ai-router-9.9.9.tar.gz',
            'sha256': hashlib.sha256(bundle).hexdigest(),
            'serial': 1, 'min_python': '3.14'}))
        os_name = {'Darwin': 'darwin', 'Linux': 'linux'}[platform.system()]
        arch = {'arm64': 'arm64', 'aarch64': 'arm64',
                'x86_64': 'x86_64', 'amd64': 'x86_64'}[platform.machine().lower()]
        (serve / 'runtimes.json').write_text(json.dumps({'targets': {
            f'{os_name}/{arch}': {
                'mirror': 'runtimes/cpython-test.tar.gz',
                'sha256': hashlib.sha256(
                    (serve / 'mirror.bin').read_bytes()).hexdigest(),
                'exec': 'python/bin/python3.14'}}}))
        proc = subprocess.run(
            ['sh', str(_ROOT / 'packaging' / 'bootstrap.sh'),
             '--channel=' + channel],
            env=self._env(tmp, 'full', serve=serve), capture_output=True, text=True)
        return proc, home

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
            self.assertFalse((home / 'channel').exists())

    def test_failed_bootstrap_does_not_switch_the_channel(self):
        # The channel is persisted only once install.py succeeds, so an
        # aborted bootstrap cannot move a stable host onto betas.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir(parents=True)
            (home / 'channel').write_text('stable\n')
            proc, home, _ = self._run(tmp, mode='ok-first', channel='beta')
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual((home / 'channel').read_text(), 'stable\n')

    @unittest.skipUnless(shutil.which('shasum'), 'needs shasum for the checksums')
    def test_bootstrap_pins_the_channel_and_persists_it_after_success(self):
        # The installer resolves its own feed from the router home, so the
        # requested channel must travel with this run, and only a successful
        # install may leave the channel file behind.
        for channel in ('stable', 'beta'):
            with tempfile.TemporaryDirectory() as tmp:
                proc, home = self._full_run(tmp, channel)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual((home / 'channel').read_text(), channel + '\n')
                argv = json.loads((home / 'installer-argv.txt').read_text())
                self.assertIn(f'https://feed.example/{channel}/latest.json', argv)

    @unittest.skipUnless(shutil.which('shasum'), 'needs shasum for the checksums')
    def test_failed_install_leaves_the_channel_alone(self):
        # The channel moves only when the installer itself succeeds.
        with tempfile.TemporaryDirectory() as tmp:
            proc, home = self._full_run(tmp, 'beta', installer_exit=3)
            self.assertEqual(proc.returncode, 3)
            self.assertFalse((home / 'channel').exists())

    @unittest.skipUnless(shutil.which('shasum'), 'needs shasum for the checksums')
    def test_channel_switch_clears_the_stale_feed_serial(self):
        # The new channel's serial is unrelated to the old one's; keeping it
        # would refuse every poll until that channel's next release.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir(parents=True)
            (home / 'channel').write_text('stable\n')
            (home / 'feed-serial').write_text('1240\n')
            proc, home = self._full_run(tmp, 'beta')
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual((home / 'channel').read_text(), 'beta\n')
            self.assertFalse((home / 'feed-serial').exists())

    @unittest.skipUnless(shutil.which('shasum'), 'needs shasum for the checksums')
    def test_deferred_run_leaves_the_channel_alone(self):
        # A lock-deferred install exits 0 without activating the feed's
        # version, so the channel must not follow it.
        with tempfile.TemporaryDirectory() as tmp:
            proc, home = self._full_run(tmp, 'beta', land=False)
            self.assertEqual(proc.returncode, 1)
            self.assertIn('did not land', proc.stderr)
            self.assertFalse((home / 'channel').exists())

    @unittest.skipUnless(shutil.which('shasum'), 'needs shasum for the checksums')
    def test_switch_to_an_older_channel_still_writes_it(self):
        # Beta normally runs ahead of stable: moving back must work even
        # though the installer finds nothing newer and leaves the pointer.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir(parents=True)
            (home / 'channel').write_text('beta\n')
            (home / 'current').write_text('9.9.10\n')
            proc, home = self._full_run(tmp, 'stable', land=False)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual((home / 'channel').read_text(), 'stable\n')

    @unittest.skipUnless(shutil.which('shasum'), 'needs shasum for the checksums')
    def test_same_channel_run_keeps_the_feed_serial(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir(parents=True)
            (home / 'channel').write_text('beta\n')
            (home / 'feed-serial').write_text('46\n')
            proc, home = self._full_run(tmp, 'beta')
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual((home / 'feed-serial').read_text(), '46\n')

    def test_unknown_channel_is_refused_before_any_fetch(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc, home, argv_log = self._run(tmp, mode='ok-first', channel='canary')
            self.assertEqual(proc.returncode, 2)
            self.assertFalse((home / 'channel').exists())
            self.assertFalse((home / 'feed-token').exists())
            self.assertFalse(argv_log.exists())

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
