"""Express bypasses cadence, never channel or install integrity checks."""
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from tests.install_fixtures import _craft_bundle, _patch_attrs, install_mod
from tests.test_release import release_mod

ROOT = Path(__file__).resolve().parents[1]


class ExpressUpdates(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        (self.home / 'current').write_text('1.0.0')
        (self.home / 'mixed-router-state.json').write_text(
            json.dumps({'port': 1, 'token': 'test', 'last_error': 'installer_failed'}))
        (self.home / 'update-etag').write_text('previous')
        self.blob, self.latest = _craft_bundle('9.9.9')
        self.latest.update(express=True, serial=12,
                           sha256=hashlib.sha256(self.blob).hexdigest())
        self.children, self.fetches, self.feeds, self.sleeps = [], [], [], []
        _patch_attrs(self, run=self.child)

    def child(self, cmd, **kwargs):
        self.children.append(cmd)
        (self.home / 'releases' / '9.9.9').mkdir(parents=True, exist_ok=True)
        (self.home / 'current').write_text('9.9.9')
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    def run_update(self, express=True, status=200):
        args = install_mod.build_parser().parse_args(
            ['--home', str(self.home), '--update'] + (['--express-only'] if express else []))

        import importlib.util as _ilu
        _spec = _ilu.spec_from_file_location(
            'router_feed_verify_express',
            ROOT / 'packaging' / 'feed_verify.py')
        _fv = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_fv)
        _seed, _pub = _fv.generate_keypair()

        def read(feed, etag):
            self.feeds.append((feed, etag))
            return status, json.dumps(self.latest).encode(), 'candidate'

        def fetch(url):
            self.fetches.append(url)
            if url.endswith('.json.sig'):
                return _fv.sign_hex(_seed, json.dumps(self.latest).encode()).encode()
            return self.blob

        updater_mod = install_mod._updater
        old_key = updater_mod._FEED_VERIFY_KEY
        updater_mod._FEED_VERIFY_KEY = _pub
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                return install_mod.do_update(args, _read_feed=read, _fetch=fetch,
                                             _sleep=self.sleeps.append, _announce=lambda s: None)
        finally:
            updater_mod._FEED_VERIFY_KEY = old_key

    def test_ordinary_metadata_does_not_consume_the_regular_update(self):
        before = (self.home / 'mixed-router-state.json').read_bytes()
        for value in (False, None, 'true', 1):
            with self.subTest(value=value):
                self.latest['express'] = value
                self.assertEqual(self.run_update(), 0)
                self.assertEqual([u for u in self.fetches if not u.endswith('.json.sig')], [])
                self.assertEqual((self.home / 'update-etag').read_text(), 'previous')
                self.assertFalse((self.home / 'feed-serial').exists())
                self.assertEqual((self.home / 'mixed-router-state.json').read_bytes(), before)
        self.assertEqual(self.run_update(express=False), 0)
        self.assertEqual(len(self.children), 1)
        self.assertEqual((self.home / 'current').read_text(), '9.9.9')

    def test_stable_and_beta_express_reach_the_same_applying_path(self):
        for channel in ('stable', 'beta'):
            with self.subTest(channel=channel):
                (self.home / 'channel').write_text(channel)
                (self.home / 'current').write_text('1.0.0')
                self.assertEqual(self.run_update(), 0)
                self.assertTrue(self.feeds[-1][0].endswith('/' + channel + '/latest.json'))
                self.assertIn('--home', self.children[-1])
                self.assertNotIn('--feed', self.children[-1])
                self.assertEqual((self.home / 'current').read_text(), '9.9.9')
                self.assertLessEqual(self.sleeps[-1], 10)

    def test_unchanged_and_mid_install_pointer_do_not_hide_a_rollback(self):
        before = (self.home / 'mixed-router-state.json').read_bytes()
        self.run_update(status=304)
        (self.home / 'releases' / '9.9.9').mkdir(parents=True)
        (self.home / 'current').write_text('9.9.9')
        self.run_update()
        self.assertEqual([u for u in self.fetches if not u.endswith('.json.sig')], [])
        self.assertEqual((self.home / 'update-etag').read_text(), 'previous')
        self.assertEqual((self.home / 'mixed-router-state.json').read_bytes(), before)
        (self.home / 'current').write_text('1.0.0')  # failed install rolls back
        self.run_update()
        self.assertEqual(len(self.children), 1)

    def test_serial_origin_and_checksum_guards_still_refuse_express(self):
        for field, value, error in (('serial', -1, 'feed_serial'),
                                    ('url', 'https://untrusted.example/bundle', 'feed_untrusted'),
                                    ('sha256', '0' * 64, 'bundle_checksum')):
            with self.subTest(field=field):
                original = self.latest[field]
                self.latest[field] = value
                with self.assertRaises(install_mod._updater.UpdateError) as caught:
                    self.run_update()
                self.assertEqual(caught.exception.error_code, error)
                self.assertEqual(self.children, [])
                self.latest[field] = original

    def test_failed_express_attempt_waits_for_regular_retry(self):
        fail = lambda *a, **k: SimpleNamespace(returncode=1, stdout='', stderr='failure')
        _patch_attrs(self, run=fail)
        with self.assertRaises(SystemExit):
            self.run_update()
        fetched = len([u for u in self.fetches if not u.endswith('.json.sig')])
        self.assertEqual(install_mod._update_failures(self.home), {'9.9.9': 1})
        self.run_update()
        self.assertEqual(len([u for u in self.fetches if not u.endswith('.json.sig')]), fetched)
        self.assertEqual((self.home / 'update-etag').read_text(), 'previous')
        with self.assertRaises(SystemExit):
            self.run_update(express=False)
        self.assertEqual(install_mod._update_failures(self.home), {'9.9.9': 2})

    def test_regular_and_express_parents_cannot_overlap(self):
        with install_mod._svc.install_lock(self.home, 'update.lock'):
            self.run_update()
            self.run_update(express=False)
        self.assertEqual(self.feeds, [])
        self.run_update()
        self.assertEqual(len(self.children), 1)

    def test_express_flag_requires_the_applying_verb(self):
        with self.assertRaisesRegex(SystemExit, 'needs --update'):
            install_mod.main(['--express-only'])


class ExpressLauncher(unittest.TestCase):
    def test_alias_calls_supported_installer_and_skips_a_legacy_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            release = home / 'releases' / '1.0.0' / 'packaging'
            release.mkdir(parents=True)
            (home / 'current').write_text('1.0.0')
            launcher = home / 'express_launch.py'
            launcher.write_bytes((ROOT / 'packaging/update_launch.py').read_bytes())
            for supported in (True, False):
                output = home / 'argv.json'
                output.unlink(missing_ok=True)
                (release / 'install.py').write_text(
                    "# parser.add_argument('--update')\n"
                    + ("# parser.add_argument('--express-only')\n" if supported else '')
                    + "import json,sys,os\n"
                    + "open(os.environ['ARGV_OUT'], 'w').write(json.dumps(sys.argv))\n")
                result = subprocess.run([sys.executable, str(launcher)],
                                        env=dict(os.environ, ARGV_OUT=str(output)),
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(output.exists(), supported)
                if supported:
                    self.assertIn('--express-only', json.loads(output.read_text()))

    def test_legacy_bundle_cannot_replace_the_safe_express_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            packaging = home / 'release' / 'packaging'
            packaging.mkdir(parents=True)
            for name in ('update_launch.py', 'router_launch.py'):
                (packaging / name).write_text('# legacy launcher')
            (home / 'express_launch.py').write_text('safe newer launcher')
            install_mod.install_launcher(home, packaging.parent)
            self.assertEqual((home / 'express_launch.py').read_text(), 'safe newer launcher')


class ExpressTag(unittest.TestCase):
    def test_only_exact_version_and_supported_suffix_order_are_accepted(self):
        for suffix, expected in (('', ('stable', False)), ('-beta', ('beta', False)),
                                  ('-express', ('stable', True)), ('-beta-express', ('beta', True))):
            self.assertEqual(release_mod.release_tag('v1.2.3' + suffix, '1.2.3'), expected)
        for tag in ('Express', 'v1.2.4-express', 'v1.2.3-express-beta', 'v1x2x3-express'):
            with self.assertRaises(SystemExit):
                release_mod.release_tag(tag, '1.2.3')
