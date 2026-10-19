"""Store and unpackaged profile paths use current-user package registration."""
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from tests.claude_profile_sync_fixtures import load_helper

desktop = load_helper('claude_desktop_config')
windows = desktop._windows


class WindowsProfileTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.local, self.roaming = self.root / 'local', self.root / 'roaming'
        (self.local / 'Packages').mkdir(parents=True)
        self.env = {'APPDATA': str(self.roaming), 'LOCALAPPDATA': str(self.local)}
        self.system_root = self.root / 'Windows'
        system = mock.patch.dict(windows.os.environ, {'SystemRoot': str(self.system_root)})
        system.start()
        self.addCleanup(system.stop)

    def run_with(self, families, returncode=0):
        return mock.Mock(return_value=SimpleNamespace(
            returncode=returncode, stdout=json.dumps(families)))

    def test_store_subscription_root_and_gateway_root_remain_separate(self):
        run = self.run_with(['Claude_testpublisher'])
        with mock.patch.object(windows.subprocess, 'run', run):
            self.assertEqual(desktop.profile_root(self.env, 'win32'),
                             self.local / 'Packages/Claude_testpublisher/LocalCache/Roaming')
            self.assertEqual(desktop.user_data_dir(self.env, 'win32'), self.local / 'Claude-3p')
        self.assertEqual(run.call_count, 1)
        argv = run.call_args.args[0]
        self.assertEqual(argv[0], str(self.system_root / 'System32/WindowsPowerShell/v1.0/powershell.exe'))
        self.assertIn('Get-AppxPackage -Name Claude', argv[-1])
        self.assertNotIn('-AllUsers', argv[-1])
        self.assertEqual(run.call_args.kwargs['timeout'], 10)

    def test_no_registered_store_package_keeps_the_ordinary_roaming_root(self):
        self.assertEqual(windows.claude_roaming_root(self.roaming, self.local,
                                                   self.run_with([])), self.roaming)

    def test_missing_package_directory_needs_no_native_query(self):
        run = mock.Mock(side_effect=AssertionError('unnecessary query'))
        self.assertEqual(windows.claude_roaming_root(self.roaming, None, run), self.roaming)
        self.assertEqual(windows.claude_roaming_root(self.roaming, self.root / 'missing', run),
                         self.roaming)
        run.assert_not_called()

    def test_missing_or_relative_system_root_never_searches_the_project_for_powershell(self):
        run = mock.Mock(side_effect=AssertionError('unsafe executable lookup'))
        for system_root in ('', 'relative-windows'):
            with self.subTest(system_root=system_root), \
                    mock.patch.dict(windows.os.environ, {'SystemRoot': system_root}), \
                    self.assertRaises(OSError):
                windows.claude_roaming_root(self.roaming, self.local, run)
        run.assert_not_called()

    def test_ambiguous_unreadable_and_path_shaped_identities_fail_closed(self):
        for families, status in [(['Claude_one', 'Claude_two'], 0),
                                  (['../other'], 0), (['Claude_one/other'], 0),
                                  ({'name': 'Claude_one'}, 0), ([], 1)]:
            with self.subTest(families=families, status=status), self.assertRaises(OSError):
                windows.claude_roaming_root(self.roaming, self.local,
                                           self.run_with(families, status))
        with self.assertRaises(OSError):
            windows.claude_roaming_root(self.roaming, self.local,
                mock.Mock(side_effect=subprocess.TimeoutExpired('powershell', 10)))
