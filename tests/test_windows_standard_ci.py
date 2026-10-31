"""CI cleanup uses only retained handles verified to belong to its new account."""
from contextlib import contextmanager
import importlib.util
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
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


class ProfileBootstrapTests(unittest.TestCase):
    def test_profile_precedes_installer_imports_in_a_fresh_process_without_home(self):
        script = '''
import importlib.util, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('ci_child', sys.argv[1])
owner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(owner)
class ProfileReached(Exception): pass
def profile(): raise ProfileReached()
def missing_home(): raise RuntimeError('Home is not initialized')
owner.profile = profile
Path.home = missing_home
try: owner.run('synthetic-sid', 'unused-report')
except ProfileReached: print('profile-first')
'''
        result = subprocess.run([sys.executable, '-I', '-c', script, str(Path(tool().__file__))],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'profile-first')


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
    def shell(self):
        shell = shutil.which(os.environ.get('SCG_TEST_WINDOWS_SHELL', 'pwsh'))
        self.assertIsNotNone(shell)
        return shell

    def inventory(self):
        command = ('@{users=@(Get-LocalUser | Where-Object Name -Like "scgci*" | '
                   'ForEach-Object {$_.SID.Value});profiles=@(Get-CimInstance Win32_UserProfile | '
                   'Where-Object LocalPath -Match "scgci" | ForEach-Object {$_.SID});'
                   'directories=@(Get-ChildItem -Directory $env:RUNNER_TEMP -Filter "scgci*" | '
                   'ForEach-Object {$_.Name})} | ConvertTo-Json -Compress')
        result = subprocess.run([self.shell(), '-NoProfile', '-Command', command],
                                capture_output=True, text=True, timeout=30, check=True)
        return json.loads(result.stdout)

    def test_bad_executable_still_removes_new_account_profile_and_temporary_directory(self):
        shell = self.shell()
        script = Path(__file__).resolve().parents[1] / 'tools/run_windows_standard.ps1'
        before = self.inventory()
        with tempfile.TemporaryDirectory() as temporary:
            invalid = Path(temporary) / 'invalid.exe'
            invalid.write_bytes(b'not a Windows executable')
            result = subprocess.run([shell, '-NoProfile', '-File', str(script), '-Python', str(invalid)],
                                    capture_output=True, text=True, timeout=90)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.inventory(), before)

    def test_selected_failures_and_timeout_clean_up_real_standard_user_children(self):
        source = Path(__file__).resolve().parents[1]
        before = self.inventory()
        # Only the copied launcher uses this synthetic child; production has no injection switch.
        for selection, mode in (('core', 'success'), ('core', 'failure'),
                                ('native-runtime', 'failure'), ('native-shortcuts', 'timeout')):
            with self.subTest(selection=selection, mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / 'tools').mkdir()
                script = root / 'tools/run_windows_standard.ps1'
                shutil.copyfile(source / 'tools/run_windows_standard.ps1', script)
                (root / 'tools/windows_standard.py').write_text('''
import argparse, ctypes, importlib.util, json, pathlib, subprocess, sys, time
parser = argparse.ArgumentParser()
parser.add_argument('--sid'); parser.add_argument('--report'); parser.add_argument('--suite')
parser.add_argument('--cleanup', action='store_true')
args = parser.parse_args()
if args.cleanup:
    sys.path.insert(0, ROOT)
    spec = importlib.util.spec_from_file_location('real_standard', pathlib.Path(ROOT) / 'tools/windows_standard.py')
    owner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(owner)
    owner.cleanup(args.sid)
    sys.exit(0)
sid = subprocess.check_output(['powershell.exe', '-NoProfile', '-Command',
    '[Security.Principal.WindowsIdentity]::GetCurrent().User.Value'], text=True).strip()
assert sid == args.sid and not ctypes.windll.shell32.IsUserAnAdmin()
assert args.suite == SELECTION
if MODE == 'timeout':
    code = 'import pathlib,sys,time\\nwhile True:\\n pathlib.Path(sys.argv[1]).write_text(str(time.monotonic())); time.sleep(0.1)'
    subprocess.Popen([sys.executable, '-c', code, str(pathlib.Path(args.report).parent / 'heartbeat')])
    time.sleep(60)
success = MODE == 'success'
status = 0 if success else 1
pathlib.Path(args.report).write_text(json.dumps(dict(sid=sid, elevated=False, status=status,
    suites=[dict(suite=args.suite, tests=1, skipped=0, success=success)])))
sys.exit(status)
'''.replace('ROOT', repr(str(source))).replace('SELECTION', repr(selection)).replace('MODE', repr(mode)))
                evidence = root / 'evidence.json'
                result = subprocess.run([self.shell(), '-NoProfile', '-File', str(script),
                                         '-Python', sys.executable, '-Suite', selection,
                                         '-EvidencePath', str(evidence),
                                         '-TimeoutSeconds', '5' if mode == 'timeout' else '30'],
                                        capture_output=True, text=True, timeout=90)
                self.assertTrue(evidence.is_file(), result.stdout + result.stderr)
                recorded = json.loads(evidence.read_text(encoding='utf-8'))
                self.assertEqual(recorded['selection'], selection)
                self.assertEqual(recorded['identity_verified'], mode == 'success')
                if mode == 'success':
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                else:
                    self.assertNotEqual(result.returncode, 0)
                    expected = 'timed out' if mode == 'timeout' else 'does not match its process'
                    self.assertIn(expected, result.stdout + result.stderr)
                    if mode == 'timeout':
                        self.assertRegex(result.stdout, r'windows_standard_cleanup ended=[1-9]')
                self.assertEqual(self.inventory(), before)


if __name__ == '__main__':
    unittest.main()
