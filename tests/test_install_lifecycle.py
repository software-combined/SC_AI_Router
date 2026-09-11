"""Installer lifecycle: backup-before-replace, fail-closed uninstall, rollback.

Brief defects 4-5: config replacement must back up before truncating, a
failed restore must not stop services, --version rolls back from installed
releases (never the JSON feed), and a failed first install must not read
as up to date on retry.
"""
import contextlib
import io
import json
import os
import tarfile
import tempfile
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests._platform import unix_only
from tests.test_install import (
    _craft_bundle,
    _ok_run,
    _patch_attrs,
    _static_fetch,
    install_mod,
)
from tests.fakes import launchd_in_sync
from tests.test_install_config import _fake_write_catalogue


def _no_fetch(url):
    raise AssertionError('rollback must not fetch anything')


def _recording(calls):
    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return _ok_run(cmd, **kwargs)
    return fake_run


def _remanifest(blob, **fields):
    """Re-tar a crafted bundle with patched MANIFEST.json fields."""
    with tarfile.open(fileobj=io.BytesIO(blob), mode='r') as tar:
        manifest = json.loads(tar.extractfile('MANIFEST.json').read())
        names = tar.getnames()
        members = {name: tar.extractfile(name).read() for name in names
                   if name != 'MANIFEST.json'}
    manifest = dict(manifest, **fields)
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode='w') as tar:
        for name in names:
            data = json.dumps(manifest).encode() if name == 'MANIFEST.json' else members[name]
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return out.getvalue()


def _uninstall_home(tmp):
    """Staged home with one installed release, pointer current, and plists."""
    home = Path(tmp) / 'home'
    rel = home / 'releases' / '1.0.0'
    (rel / 'tools').mkdir(parents=True)
    (rel / 'tools' / 'disable.py').write_text('# stub\n')
    (home / 'current').write_text('1.0.0\n')
    (home / 'activation.json').write_text(json.dumps(
        {'config_path': str(Path(tmp) / 'fakehome' / '.codex' / 'config.toml'),
         'inserted_block': '# BEGIN local mixed model picker\n# END local mixed model picker\n'}))
    agents = Path(tmp) / 'fakehome' / 'Library' / 'LaunchAgents'
    agents.mkdir(parents=True)
    return home, agents


def _run_install(test, tmp, home, version, *extra_args, feed='file:///latest.json',
                 wait_version=True):
    blob, latest = _craft_bundle(version)
    latest = dict(latest, version=version)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return _ok_run(cmd, **kwargs)

    _patch_attrs(test, run=fake_run, self_test=lambda *args: None,
                 write_catalogue=_fake_write_catalogue,
                 wait_version=lambda *args, **kwargs: wait_version)
    argv = ['--home', str(home), *extra_args]
    if feed is not None:
        argv = ['--feed', feed, *argv]
    args = install_mod.build_parser().parse_args(argv)
    env = {'HOME': str(Path(tmp) / 'fakehome'), 'OPENROUTER_API_KEY': 'test-key'}
    with mock.patch.dict(os.environ, env):
        rc = install_mod.do_install(args, _fetch=_static_fetch(latest, blob),
                                    _run=fake_run)
    return rc, calls, args, env


class InstallLifecycleTests(unittest.TestCase):
    def test_current_pointer_reports_version_and_survives_garbage(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            self.assertEqual(install_mod.current_version(home), '0.0.0')
            self.assertIsNone(install_mod.current_release_dir(home))
            (home / 'current').write_text('  \n')
            self.assertEqual(install_mod.current_version(home), '0.0.0')
            self.assertIsNone(install_mod.current_release_dir(home))
            rel = home / 'releases' / '1.2.3'
            (rel / 'packaging').mkdir(parents=True)
            self.assertIsNone(install_mod.swap_current(home, rel))
            self.assertEqual(install_mod.current_version(home), '1.2.3')
            self.assertEqual(install_mod.current_release_dir(home), rel)

    def test_absolute_pointer_resolves_inside_releases(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            (home / 'releases' / 'passwd').mkdir(parents=True)
            (home / 'current').write_text('/etc/passwd\n')
            self.assertEqual(install_mod.current_release_dir(home),
                             home / 'releases' / 'passwd')
            self.assertEqual(install_mod.current_version(home), 'passwd')

    def test_binary_garbage_pointer_reads_as_no_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            (home / 'current').write_bytes(b'\x00\xff\xfe\x01')
            self.assertEqual(install_mod.current_version(home), '0.0.0')
            self.assertIsNone(install_mod.current_release_dir(home))

    @unix_only
    def test_swap_current_migrates_legacy_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            prev = home / 'releases' / '0.2.0'
            (prev / 'packaging').mkdir(parents=True)
            (prev / 'packaging' / 'VERSION').write_text('0.2.0\n')
            os.symlink(str(prev), home / 'current')
            self.assertEqual(install_mod.current_version(home), '0.2.0')
            install_mod.swap_current(home, home / 'releases' / '0.3.0')
            self.assertFalse((home / 'current').is_symlink())
            self.assertEqual((home / 'current').read_text(), '0.3.0\n')

    @unix_only
    def test_config_backup_holds_pre_replacement_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            rc, _, _, env = _run_install(self, tmp, home, '1.0.0')
            self.assertEqual(rc, 0)
            config = Path(env['HOME']) / '.codex' / 'config.toml'
            first_config = config.read_text()
            config.write_text('other = 1\n' + first_config)
            _run_install(self, tmp, home, '1.0.1')
            backups = sorted(home.glob('config-before-*.toml'))
            self.assertTrue(backups)
            self.assertEqual(backups[-1].read_text(), 'other = 1\n' + first_config)

    def test_uninstall_aborts_when_restore_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, agents = _uninstall_home(tmp)
            main_plist = agents / (install_mod.LABEL + '.plist')
            main_plist.write_text('plist\n')
            calls = []

            def fake_run(cmd, **kwargs):
                calls.append(list(cmd))
                if 'disable.py' in cmd[-1]:
                    return SimpleNamespace(returncode=1, stdout='boom', stderr='nope')
                return _ok_run(cmd, **kwargs)

            _patch_attrs(self, run=fake_run)
            args = install_mod.build_parser().parse_args(['--home', str(home)])
            with mock.patch.dict(os.environ, {'HOME': str(Path(tmp) / 'fakehome')}):
                with self.assertRaisesRegex(SystemExit, 'services left running'):
                    install_mod.do_uninstall(args)
            self.assertFalse(any(cmd[:2] == ['launchctl', 'bootout'] for cmd in calls),
                             'failed restore must not stop services')
            self.assertTrue(main_plist.exists())

    @unix_only
    def test_uninstall_proceeds_when_restore_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, agents = _uninstall_home(tmp)
            (agents / (install_mod.LABEL + '.plist')).write_text('plist\n')
            (agents / (install_mod.UPDATE_LABEL + '.plist')).write_text('plist\n')
            seen = {}

            def fake_run(cmd, **kwargs):
                if 'disable.py' in cmd[-1]:
                    seen['env'] = kwargs.get('env')
                    return SimpleNamespace(
                        returncode=0,
                        stdout='OpenAI direct routing restored. Restart Codex.\n',
                        stderr='')
                return _ok_run(cmd, **kwargs)

            _patch_attrs(self, run=fake_run)
            args = install_mod.build_parser().parse_args(['--home', str(home)])
            with mock.patch.dict(os.environ, {'HOME': str(Path(tmp) / 'fakehome')}):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    self.assertEqual(install_mod.do_uninstall(args), 0)
            self.assertIn('OpenAI direct routing restored', buf.getvalue())
            self.assertEqual(seen['env'].get('ROUTER_HOME'), str(home))
            self.assertFalse((agents / (install_mod.LABEL + '.plist')).exists())
            self.assertFalse((agents / (install_mod.UPDATE_LABEL + '.plist')).exists())
            # A receipt outliving its restored settings makes the next
            # install refuse guidance it finds missing rather than changed.
            self.assertFalse((home / 'activation.json').exists())

    @unix_only
    def test_version_rolls_back_from_installed_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            _run_install(self, tmp, home, '1.0.0')
            _, calls, _, _ = _run_install(self, tmp, home, '1.0.1')
            # Those installs pinned --feed, so they leave the release serial
            # alone; seed one so the invariant below has something to protect.
            (home / 'feed-serial').write_text('9\n')
            serial_before = (home / 'feed-serial').read_text()
            _patch_attrs(self, wait_version=lambda *args, **kwargs: True)
            args = install_mod.build_parser().parse_args(
                ['--home', str(home), '--version', '1.0.0'])
            with mock.patch.dict(os.environ, {'OPENROUTER_API_KEY': 'k'}):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    self.assertEqual(install_mod.do_install(args, _fetch=_no_fetch), 0)
            self.assertIn('rolled back to 1.0.0', buf.getvalue())
            self.assertEqual((home / 'current').read_text(), '1.0.0\n')
            self.assertTrue(any(cmd[:3] == ['launchctl', 'kill', 'TERM'] for cmd in calls))
            self.assertEqual((home / 'feed-serial').read_text(), serial_before)

    def test_version_rollback_needs_installed_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()

            args = install_mod.build_parser().parse_args(
                ['--home', str(home), '--version', '9.9.9'])
            with self.assertRaisesRegex(SystemExit, 'not installed'):
                install_mod.do_install(args, _fetch=_no_fetch)

    @unix_only
    def test_version_rollback_restores_previous_on_health_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            _run_install(self, tmp, home, '1.0.0')
            _run_install(self, tmp, home, '1.0.1')
            _patch_attrs(self, wait_version=lambda *args, **kwargs: None)
            args = install_mod.build_parser().parse_args(
                ['--home', str(home), '--version', '1.0.0'])
            with mock.patch.dict(os.environ, {'OPENROUTER_API_KEY': 'k'}):
                with self.assertRaises(SystemExit):
                    install_mod.do_install(args, _fetch=_no_fetch)
            self.assertEqual((home / 'current').read_text(), '1.0.1\n')

    @unix_only
    def test_failed_first_install_retries_instead_of_up_to_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            blob, latest = _craft_bundle('1.0.0')
            fake_fetch = _static_fetch(latest, blob)
            _patch_attrs(self, run=lambda cmd, **kwargs: _ok_run(cmd, **kwargs),
                         self_test=lambda *args: None,
                         write_catalogue=_fake_write_catalogue,
                         wait_version=lambda *args, **kwargs: None)
            args = install_mod.build_parser().parse_args(
                ['--feed', 'file:///latest.json', '--home', str(home)])
            env = {'HOME': str(Path(tmp) / 'fakehome'), 'OPENROUTER_API_KEY': 'test-key'}
            with mock.patch.dict(os.environ, env):
                with self.assertRaises(SystemExit):
                    install_mod.do_install(args, _fetch=fake_fetch)
            self.assertFalse((home / 'current').exists())
            _patch_attrs(self, wait_version=lambda *args, **kwargs: True)
            with mock.patch.dict(os.environ, env):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = install_mod.do_install(args, _fetch=fake_fetch)
            self.assertEqual(rc, 0)
            self.assertIn('installed 1.0.0', buf.getvalue())
            self.assertEqual((home / 'current').read_text(), '1.0.0\n')

    def _check_update_home(self, tmp):
        """Bare home dir with router state for check-update tests."""
        home = Path(tmp) / 'home'
        home.mkdir()
        (home / 'mixed-router-state.json').write_text(
            json.dumps({'port': 1, 'token': 'x'}))
        return home

    def _check_update_args(self, home):
        return install_mod.build_parser().parse_args(
            ['--feed', 'file:///latest.json', '--home', str(home)])

    def test_check_update_fails_fast_on_http_error(self):
        # Deterministic feed errors (HTTP 4xx/5xx) must not burn backoff.
        with tempfile.TemporaryDirectory() as tmp:
            home = self._check_update_home(tmp)
            attempts = []
            sleeps = []

            def denied(feed, etag):
                attempts.append(feed)
                raise urllib.error.HTTPError(feed, 404, 'Not Found', {}, None)

            args = self._check_update_args(home)
            with self.assertRaises(urllib.error.HTTPError):
                install_mod.do_check_update(
                    args, _read_feed=denied, _sleep=sleeps.append)
            self.assertEqual(len(attempts), 1, 'HTTP errors must not retry')
            # Only the opening jitter sleep runs; no backoff sleep on fail-fast path.
            self.assertEqual(len(sleeps), 1, sleeps)
            self.assertLessEqual(sleeps[0], 120)

    def test_check_update_reraises_after_retry_exhaustion(self):
        # Persistent outage: exactly 4 attempts, backoff [30, 60, 120], then raise.
        with tempfile.TemporaryDirectory() as tmp:
            home = self._check_update_home(tmp)
            attempts = []
            sleeps = []

            def down(feed, etag):
                attempts.append(feed)
                raise OSError('simulated persistent outage')

            def boom(url):
                raise AssertionError('tarball must not download on persistent outage')

            args = self._check_update_args(home)
            with self.assertRaises(OSError):
                install_mod.do_check_update(
                    args, _fetch=boom, _read_feed=down, _sleep=sleeps.append)
            self.assertEqual(len(attempts), 4, 'must exhaust all attempts')
            self.assertLessEqual(sleeps[0], 120, 'opening jitter sleep')
            self.assertEqual(sleeps[1:], [30, 60, 120], 'bounded backoff schedule')
            self.assertFalse((home / 'update-etag').exists(), 'no etag write on failure')

    def test_check_update_retries_transient_feed_failure(self):
        # A blipped feed fetch must not kill the poll: the run retries
        # in-cycle, then proceeds. There is no idle gate any more, so this
        # ends at the surviving deferral: the child installer ran but did not
        # activate the requested version.
        with tempfile.TemporaryDirectory() as tmp:
            home = self._check_update_home(tmp)
            latest = {'version': '9.9.9', 'url': 'file:///bundle.tar.gz',
                      'sha256': None, 'min_python': '3.14'}
            attempts = []

            def flaky_read(feed, etag):
                attempts.append(feed)
                if len(attempts) == 1:
                    raise OSError('simulated transient network failure')
                return 200, json.dumps(latest).encode(), 'etag-B'

            blob, _ = _craft_bundle('9.9.9')
            _patch_attrs(self, run=lambda cmd, **kw: _ok_run(cmd, **kw))
            args = self._check_update_args(home)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = install_mod.do_check_update(
                    args, _fetch=lambda url: blob, _read_feed=flaky_read,
                    _sleep=lambda s: None)
            self.assertEqual(rc, 0, buf.getvalue())
            self.assertEqual(len(attempts), 2, 'feed must be re-read after transient failure')
            self.assertIn('retrying feed fetch', buf.getvalue())
            self.assertIn('deferred', buf.getvalue())

class SafeUpdateTests(unittest.TestCase):
    """Long-term safe-update seams: identity gate, busy deferral, TERM-only
    rollback, three-release retention (incident 2026-09-08: 0.6.4.100 feed
    pointed at a 0.6.4.0 bundle, installer waited on an impossible version,
    then bootout stranded the machine with no router)."""

    def test_identity_mismatch_aborts_before_mutation(self):
        # Feed 9.9.9 vs manifest 9.9.8 through the real install path: no
        # pointer, no published release, no launchd signal, no serial write.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            blob, latest = _craft_bundle('9.9.9')
            bad_blob = _remanifest(blob, version='9.9.8')
            calls = []
            _patch_attrs(self, run=_recording(calls),
                         self_test=lambda *a: None,
                         write_catalogue=_fake_write_catalogue,
                         wait_version=lambda *a, **k: True)
            # Unpinned: only that path records a serial, so only there does
            # "aborted before the serial write" assert anything.
            args = install_mod.build_parser().parse_args(['--home', str(home)])
            env = {'HOME': str(Path(tmp) / 'fakehome'), 'OPENROUTER_API_KEY': 'test-key'}
            with mock.patch.dict(os.environ, env):
                with self.assertRaisesRegex(SystemExit, 'release identity mismatch'):
                    install_mod.do_install(args, _fetch=_static_fetch(latest, bad_blob))
            self.assertFalse((home / 'current').exists())
            self.assertFalse((home / 'feed-serial').exists())
            self.assertFalse(list((home / 'releases').glob('9.9.9')),
                             'identity failure must not publish a release')
            signals = [c for c in calls if c[:2] == ['launchctl', 'kill']
                       or 'bootout' in c or 'bootstrap' in c]
            self.assertFalse(signals, 'identity failure must not signal launchd')

    @unix_only
    def test_busy_upgrade_proceeds_and_hands_over_in_place(self):
        # There is no idle gate: waiting for inflight to reach zero delayed
        # every update on a machine actually in use. A TERM is safe while
        # requests are in flight because launchd keeps the listening socket
        # and the outgoing process drains what it already accepted.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            rc, calls, _, _ = _run_install(self, tmp, home, '1.0.0')
            self.assertEqual(rc, 0)
            blob, latest = _craft_bundle('1.0.1')
            _patch_attrs(self,
                         health=lambda state, timeout=20: {
                             'status': 'ok', 'version': '1.0.1', 'inflight': 3},
                         wait_version=lambda *a, **k: {'status': 'ok',
                                                       'version': '1.0.1'})
            launchd_in_sync(home, install_mod.LABEL, install_mod.UPDATE_LABEL)
            args = install_mod.build_parser().parse_args(
                ['--feed', 'file:///latest.json', '--home', str(home)])
            env = {'HOME': str(Path(tmp) / 'fakehome'), 'OPENROUTER_API_KEY': 'test-key'}
            n_calls = len(calls)
            with mock.patch.dict(os.environ, env):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = install_mod.do_install(
                        args, _fetch=_static_fetch(latest, blob),
                        _run=_recording(calls))
            self.assertEqual(rc, 0, buf.getvalue())
            self.assertNotIn('deferred', buf.getvalue())
            self.assertEqual((home / 'current').read_text(), '1.0.1\n',
                             'a busy router must still be updated')
            fresh = calls[n_calls:]
            self.assertTrue([c for c in fresh if c[:3] == ['launchctl', 'kill', 'TERM']],
                            'the swap hands over with a TERM')
            self.assertFalse([c for c in fresh if 'bootout' in c],
                             'an in-place handover must never bootout')

    @unix_only
    def test_failed_upgrade_rolls_back_with_term_not_bootout(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            _run_install(self, tmp, home, '1.0.0')
            blob, latest = _craft_bundle('1.0.1')
            calls = []
            _patch_attrs(self, run=_recording(calls),
                         self_test=lambda *a: None,
                         wait_version=lambda *a, **k: None)
            # launchd is running what the previous install wrote, so this
            # upgrade needs no reload and the rollback has a live job to TERM.
            launchd_in_sync(home, install_mod.LABEL, install_mod.UPDATE_LABEL)
            args = install_mod.build_parser().parse_args(
                ['--feed', 'file:///latest.json', '--home', str(home)])
            env = {'HOME': str(Path(tmp) / 'fakehome'), 'OPENROUTER_API_KEY': 'test-key'}
            with mock.patch.dict(os.environ, env):
                with self.assertRaises(SystemExit):
                    install_mod.do_install(args, _fetch=_static_fetch(latest, blob))
            self.assertEqual((home / 'current').read_text(), '1.0.0\n')
            self.assertFalse(any('bootout' in c for c in calls),
                             'rollback must TERM, never bootout a live service')
            self.assertTrue(any(c[:3] == ['launchctl', 'kill', 'TERM'] for c in calls))

    def test_prune_releases_keeps_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            rel = home / 'releases'
            for v in ('1.0.0', '1.0.1', '1.0.2', '1.0.3'):
                (rel / v).mkdir(parents=True)
            install_mod.prune_releases(home, '1.0.3', '1.0.2')
            kept = sorted(p.name for p in rel.iterdir())
            self.assertEqual(kept, ['1.0.1', '1.0.2', '1.0.3'])

    def test_prune_releases_ignores_non_version_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            rel = home / 'releases'
            for v in ('1.0.0', '1.0.1', '1.0.2', '1.0.3', 'manual-backup'):
                (rel / v).mkdir(parents=True)
            install_mod.prune_releases(home, '1.0.3', '1.0.2')
            kept = sorted(p.name for p in rel.iterdir())
            self.assertEqual(kept, ['1.0.1', '1.0.2', '1.0.3', 'manual-backup'])


if __name__ == '__main__':
    unittest.main()
