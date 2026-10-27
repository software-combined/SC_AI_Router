"""CI cleanup uses only retained handles verified to belong to its new account."""
from contextlib import contextmanager
import importlib.util
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from tests import test_native_setup


def tool():
    path = Path(__file__).resolve().parents[1] / 'tools/windows_standard.py'
    spec = importlib.util.spec_from_file_location('windows_standard_ci', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StandardUserCleanupTests(unittest.TestCase):
    def test_unrelated_and_reused_pids_are_never_ended(self):
        owner = tool()
        held, ended, closed = [], [], []
        @contextmanager
        def opened(pid, terminate=False):
            self.assertTrue(terminate)
            handle = object()
            held.append((pid, handle))
            try:
                yield handle
            finally:
                closed.append(handle)
        def user(handle=None):
            if handle is None:
                return 'runner-admin'
            return 'ci-user' if held[-1][0] == 11 else 'other-user'
        def end(handle):
            self.assertIs(handle, held[-1][1])
            self.assertNotIn(handle, closed)
            ended.append(handle)
        api = SimpleNamespace(user=user, opened=opened, end=end,
                              entries=lambda: [dict(pid=10), dict(pid=11)])
        with mock.patch.object(owner, 'os', SimpleNamespace(name='nt', environ={'GITHUB_ACTIONS': 'true'})), \
                mock.patch.object(test_native_setup, 'module', return_value=SimpleNamespace(Native=lambda: api)):
            owner.cleanup('ci-user')
            self.assertEqual(ended, [held[1][1]])
            self.assertEqual(len(closed), 2)
            # PID11 is reused by an unrelated account before the next handle opens.
            with mock.patch.object(api, 'user', return_value='other-user'):
                owner.cleanup('ci-user')
            self.assertEqual(len(ended), 1)
            self.assertEqual(len(closed), 4)

    def test_invoking_account_and_non_ci_hosts_refuse_before_process_actions(self):
        owner = tool()
        api = SimpleNamespace(user=lambda: 'runner-admin', entries=mock.Mock())
        with mock.patch.object(owner, 'os', SimpleNamespace(name='nt', environ={'GITHUB_ACTIONS': 'true'})), \
                mock.patch.object(test_native_setup, 'module', return_value=SimpleNamespace(Native=lambda: api)):
            with self.assertRaisesRegex(RuntimeError, 'invoking account'):
                owner.cleanup('runner-admin')
            api.entries.assert_not_called()
        with mock.patch.object(owner, 'os', SimpleNamespace(name='nt', environ={})), \
                mock.patch.object(test_native_setup, 'module') as load:
            with self.assertRaisesRegex(RuntimeError, 'disposable'):
                owner.cleanup('ci-user')
            load.assert_not_called()


@unittest.skipUnless(os.name == 'nt' and os.environ.get('GITHUB_ACTIONS') == 'true'
                     and ctypes.windll.shell32.IsUserAnAdmin(), 'disposable administrator Windows CI only')
class StandardUserLaunchFailureTests(unittest.TestCase):
    def test_bad_executable_still_removes_new_account_profile_and_temporary_directory(self):
        shell = shutil.which('pwsh')
        self.assertIsNotNone(shell)
        script = Path(__file__).resolve().parents[1] / 'tools/run_windows_standard.ps1'
        def inventory():
            command = ('@{users=@(Get-LocalUser | Where-Object Name -Like "scgci*" | '
                       'ForEach-Object {$_.SID.Value});profiles=@(Get-CimInstance Win32_UserProfile | '
                       'Where-Object LocalPath -Match "scgci" | ForEach-Object {$_.SID});'
                       'directories=@(Get-ChildItem -Directory $env:RUNNER_TEMP -Filter "scgci*" | '
                       'ForEach-Object {$_.Name})} | ConvertTo-Json -Compress')
            result = subprocess.run([shell, '-NoProfile', '-Command', command],
                                    capture_output=True, text=True, timeout=30, check=True)
            return json.loads(result.stdout)
        before = inventory()
        with tempfile.TemporaryDirectory() as temporary:
            invalid = Path(temporary) / 'invalid.exe'
            invalid.write_bytes(b'not a Windows executable')
            result = subprocess.run([shell, '-NoProfile', '-File', str(script), '-Python', str(invalid)],
                                    capture_output=True, text=True, timeout=90)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(inventory(), before)


if __name__ == '__main__':
    unittest.main()
