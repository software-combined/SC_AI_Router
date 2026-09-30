"""Linux retirement of the git plugin runner: its systemd units go with it.

The runner's scheduling.py installed a user timer and service on Linux. Moving
the runner aside while leaving them enabled would fail every day against a file
that no longer exists, so the timer is disabled and both units are preserved
beside the runner as `.migrated.<n>`, never deleted.
"""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_agent_skills import _Run, _which, skills


class LinuxRetirementTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / 'home'
        self.enterContext(patch.object(Path, 'home', return_value=self.home))
        self.enterContext(patch.dict('os.environ', {'XDG_CONFIG_HOME': ''}))
        self.units = self.home / '.config' / 'systemd' / 'user'
        self.units.mkdir(parents=True)
        for kind in ('timer', 'service'):
            (self.units / ('scg-agent-plugins-update.' + kind)).write_text('stale ' + kind)
        self.base = Path(tmp.name) / 'scg-agent-plugins'
        self.base.mkdir()
        runner = self.base / 'updater.py'
        runner.write_text('stale runner')
        original = skills.LEGACY_RUNNERS
        skills.LEGACY_RUNNERS = (hashlib.sha256(runner.read_bytes()).hexdigest(),)
        self.addCleanup(setattr, skills, 'LEGACY_RUNNERS', original)

    def test_the_timer_is_disabled_and_its_units_are_preserved(self):
        run = _Run()
        line = skills.retire_git_updater(base=self.base, run=run,
                                         which=_which({'systemctl'}))
        self.assertIn('retired', line)
        self.assertIn(['systemctl', '--user', 'disable', '--now',
                       'scg-agent-plugins-update.timer'], run.calls)
        self.assertIn(['systemctl', '--user', 'stop',
                       'scg-agent-plugins-update.service'], run.calls)
        self.assertIn(['systemctl', '--user', 'reset-failed',
                       'scg-agent-plugins-update.timer',
                       'scg-agent-plugins-update.service'], run.calls)
        self.assertIn(['systemctl', '--user', 'daemon-reload'], run.calls)
        for kind in ('timer', 'service'):
            unit = self.units / ('scg-agent-plugins-update.' + kind)
            self.assertFalse(unit.exists())
            self.assertEqual(unit.with_name(unit.name + '.migrated.0').read_text(),
                             'stale ' + kind)

    def test_units_an_earlier_router_left_beside_a_moved_runner_are_retired(self):
        # Routers before 1.0.2 moved the runner aside and left its timer on.
        (self.base / 'updater.py').rename(self.base / 'updater.py.migrated.0')
        run = _Run()
        line = skills.retire_git_updater(base=self.base, run=run,
                                         which=_which({'systemctl'}))
        self.assertIn('Linux schedule retired', line)
        self.assertIn(['systemctl', '--user', 'disable', '--now',
                       'scg-agent-plugins-update.timer'], run.calls)
        self.assertIn(['systemctl', '--user', 'stop',
                       'scg-agent-plugins-update.service'], run.calls)
        self.assertIn(['systemctl', '--user', 'reset-failed',
                       'scg-agent-plugins-update.timer',
                       'scg-agent-plugins-update.service'], run.calls)
        for kind in ('timer', 'service'):
            unit = self.units / ('scg-agent-plugins-update.' + kind)
            self.assertFalse(unit.exists())
            self.assertTrue(unit.with_name(unit.name + '.migrated.0').exists())
        self.assertEqual((self.base / 'updater.py.migrated.0').read_text(), 'stale runner')

    def test_units_beside_an_unrecognised_moved_runner_stay(self):
        moved = self.base / 'updater.py.migrated.0'
        (self.base / 'updater.py').rename(moved)
        moved.write_text('not ours')
        run = _Run()
        self.assertEqual(skills.retire_git_updater(base=self.base, run=run,
                                                   which=_which({'systemctl'})), '')
        self.assertEqual(run.calls, [])
        self.assertTrue((self.units / 'scg-agent-plugins-update.timer').exists())

    def test_recreated_units_never_overwrite_an_earlier_retirement(self):
        run = _Run()
        skills.retire_git_updater(base=self.base, run=run, which=_which({'systemctl'}))
        for kind in ('timer', 'service'):
            (self.units / ('scg-agent-plugins-update.' + kind)).write_text('recreated ' + kind)
        skills.retire_git_updater(base=self.base, run=run, which=_which({'systemctl'}))
        for kind in ('timer', 'service'):
            unit = self.units / ('scg-agent-plugins-update.' + kind)
            self.assertEqual(unit.with_name(unit.name + '.migrated.0').read_text(), 'stale ' + kind)
            self.assertEqual(unit.with_name(unit.name + '.migrated.1').read_text(), 'recreated ' + kind)
        self.assertEqual((self.base / 'updater.py.migrated.0').read_text(), 'stale runner')

    def test_a_failed_scheduler_operation_keeps_the_files_for_a_later_retry(self):
        for moved in (False, True):
            for action in ('disable', 'stop', 'reset-failed'):
                with self.subTest(already_moved=moved, failed=action):
                    base = self.base / ('moved' if moved else 'fresh') / action
                    base.mkdir(parents=True)
                    runner = base / 'updater.py'
                    runner.write_text('stale runner')
                    for kind in ('timer', 'service'):
                        (self.units / ('scg-agent-plugins-update.' + kind)).write_text('stale ' + kind)
                    if moved:
                        runner.rename(base / 'updater.py.migrated.0')
                    calls = _Run()

                    def fail(command, **kwargs):
                        result = calls(command, **kwargs)
                        result.returncode = int(command[2] == action)
                        return result

                    line = skills.retire_git_updater(base, run=fail, which=_which({'systemctl'}))
                    self.assertIn('pending', line)
                    self.assertEqual(runner.exists(), not moved)
                    for kind in ('timer', 'service'):
                        self.assertEqual((self.units / ('scg-agent-plugins-update.' + kind)).read_text(),
                                         'stale ' + kind)
                    line = skills.retire_git_updater(base, run=_Run(), which=_which({'systemctl'}))
                    self.assertIn('retired', line)
                    self.assertFalse((self.units / 'scg-agent-plugins-update.timer').exists())

    def test_an_unrecognised_runner_keeps_its_units(self):
        (self.base / 'updater.py').write_text('not ours')
        run = _Run()
        line = skills.retire_git_updater(base=self.base, run=run,
                                         which=_which({'systemctl'}))
        self.assertIn('unrecognised', line)
        self.assertEqual(run.calls, [])
        self.assertTrue((self.units / 'scg-agent-plugins-update.timer').exists())

    def test_an_unloaded_unit_reset_needs_a_complete_inactive_readback(self):
        for status, answer in ((0, 'inactive\ninactive\n'), (0, 'failed\ninactive\n'),
                               (0, 'inactive\n'), (1, 'inactive\ninactive\n')):
            with self.subTest(status=status, answer=answer):
                for kind in ('timer', 'service'):
                    (self.units / ('scg-agent-plugins-update.' + kind)).write_text('stale ' + kind)
                (self.base / 'updater.py').write_text('stale runner')
                calls = _Run()

                def reset_unloaded(command, **kwargs):
                    result = calls(command, **kwargs)
                    if command[2] == 'reset-failed':
                        result.returncode = 1
                    elif command[2] == 'show':
                        result.returncode, result.stdout = status, answer
                    return result

                line = skills.retire_git_updater(self.base, run=reset_unloaded,
                                                 which=_which({'systemctl'}))
                success = status == 0 and answer == 'inactive\ninactive\n'
                self.assertIn('retired' if success else 'pending', line)
                self.assertEqual((self.units / 'scg-agent-plugins-update.timer').exists(), not success)


if __name__ == '__main__':
    unittest.main()
