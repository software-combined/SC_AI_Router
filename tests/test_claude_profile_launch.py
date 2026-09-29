"""Installed start/switch ordering for Claude profile session sharing."""
import importlib.util
import json
import os
import runpy
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import claude_profile_sync_fixtures as fixtures
from tests.install_fixtures import install_mod
from tests.test_claude_desktop_config import _profile, _state, desktop_config


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'desktop_switch_launch_test', ROOT / 'packaging' / 'claude_desktop_switch.py')
switcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(switcher)


class FakePlatform:
    def __init__(self, events, running=False, confirm=True, stopped=True):
        self.events = events
        self.running = running
        self.confirm_result = confirm
        self.stopped_result = stopped

    def is_running(self, _platform, run=None):
        return self.running

    def confirm(self, _message, _platform, run=None):
        self.events.append('confirm')
        return self.confirm_result

    def request_stop(self, _platform, run=None):
        self.events.append('stop')
        return self.stopped_result

    def open_app(self, _platform, run=None):
        self.events.append('open')

    def show_message(self, _message, _platform, run=None):
        pass


class ProfileLaunchTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.home = self.root / 'router'
        self.home.mkdir()
        self.profile = _profile(self.root, {'keep': 'gateway'})
        self.state = _state()
        (self.home / 'mixed-router-state.json').write_text(json.dumps(self.state))
        desktop_config.attach(self.home, self.state, install_mod._codex_config,
                              data_dir_override=self.profile)
        self.config = self.profile / 'claude_desktop_config.json'
        self.config.write_text(json.dumps({
            'deploymentMode': '3p', 'keep': {'nested': True}}))
        self.events = []
        self.env = fixtures.isolated_env(self.root)
        self.addCleanup(mock.patch.stopall)
        mock.patch.dict(os.environ, self.env).start()
        self.initialized = mock.patch.object(switcher, '_initialized', return_value=True).start()

    def sync(self, _home, mode, _third, _env):
        self.events.append('sync:' + mode)
        return {'copied': 1, 'replaced': 0, 'unchanged': 0,
                'pending': 0, 'failed': 0, 'errors': []}

    def test_switch_syncs_old_mode_then_writes_mode_before_reopen(self):
        events = self.events
        platform_ops = FakePlatform(events)
        original_write = desktop_config.write_json

        def write(path, doc):
            events.append('mode')
            return original_write(path, doc)

        with mock.patch.object(switcher._desktop, 'write_json',
                               side_effect=write):
            self.assertEqual(switcher.switch(
                self.home, action='switch', policy_check=lambda: False,
                sync=self.sync, platform_ops=platform_ops), '1p')
        self.assertEqual(events, ['confirm', 'stop', 'sync:3p', 'mode', 'open'])
        self.assertEqual(json.loads(self.config.read_text())['deploymentMode'], '1p')

    def test_start_preserves_mode_and_opens_without_sync(self):
        for running in (False, True):
            with self.subTest(running=running), mock.patch.object(
                    switcher._desktop, 'write_json') as write:
                self.events.clear()
                self.assertEqual(switcher.switch(
                    self.home, action='start', policy_check=lambda: False,
                    sync=self.sync, platform_ops=FakePlatform(self.events, running=running)), '3p')
                self.assertEqual(self.events, ['open'])
                write.assert_not_called()
        self.assertEqual(json.loads(self.config.read_text())['deploymentMode'], '3p')

    def test_sync_failure_keeps_old_mode_and_does_not_reopen(self):
        platform_ops = FakePlatform(self.events)

        def failed_sync(_home, _mode, _third, _env):
            self.events.append('sync')
            return {'copied': 0, 'replaced': 0, 'unchanged': 0,
                    'pending': 0, 'failed': 1, 'errors': ['ValueError']}

        with mock.patch.object(switcher._desktop, 'write_json') as write:
            with self.assertRaisesRegex(switcher.SwitchError, 'not fully shared'):
                switcher.switch(
                    self.home, action='switch', policy_check=lambda: False,
                    sync=failed_sync, platform_ops=platform_ops)
        self.assertEqual(self.events, ['confirm', 'stop', 'sync'])
        write.assert_not_called()
        self.assertEqual(json.loads(self.config.read_text())['deploymentMode'],
                         '3p')

    def test_partial_pending_sync_prevents_mode_write_and_open(self):
        platform_ops = FakePlatform(self.events)

        def pending_sync(_home, mode, _third, _env):
            self.events.append('sync:' + mode)
            return {'copied': 0, 'replaced': 0, 'unchanged': 1,
                    'pending': 1, 'failed': 0, 'errors': []}

        with self.assertRaisesRegex(switcher.SwitchError, 'waiting for Claude setup'):
            switcher.switch(self.home, policy_check=lambda: False,
                            sync=pending_sync, platform_ops=platform_ops)
        self.assertEqual(self.events, ['confirm', 'stop', 'sync:3p'])
        self.assertEqual(json.loads(self.config.read_text())['deploymentMode'], '3p')

    def test_initialization_only_open_migrates_nothing(self):
        self.initialized.return_value = False
        sync = mock.Mock()
        self.assertEqual(switcher.switch(
            self.home, action='start', policy_check=lambda: False, sync=sync,
            platform_ops=FakePlatform(self.events)), '3p')
        sync.assert_not_called()
        self.assertEqual(self.events, ['open'])

    def test_missing_identity_with_saved_tasks_prevents_switch(self):
        self.initialized.return_value = False
        fixtures.record(self.profile, 'claude-code-sessions',
                        '87654321-4321-4567-8123-123456789abc',
                        'fedcbaab-4321-4567-8123-123456789abc', 'saved')
        with self.assertRaisesRegex(switcher.SwitchError, 'setup'):
            switcher.switch(self.home, policy_check=lambda: False,
                            sync=self.sync, platform_ops=FakePlatform(self.events))
        self.assertEqual(json.loads(self.config.read_text())['deploymentMode'], '3p')
        self.assertNotIn('open', self.events)

    def test_router_start_does_not_share_tasks(self):
        release = self.home / 'releases/fake'
        (release / 'ai_router').mkdir(parents=True)
        (release / 'packaging').mkdir()
        (self.home / 'current').write_text('fake')
        launch = self.home / 'router_launch.py'
        shutil.copyfile(ROOT / 'packaging/router_launch.py', launch)
        helper = release / 'packaging/claude_desktop_switch.py'
        helper.write_text('def startup_sync(home):\n    (home / "unexpected-sync").touch()\n')
        with mock.patch.object(runpy, 'run_module') as serve, \
                mock.patch.object(sys, 'path', sys.path[:]):
            runpy.run_path(str(launch), run_name='__main__')
            serve.assert_called_once_with('ai_router', run_name='__main__')
            self.assertFalse((self.home / 'unexpected-sync').exists())

    def test_installed_helper_round_trips_real_synthetic_profiles(self):
        first = fixtures.profile(
            desktop_config.profile_root(self.env), 'Claude', '12345678-1234-4567-8123-123456789abc', 'abcdefab-1234-4567-8123-123456789abc')
        third = self.profile
        (third / 'config.json').write_text(json.dumps({
            'lastKnownAccountUuid': '87654321-4321-4567-8123-123456789abc',
            'lastKnownOrganizationUuid': 'fedcbaab-4321-4567-8123-123456789abc',
        }))
        fixtures.third_party_identity(third, '87654321-4321-4567-8123-123456789abc',
                                      'fedcbaab-4321-4567-8123-123456789abc')
        for profile_path in (first, third):
            for store in fixtures.STORES:
                account, org = ('12345678-1234-4567-8123-123456789abc', 'abcdefab-1234-4567-8123-123456789abc')
                if profile_path == third:
                    account, org = '87654321-4321-4567-8123-123456789abc', 'fedcbaab-4321-4567-8123-123456789abc'
                fixtures.namespace(profile_path, store, account, org)
            fixtures.write_sentinels(profile_path)
        before_creds = {
            path: fixtures.fingerprint(path / 'creds')
            for path in (first, third)
        }
        shared = {}
        for profile_path, title, result, account, org in (
                (third, 'third', 'third-result', '87654321-4321-4567-8123-123456789abc',
                 'fedcbaab-4321-4567-8123-123456789abc'),
                (first, 'first', 'first-result', '12345678-1234-4567-8123-123456789abc',
                 'abcdefab-1234-4567-8123-123456789abc')):
            shared[profile_path] = fixtures.record(
                profile_path, 'claude-code-sessions', account, org,
                'shared', filename=('local_third.json' if profile_path == third
                                    else 'local_first.json'),
                title=title,
                cli='cli-shared', transcript='synthetic history',
                bundle_files={'outputs/result.txt': result,
                              'outputs/' + title + '.txt': title})
        cowork = 'local-agent-mode-sessions'
        fixtures.record(first, cowork, '12345678-1234-4567-8123-123456789abc',
                        'abcdefab-1234-4567-8123-123456789abc', 'first-only')
        fixtures.record(third, cowork, '87654321-4321-4567-8123-123456789abc',
                        'fedcbaab-4321-4567-8123-123456789abc', 'third-only')
        cowork_before = [fixtures.fingerprint(path / cowork) for path in (first, third)]
        release = self.home / 'releases/fixture/packaging'
        inventory = fixtures.load_helper('release').bundle_files(ROOT)
        archive = self.root / 'release.tar'
        with tarfile.open(archive, 'w') as bundle:
            for relative in inventory:
                bundle.add(ROOT / relative, arcname=relative, recursive=False)
        with tarfile.open(archive) as bundle:
            bundle.extractall(release.parent, filter='data')
        (self.home / 'current').write_text('fixture', encoding='utf-8')
        launch = self.home / 'claude_profile_launch.py'
        shutil.copyfile(release / launch.name, launch)
        # Native lifecycle, managed policy and subscription identity are simulated.
        with (release / 'claude_desktop_platform.py').open('a', encoding='utf-8') as out:
            out.write('\ndef policy_disabled(*a, **k): return False\n'
                      'def is_running(*a, **k): return False\n'
                      'def confirm(*a, **k): return True\n'
                      'def request_stop(*a, **k): return True\n'
                      'def open_app(*a, **k): return None\n'
                      'def show_message(*a, **k): return None\n')
        with (release / 'claude_desktop_policy.py').open('a', encoding='utf-8') as out:
            out.write('\ndef managed_connection(*a, **k): return False\n')
        fixtures.simulate_subscription_identity(release / 'claude_profile_identity.py')

        def dispatch(action, mode, code=0):
            answer = subprocess.run([sys.executable, str(launch), '--home', str(self.home),
                                     '--action', action], capture_output=True, text=True,
                                    env=dict(os.environ), timeout=20)
            self.assertEqual(answer.returncode, code, answer.stderr)
            self.assertEqual(json.loads(self.config.read_text())['deploymentMode'], mode)

        dispatch('switch', '1p')
        with fixtures.sync._service.install_lock(third, '.claude-profile-sync.lock') as locked:
            self.assertTrue(locked)
            before_busy = fixtures.fingerprint(first), fixtures.fingerprint(third)
            dispatch('switch', '1p', code=1)
            self.assertEqual((fixtures.fingerprint(first), fixtures.fingerprint(third)), before_busy)
        # Cowork tasks are not shared in the beta and stay exactly as they were.
        self.assertEqual([fixtures.fingerprint(path / cowork) for path in (first, third)],
                         cowork_before)
        for profile_path in (first, third):
            paths = sync_groups(profile_path / 'claude-code-sessions').get('shared', [])
            self.assertEqual(len(paths), 1, profile_path)
            shared_path = paths[0]
            self.assertEqual(
                json.loads(shared_path.read_text())['title'], 'third')
            self.assertEqual(json.loads(shared_path.read_text())['cliSessionId'], 'cli-shared')
            self.assertEqual(
                (shared_path.with_suffix('') / 'outputs' /
                 'result.txt').read_text(), 'third-result')
            for name in ('first', 'third'):
                self.assertEqual((shared_path.with_suffix('') / 'outputs' / (name + '.txt')).read_text(), name)
        for profile_path in (first, third):
            self.assertEqual(
                fixtures.fingerprint(profile_path / 'creds'),
                before_creds[profile_path])

        first_shared = shared[first]
        doc = json.loads(first_shared.read_text())
        doc['title'] = 'first-continued'
        first_shared.write_text(json.dumps(doc))
        (first_shared.with_suffix('') / 'outputs' /
         'result.txt').write_text('first-continued')
        dispatch('switch', '3p')
        for profile_path in (first, third):
            path = sync_groups(profile_path / 'claude-code-sessions')['shared'][0]
            self.assertEqual(json.loads(path.read_text())['title'], 'first-continued')
        after_second = fixtures.fingerprint(self.root)
        dispatch('start', '3p')
        self.assertEqual(fixtures.fingerprint(self.root), after_second)

def sync_groups(store):
    groups = {}
    for path in sorted(Path(store).glob('*/*/local_*.json')):
        identifier = json.loads(path.read_text())['sessionId']
        groups.setdefault(identifier, []).append(path)
    return groups
