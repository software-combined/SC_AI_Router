"""Task failures retain safe provenance; uncertain instances still refuse."""
import json
import shutil
import subprocess
import unittest
from types import SimpleNamespace

from tests.test_windows_backend import backend, USER

SHELL = shutil.which('pwsh') or shutil.which('powershell')

# The external COM service and executable-version resource are fixture boundaries.
# The actual ownership, instance enumeration and result script run unchanged.
FIXTURE = r'''
$action = [pscustomobject]@{Type=0;Arguments='args';Path='C:\Python\python.exe'}
$actions = [pscustomobject]@{Count=1}
$actions | Add-Member ScriptMethod Item {param($index) return $script:action}
$definition = [pscustomobject]@{
    Principal=[pscustomobject]@{UserId='SID';LogonType=3;RunLevel=0}
    Actions=$actions;RegistrationInfo=[pscustomobject]@{Author='codex-router-installer'}
    Data='';Settings=[pscustomobject]@{StartWhenAvailable=$true};Triggers=@()
}
Add-Type 'using System.Runtime.InteropServices; public class AuditTaskInstance {
    public int ErrorCode, Calls, ExitAfter; public string InstanceGuid = "live-instance";
    public void Refresh() { Calls++; if (ErrorCode != 0 && Calls > ExitAfter)
        throw new COMException("PRIVATE PROPERTY", ErrorCode); }
}'
$live = [AuditTaskInstance]::new()
$ending = [AuditTaskInstance]::new()
$ending.ErrorCode = END_CODE
$taskFixture = [pscustomobject]@{Definition=$definition;State=3;Enabled=$true;Path='\Router'}
$taskFixture | Add-Member ScriptMethod GetInstances {param($flags) return @($script:live,$script:ending)}
$folderFixture = [pscustomobject]@{}
$folderFixture | Add-Member ScriptMethod GetTask {param($name) return $script:taskFixture}
$serviceFixture = [pscustomobject]@{}
$serviceFixture | Add-Member ScriptMethod Connect {}
$serviceFixture | Add-Member ScriptMethod GetFolder {param($name) return $script:folderFixture}
$serviceFixture | Add-Member ScriptMethod GetRunningTasks {
    throw [Runtime.InteropServices.COMException]::new('PRIVATE UNRELATED TASK',-2147024891)
}
'''


class TaskDiagnosticsTests(unittest.TestCase):
    @unittest.skipUnless(SHELL, 'requires executable PowerShell fixture')
    def test_active_owned_task_uses_cross_context_view_only_when_scoped_view_is_empty(self):
        script = FIXTURE.replace("'SID'", "'" + USER + "'").replace('END_CODE', '0')
        script = script.replace('return @($script:live,$script:ending)', 'return @()')
        script = script.replace('Definition=$definition;State=3;', 'Definition=$definition;State=4;')
        script = script.replace("throw [Runtime.InteropServices.COMException]::new('PRIVATE UNRELATED TASK',-2147024891)",
                                'return @($script:ending,$script:live)')
        script += ("\n$ending | Add-Member NoteProperty Path '\\OtherTask';"
                   "$ending.ErrorCode=-2147024891;"
                   "$live | Add-Member NoteProperty Path '\\router';\n")
        command = backend._tasks._SCRIPT.replace('New-Object -ComObject Schedule.Service', '$script:serviceFixture')
        command = command.replace('$owned = Test-Python ($d.Actions.Item(1).Path)', '$owned = $true')
        def run(_command, **kwargs):
            return subprocess.run([SHELL, '-NoProfile', '-Command', script + command], **kwargs)
        result = backend._tasks.invoke(run, USER, 'Router', 'args')
        self.assertEqual(result['instances'], ['live-instance'])

    def _refusal(self, stdout):
        run = lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout=stdout)
        with self.assertRaises(SystemExit) as refused:
            backend._tasks.invoke(run, USER, 'Router', 'args', 'query')
        return str(refused.exception)

    def test_failure_reports_hresult_and_class_without_message_or_stderr(self):
        doc = json.dumps({'kind': 'error', 'hresult': -2147024809,
                          'type': 'ArgumentException', 'message': 'PRIVATE'})
        self.assertEqual(self._refusal(doc),
                         'cannot verify Windows task Router during query (0x80070057 ArgumentException)')

    def test_malformed_or_content_bearing_diagnostics_stay_plain(self):
        for doc in ('not json', [], {'kind': 'error', 'hresult': True, 'type': 'Error'},
                    {'kind': 'error', 'hresult': -1, 'type': 'PRIVATE /path'},
                    {'kind': 'error', 'hresult': -1, 'type': 'x' * 65}):
            with self.subTest(doc=doc):
                raw = doc if isinstance(doc, str) else json.dumps(doc)
                self.assertEqual(self._refusal(raw), 'cannot verify Windows task Router during query')

    @unittest.skipUnless(SHELL, 'requires executable PowerShell fixtures')
    def test_registered_query_skips_only_confirmed_finished_instances(self):
        for code, after in ((-2147216629, 0), (-2147216629, 1), (-2147024891, 0), (0, 0)):
            with self.subTest(hresult=code, after=after):
                script = backend._tasks._SCRIPT.replace('New-Object -ComObject Schedule.Service',
                                                        '$serviceFixture')
                script = script.replace('$owned = Test-Python ($d.Actions.Item(1).Path)',
                                        '$owned = $true')
                script = FIXTURE.replace("'SID'", "'" + USER + "'").replace('END_CODE', str(code)) + script
                if code == 0 or after:
                    script = script.replace('$ending.ErrorCode = ' + str(code),
                        "$ending.InstanceGuid = ''; $ending.ExitAfter = %s; $ending.ErrorCode = %s" % (after, code))
                request = dict(sid=USER, name='Router', arguments='args', operation='query')
                result = subprocess.run([SHELL, '-NoLogo', '-NoProfile', '-NonInteractive',
                                         '-Command', script], input=json.dumps(request),
                                        capture_output=True, text=True, encoding='utf-8', timeout=20)
                self.assertNotIn('PRIVATE', result.stdout + result.stderr)
                reply = json.loads(result.stdout)
                if code == -2147216629:
                    self.assertEqual(result.returncode, 0)
                    self.assertEqual(reply['instances'], ['live-instance'])
                    self.assertTrue(backend._active(reply))
                else:
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(reply['kind'], 'error')
                    if code:
                        self.assertEqual(reply['hresult'], code)
                    else:
                        self.assertEqual(reply['type'], 'RuntimeException')


if __name__ == '__main__':
    unittest.main()
