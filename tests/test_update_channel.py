"""The scheduled update channel must be adopted, and never self-destruct.

Two defects this file pins. First, the updater plist used to name a
per-release `install.py`; launchd runs its in-memory copy of a loaded plist,
so once `prune_releases` deleted that release the updater fired a missing
file every 900s and automatic updates stopped with no signal. Adopting the
release-independent launcher requires comparing the whole loaded command:
the interpreter is unchanged on a normal upgrade, so a check that reads
argv[0] alone never fires and the stale command survives forever.

Second, the scheduled updater is what runs the installer. Booting that label
out from inside it kills the process issuing the bootout, so `unload` waits
out its whole timeout for a label that cannot leave the domain and returns
without ever bootstrapping -- the updater is gone and the run still succeeds.
"""
import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests._platform import unix_only
from tests.fakes import LAUNCHD, static_fetch as _static_fetch
from tests.install_fixtures import _craft_bundle, _ok_run, _patch_attrs, install_mod
from tests.test_install_config import _fake_write_catalogue

LABEL = install_mod.LABEL
UPDATE_LABEL = install_mod.UPDATE_LABEL


@unix_only
class UpdaterAdoptionTests(unittest.TestCase):

    def _upgrade(self, tmp, env_extra=None):
        """Seed 1.0.0, stage a stale per-release updater command, upgrade."""
        home = Path(tmp) / 'home'
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            return _ok_run(cmd, **kwargs)

        _patch_attrs(self, run=fake_run, self_test=lambda *a: None,
                     write_catalogue=_fake_write_catalogue,
                     wait_version=lambda *a, **k: {'status': 'ok'})
        env = dict({'HOME': str(Path(tmp) / 'fakehome'),
                    'OPENROUTER_API_KEY': 'k',
                    'ROUTER_NO_KEY_WINDOW': '1'}, **(env_extra or {}))
        with mock.patch.dict(os.environ, env):
            args = install_mod.build_parser().parse_args(
                ['--feed', 'file:///latest.json', '--home', str(home)])
            blob, latest = _craft_bundle('1.0.0')
            self.assertEqual(
                install_mod.do_install(args, _fetch=_static_fetch(latest, blob),
                                       _run=_ok_run), 0)
            # The state a real machine is in before this release: same
            # interpreter, but launchd still holds the per-release installer.
            program = LAUNCHD.DEFAULT_PROGRAM
            stale = [program, str(home / 'releases' / '1.0.0' / 'packaging'
                                  / 'install.py'), '--check-update',
                     '--home', str(home)]
            LAUNCHD.reset(program=program, commands={
                LABEL: [program, str(home / 'router_launch.py')],
                UPDATE_LABEL: stale})
            calls.clear()
            blob, latest = _craft_bundle('1.0.1')
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = install_mod.do_install(
                    args, _fetch=_static_fetch(latest, blob), _run=fake_run)
        return home, calls, rc, buf.getvalue()

    def test_a_stale_updater_command_is_adopted_even_when_python_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, calls, rc, _out = self._upgrade(tmp)
            self.assertEqual(rc, 0)
            updater = [c for c in calls if c[:2] == ['launchctl', 'bootstrap']
                       and c[-1].endswith('.update.plist')]
            self.assertTrue(updater, 'a changed updater command must be reloaded')
            self.assertEqual(
                LAUNCHD.commands[UPDATE_LABEL],
                [LAUNCHD.DEFAULT_PROGRAM, str(home / 'update_launch.py')],
                'launchd must end up running the release-independent launcher')

    def test_never_boots_out_the_job_this_installer_is_running_inside(self):
        # launchd stamps XPC_SERVICE_NAME into the job's environment and
        # children inherit it, so the scheduled run can recognise itself.
        with tempfile.TemporaryDirectory() as tmp:
            home, calls, rc, out = self._upgrade(
                tmp, env_extra={'XPC_SERVICE_NAME': UPDATE_LABEL})
            self.assertEqual(rc, 0, 'a deferred adoption must not fail the install')
            self.assertFalse(
                [c for c in calls if c[:2] == ['launchctl', 'bootout']
                 and c[-1].endswith('.update')],
                'the installer must never bootout its own launchd job')
            self.assertIn('next manual install or login', out)
            self.assertTrue((home / 'update_launch.py').is_file(),
                            'the rewritten launcher is still installed for adoption')

    def test_prune_keeps_the_release_launchd_still_names(self):
        # A scheduled run defers the updater reload, so launchd goes on
        # running the old per-release installer path. Pruning that release
        # would leave it firing a missing file on every poll with nothing to
        # report it -- the exact silent loss this release removes.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'

            def fake_run(cmd, **kwargs):
                return _ok_run(cmd, **kwargs)

            _patch_attrs(self, run=fake_run, self_test=lambda *a: None,
                         write_catalogue=_fake_write_catalogue,
                         wait_version=lambda *a, **k: {'status': 'ok'})
            env = {'HOME': str(Path(tmp) / 'fakehome'), 'OPENROUTER_API_KEY': 'k',
                   'ROUTER_NO_KEY_WINDOW': '1',
                   'XPC_SERVICE_NAME': UPDATE_LABEL}
            with mock.patch.dict(os.environ, env):
                args = install_mod.build_parser().parse_args(
                    ['--feed', 'file:///latest.json', '--home', str(home)])
                blob, latest = _craft_bundle('1.0.0')
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(install_mod.do_install(
                        args, _fetch=_static_fetch(latest, blob), _run=_ok_run), 0)
                # Three newer releases installed and the pointer on the newest,
                # so 1.0.0 falls outside the three prune_releases retains.
                for filler in ('1.0.1', '1.0.2', '1.0.3'):
                    (home / 'releases' / filler / 'packaging').mkdir(parents=True)
                    (home / 'releases' / filler / 'packaging' / 'VERSION').write_text(
                        filler + '\n')
                (home / 'current').write_text('1.0.3\n')
                program = LAUNCHD.DEFAULT_PROGRAM
                LAUNCHD.reset(program=program, commands={
                    LABEL: [program, str(home / 'router_launch.py')],
                    UPDATE_LABEL: [
                        program,
                        str(home / 'releases' / '1.0.0' / 'packaging' / 'install.py'),
                        '--check-update', '--home', str(home)]})
                blob, latest = _craft_bundle('1.0.4')
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(install_mod.do_install(
                        args, _fetch=_static_fetch(latest, blob), _run=fake_run), 0)
            self.assertFalse((home / 'releases' / '1.0.1').is_dir(),
                             'the test needs prune_releases to have actually run')
            self.assertTrue((home / 'releases' / '1.0.0').is_dir(),
                            'the release launchd still names must survive prune')

    def test_a_missing_updater_is_bootstrapped(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            calls = []

            def fake_run(cmd, **kwargs):
                calls.append(list(cmd))
                return _ok_run(cmd, **kwargs)

            _patch_attrs(self, run=fake_run, self_test=lambda *a: None,
                         write_catalogue=_fake_write_catalogue,
                         wait_version=lambda *a, **k: {'status': 'ok'})
            LAUNCHD.reset(unloaded={LABEL, UPDATE_LABEL})
            env = {'HOME': str(Path(tmp) / 'fakehome'), 'OPENROUTER_API_KEY': 'k',
                   'ROUTER_NO_KEY_WINDOW': '1'}
            with mock.patch.dict(os.environ, env):
                args = install_mod.build_parser().parse_args(
                    ['--feed', 'file:///latest.json', '--home', str(home)])
                blob, latest = _craft_bundle('1.0.0')
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(install_mod.do_install(
                        args, _fetch=_static_fetch(latest, blob), _run=fake_run), 0)
            self.assertEqual(
                LAUNCHD.commands[UPDATE_LABEL],
                [LAUNCHD.DEFAULT_PROGRAM, str(home / 'update_launch.py')])


class InstallLockTests(unittest.TestCase):
    """One writer per router home, on every platform.

    The scheduled pass and a manual run fire independently and both swap
    `current`, rewrite both plists and reload the same service. This lock used
    to exist only on the systemd path, so macOS had nothing serialising them.
    """

    def test_a_second_writer_is_refused_while_one_holds_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            with install_mod.install_lock(home) as first:
                self.assertTrue(first)
                # A separate descriptor, which is what a second process has:
                # flock does not recurse across open file descriptions.
                with install_mod.install_lock(home) as second:
                    self.assertFalse(second, 'a second writer must be refused')
            with install_mod.install_lock(home) as again:
                self.assertTrue(again, 'the lock must be released on exit')

    def test_a_mutating_run_defers_while_another_holds_the_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            with install_mod.install_lock(home):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = install_mod.main(['--home', str(home),
                                           '--feed', 'file:///latest.json'])
            self.assertEqual(rc, 0)
            self.assertIn('another router operation', buf.getvalue())

    def test_update_never_takes_the_lock_its_own_child_needs(self):
        # The scheduled parent must stay unlocked: the installer it spawns is
        # a fresh main() that takes the lock itself. A parent holding it would
        # make the child defer, the parent report "did not activate", and
        # every automatic update no-op forever with a clean exit status.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir(parents=True)
            (home / 'mixed-router-state.json').write_text(
                json.dumps({'port': 1, 'token': 'x'}))
            blob, latest = _craft_bundle('9.9.9')
            bundle = Path(tmp) / 'bundle.tar.gz'
            bundle.write_bytes(blob)
            feed_doc = Path(tmp) / 'latest.json'
            feed_doc.write_text(json.dumps(
                dict(latest, url='file://' + str(bundle),
                     sha256=hashlib.sha256(blob).hexdigest())))
            child = []

            def fake_run(cmd, **kwargs):
                child.append(list(cmd))
                return _ok_run(cmd, **kwargs)

            _patch_attrs(self, run=fake_run)
            buf = io.StringIO()
            with install_mod.install_lock(home) as held:
                self.assertTrue(held, 'the test must actually hold the lock')
                with mock.patch('time.sleep'), contextlib.redirect_stdout(buf), \
                        mock.patch.dict(os.environ, {'ROUTER_LIVE_RUN': '1'}):  # deliberate scratch-home run
                    rc = install_mod.main(
                        ['--update', '--home', str(home),
                         '--feed', 'file://' + str(feed_doc)])
            self.assertEqual(rc, 0)
            self.assertNotIn('another router operation', buf.getvalue(),
                             'a scheduled update must not be blocked by the lock')
            self.assertTrue([c for c in child if '--home' in c],
                            'the check must still reach the child installer')

    def test_the_lock_is_released_when_the_holder_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            with self.assertRaises(RuntimeError):
                with install_mod.install_lock(home):
                    raise RuntimeError('installer died')
            with install_mod.install_lock(home) as held:
                self.assertTrue(held, 'a crashed installer must not strand the lock')


class UpdateBackoffTests(unittest.TestCase):
    """A bad release must not restart the service on every poll forever.

    The incident ran this loop for hours: each pass re-fetched the same
    version, swapped the pointer, waited out the 150s health deadline and
    rolled back, leaving the router down for most of every cycle.
    """

    def _home(self, tmp):
        home = Path(tmp) / 'home'
        home.mkdir(parents=True)
        (home / 'mixed-router-state.json').write_text(
            json.dumps({'port': 1, 'token': 'x'}))
        return home

    def _check(self, home, blob, latest, fetches, run=None, child_rc=1, _announce=None):
        def fake_run(cmd, **kwargs):
            if cmd[:1] == ['launchctl']:
                return _ok_run(cmd, **kwargs)
            return SimpleNamespace(returncode=child_rc, stdout='', stderr='boom')

        def fetch(url):
            fetches.append(url)
            return blob

        _patch_attrs(self, run=run or fake_run)
        args = install_mod.build_parser().parse_args(
            ['--feed', 'file:///latest.json', '--home', str(home)])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                rc = install_mod.do_update(
                    args, _fetch=fetch,
                    _read_feed=lambda f, e: (200, json.dumps(latest).encode(), 'etag-1'),
                    _sleep=lambda s: None, _announce=_announce)
            except SystemExit as exc:
                rc = exc.code
        return rc, buf.getvalue()

    def test_a_repeatedly_failing_version_is_parked(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = self._home(tmp)
            blob, latest = _craft_bundle('9.9.9')
            fetches, out = [], ''
            for attempt in range(install_mod.MAX_VERSION_FAILURES):
                rc, out = self._check(home, blob, latest, fetches, child_rc=1)
                self.assertEqual(rc, 1, f'attempt {attempt} must report the failure')
            # file:// with no key configured stays operator-trusted: one
            # doc read per attempt, no sidecar.
            self.assertEqual(len(fetches), install_mod.MAX_VERSION_FAILURES)
            self.assertIn('parking 9.9.9', out)
            rc, out = self._check(home, blob, latest, fetches, child_rc=1)
            self.assertEqual(rc, 0, 'a parked version is skipped, not an error')
            self.assertEqual(len(fetches), install_mod.MAX_VERSION_FAILURES,
                             'a parked version must not be downloaded again')
            self.assertIn('skipping 9.9.9', out)

    def test_the_failure_count_is_per_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = self._home(tmp)
            for _ in range(install_mod.MAX_VERSION_FAILURES):
                blob, latest = _craft_bundle('9.9.9')
                self._check(home, blob, latest, [], child_rc=1)
            # A different version is a different release: it gets its own
            # attempts, or one bad build would freeze the channel for good.
            fetches = []
            blob, latest = _craft_bundle('9.9.10')
            rc, out = self._check(home, blob, latest, fetches, child_rc=1)
            self.assertEqual(rc, 1)
            self.assertEqual(len(fetches), 1, 'a new version must still be tried')
            self.assertNotIn('skipping', out)

    def test_a_success_clears_the_count_so_a_later_failure_starts_over(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = self._home(tmp)
            blob, latest = _craft_bundle('9.9.9')
            self._check(home, blob, latest, [], child_rc=1)
            self.assertEqual(install_mod._update_failures(home), {'9.9.9': 1})
            install_mod._clear_update_failures(home, '9.9.9')
            self.assertEqual(install_mod._update_failures(home), {})
            state = json.loads((home / 'mixed-router-state.json').read_text())
            self.assertEqual(state['port'], 1, 'unrelated state must survive')

    def _landing_run(self, home, serving):
        """A child that swaps the pointer, stages its notice, then fails."""
        def fake_run(cmd, **kwargs):
            if cmd[:1] == ['launchctl']:
                return _ok_run(cmd, **kwargs)
            (home / 'releases' / '9.9.9').mkdir()
            (home / 'current').write_text('9.9.9')
            (home / 'update-notice.json').write_text(
                json.dumps({'version': '9.9.9'}))
            return SimpleNamespace(returncode=1, stdout='',
                                   stderr='config block was edited by hand')

        _patch_attrs(self, wait_version=lambda *a, **k: serving)
        return fake_run

    def test_a_landed_update_that_failed_a_later_step_is_recorded_not_parked(self):
        # A refused Codex settings merge exits non-zero after the swap and a
        # healthy restart. That release keeps serving: record the pass, leave
        # the notice to the notice module, and still report the failure.
        with tempfile.TemporaryDirectory() as tmp:
            home = self._home(tmp)
            (home / 'releases' / '9.9.8').mkdir(parents=True)
            (home / 'current').write_text('9.9.8')
            blob, latest = _craft_bundle('9.9.9')
            honest = install_mod._svc.notice.show_pending
            run = self._landing_run(home, serving=True)
            with mock.patch.object(install_mod._svc.notice, 'show_pending',
                                   wraps=honest) as shown, \
                    mock.patch.dict(os.environ, {'ROUTER_NO_NOTICE': '1'}):
                rc, out = self._check(home, blob, latest, [], run=run,
                                      _announce=lambda _home, _state: None)
            self.assertEqual(rc, 1, 'the failure must stay visible')
            self.assertEqual(shown.call_count, 1, 'the notice module is asked')
            self.assertEqual(install_mod._update_failures(home), {},
                             'a release that landed must not be parked')
            notice = json.loads((home / 'update-notice.json').read_text())
            self.assertNotIn('shown', notice, 'a silenced dialog is not a shown one')
            self.assertIn('9.9.9', (home / 'logs' / 'update.log').read_text())
            self.assertIn('exited 1 after the swap', out)

    def test_a_pointer_without_a_serving_router_is_parked(self):
        # The pointer alone is not proof: a killed rollback can leave it
        # naming a release the router never served.
        with tempfile.TemporaryDirectory() as tmp:
            home = self._home(tmp)
            (home / 'releases' / '9.9.8').mkdir(parents=True)
            (home / 'current').write_text('9.9.8')
            blob, latest = _craft_bundle('9.9.9')
            run = self._landing_run(home, serving=False)
            rc, out = self._check(home, blob, latest, [], run=run)
            self.assertEqual(rc, 1)
            self.assertEqual(install_mod._update_failures(home), {'9.9.9': 1})
            self.assertFalse((home / 'logs' / 'update.log').exists())
            self.assertNotIn('after the swap', out)

    def test_the_announce_runs_after_the_update_log_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = self._home(tmp)
            blob, latest = _craft_bundle('9.9.9')
            seen = {}

            def fake_run(cmd, **kwargs):
                if cmd[:1] == ['launchctl']:
                    return _ok_run(cmd, **kwargs)
                (home / 'releases' / '9.9.9').mkdir(parents=True)
                (home / 'current').write_text('9.9.9')
                return SimpleNamespace(returncode=0, stdout='', stderr='')

            def fake_announce(_home, state):
                seen['log'] = (home / 'logs' / 'update.log').read_text()
                seen['state'] = state

            rc, _out = self._check(home, blob, latest, [], run=fake_run,
                                   child_rc=0, _announce=fake_announce)
            self.assertEqual(rc, 0)
            self.assertIn('9.9.9', seen['log'])
            self.assertEqual(seen['state']['port'], 1)


if __name__ == '__main__':
    unittest.main()
