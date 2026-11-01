"""Execute the Windows snapshot against CIM fixtures, before JSON reaches Python."""
import json
import shutil
import subprocess
import unittest
from types import SimpleNamespace
from unittest import mock

from tests.test_claude_desktop_platform import platform

POWERSHELL = shutil.which('powershell') or shutil.which('pwsh')
USER = 'S-1-5-21-100-200-300-1001'
IDENTITY = dict(root=r'C:\Apps\Codex', exe=r'C:\Apps\Codex\app\Codex.exe', user=USER)
MOCKS = r'''
$fixture = ConvertFrom-Json '%s'
foreach($row in $fixture){$row.CreationDate = [datetime]$row.CreationDate}
function Get-Process { param($Id) [pscustomobject]@{SessionId=1} }
function Get-CimInstance {
    param($ClassName,$Filter,$ErrorAction)
    if($Filter){
        $number=[int]($Filter -replace '.*=','')
        @($fixture | Where-Object {$_.ProcessId -eq $number -and -not $_.gone})
    }else{@($fixture)}
}
function Invoke-CimMethod {
    param($InputObject,$MethodName)
    if($InputObject.gone){throw 'fixture process vanished'}
    [pscustomobject]@{ReturnValue=$InputObject.owner_result;Sid=$InputObject.owner}
}
'''


def row(pid, exe, *, parent=1, name=None, denied=False, gone=False):
    return dict(ProcessId=pid, ParentProcessId=parent, SessionId=1,
        Name=name or exe.rsplit('\\', 1)[-1], ExecutablePath=exe,
        CreationDate='2026-10-22T00:00:00Z', owner=USER,
        owner_result=2 if denied else 0, gone=gone)


@unittest.skipUnless(POWERSHELL, 'PowerShell executes the CIM fixture')
class WindowsSnapshotTests(unittest.TestCase):
    def snapshot(self, rows, *, tracked=None):
        def run(command, **kwargs):
            self.assertEqual(kwargs.pop('creationflags'), 0x08000000)
            script = MOCKS % json.dumps(rows).replace("'", "''") + command[-1].replace(
                '[Security.Principal.WindowsIdentity]::GetCurrent().User.Value', "'%s'" % USER)
            return subprocess.run([POWERSHELL, '-NoProfile', '-NonInteractive',
                                   '-Command', script], **kwargs)
        if tracked is None:
            return platform._snapshot('win32', IDENTITY, run)
        return platform._snapshot('win32', IDENTITY, run, tracked=tracked)

    def test_protected_unrelated_processes_are_not_owner_queried(self):
        rows = [row(n, 'C:\\Windows\\System32\\' + name, denied=True)
                for n, name in enumerate(('csrss.exe', 'winlogon.exe', 'dwm.exe', 'fontdrvhost.exe'), 1)]
        rows += [row(10, IDENTITY['exe']), row(11, r'C:\tools\writer.exe', parent=10)]
        self.assertEqual(set(self.snapshot(rows)), {10, 11})

    def test_only_confirmed_vanished_process_is_ignored(self):
        self.assertEqual(self.snapshot([row(10, IDENTITY['exe'], gone=True)]), {})
        with self.assertRaises(OSError):
            self.snapshot([row(10, IDENTITY['exe'], denied=True)])

    def test_reparented_tracked_child_is_still_owner_checked(self):
        child = row(11, r'C:\tools\writer.exe')
        self.assertEqual(set(self.snapshot([child], tracked={11})), {11})
        with self.assertRaises(OSError):
            self.snapshot([dict(child, owner_result=2)], tracked={11})

    def test_named_writer_outside_package_still_refuses_when_unreadable(self):
        with self.assertRaises(OSError):
            self.snapshot([row(10, r'C:\other\Codex.exe', denied=True)])
        rows = self.snapshot([row(10, r'C:\old-package\Codex.exe')])
        with self.assertRaisesRegex(OSError, 'unverified'):
            platform._writers(rows, IDENTITY, {}, 'win32', ())

    def test_package_prefix_does_not_include_a_sibling_folder(self):
        self.assertEqual(self.snapshot([row(10, r'C:\Apps\Codex-other\helper.exe', denied=True)]), {})


class WindowsIdentityBudgetTests(unittest.TestCase):
    def test_post_quit_probe_failure_reopens_both_clients_but_pre_quit_failure_does_not(self):
        failed = platform._windows_identity.QueryError('process_snapshot', 'timeout', elapsed_ms=5000)
        rows = {10: dict(pid=10, parent=1, user=USER, born='fixture', exe=IDENTITY['exe'])}
        for app in (platform.CLAUDE, platform.App('com.openai.codex', ())):
            for snapshots, expected in (([rows, failed], 1), ([failed], 0)):
                with self.subTest(app=app.bundle_id, post_quit=bool(expected)), \
                        mock.patch.object(platform, '_checked_identity', return_value=IDENTITY), \
                        mock.patch.object(platform, '_snapshot', side_effect=snapshots), \
                        mock.patch.object(platform, '_run', return_value=SimpleNamespace(returncode=0)), \
                        mock.patch.object(platform, 'open_app') as reopen:
                    with self.assertRaises(OSError) as error:
                        platform.request_stop('win32', timeout=0, app=app, identity=IDENTITY)
                    self.assertIs(error.exception, failed)
                    self.assertEqual(reopen.call_count, expected)
                    if expected:
                        self.assertEqual(reopen.call_args.kwargs['identity'], IDENTITY)

    def test_identity_allows_a_slow_store_query(self):
        run = mock.Mock(return_value=SimpleNamespace(returncode=0,
            stdout=json.dumps(dict(IDENTITY, app='Codex!App')), stderr=''))
        self.assertEqual(platform.app_identity('win32', run, platform.CLAUDE),
                         dict(IDENTITY, app='Codex!App'))
        self.assertEqual(run.call_args.kwargs['timeout'], 30)
        self.assertEqual(run.call_args.kwargs['encoding'], 'utf-8')

    def test_identity_timeout_retains_only_safe_failure_facts(self):
        run = mock.Mock(side_effect=subprocess.TimeoutExpired('private command', 30,
                                                             stderr='private path'))
        with self.assertRaises(OSError) as error:
            platform.app_identity('win32', run, platform.CLAUDE)
        facts = platform.error_facts(error.exception, 'app_identity')
        self.assertEqual(facts['reason'], 'timeout')
        self.assertEqual(facts['operation'], 'app_identity')
        self.assertNotIn('private', json.dumps(facts))

    def test_identity_exit_and_invalid_output_keep_the_failure_class(self):
        for answer, reason in ((SimpleNamespace(returncode=1, stderr='private details',
                stdout='{"scg_error":"manifest","hresult":-1}'), 'query_exit'),
                (SimpleNamespace(returncode=0, stdout='not JSON', stderr=''), 'invalid_output')):
            with self.subTest(reason=reason), self.assertRaises(OSError) as error:
                platform.app_identity('win32', mock.Mock(return_value=answer),
                                      platform.CLAUDE)
            facts = platform.error_facts(error.exception, 'app_identity')
            self.assertEqual(facts['reason'], reason)
            self.assertEqual(facts['exit_code'], answer.returncode)
            self.assertNotIn('private', json.dumps(facts))


if __name__ == '__main__':
    unittest.main()
