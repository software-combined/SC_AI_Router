"""Fixture failures must not turn unknown process or cleanup state into success."""
import ctypes
from ctypes import wintypes
import io
import json
import shutil
import subprocess
import sys
import traceback
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest import mock

from tests.windows_native_fixture import NativeChild, cleanup, create_shortcut

NAME = 'SCG-CI-' + 'a' * 32
POWERSHELL = shutil.which('powershell' if sys.platform == 'win32' else 'pwsh')


class ShortcutCreationDiagnosticsTests(unittest.TestCase):
    def test_timeout_reports_only_closed_phases_and_bounds_fixture_creation(self):
        cases = [(None, 'script-entry-unobserved'),
                 (b'PRIVATE STDERR\nSCG_SHORTCUT_STAGE=PRIVATE\n', 'script-entry-unobserved')]
        for phase in ('entry', 'new-object', 'create-shortcut', 'target', 'arguments', 'save', 'complete'):
            stderr = 'SCG_SHORTCUT_STAGE=%s\r\nPRIVATE STDERR\nSCG_SHORTCUT_STAGE=PRIVATE\n' % phase
            cases.append((stderr.encode(), phase))
        cases.append(('SCG_SHORTCUT_STAGE=save\n', 'save'))
        for stderr, phase in cases:
            run = mock.Mock(side_effect=subprocess.TimeoutExpired(
                'PRIVATE COMMAND', 60, output=b'PRIVATE STDOUT', stderr=stderr))
            values = dict(path='PRIVATE PATH', target='PRIVATE TARGET', arguments='PRIVATE ARGUMENTS')
            with self.subTest(phase=phase):
                try:
                    create_shortcut(run, **values)
                except AssertionError as error:
                    self.assertEqual(str(error),
                        'Windows shortcut creation timed out after 60 seconds (phase=%s)' % phase)
                    self.assertTrue(error.__suppress_context__)
                    self.assertNotIn('PRIVATE', traceback.format_exc())
                else:
                    self.fail('Shortcut creation did not refuse the timeout')
                run.assert_called_once()
                self.assertEqual(run.call_args.kwargs['timeout'], 60)
                self.assertTrue(run.call_args.kwargs['check'])
                self.assertTrue(run.call_args.kwargs['capture_output'])
                self.assertEqual(run.call_args.args[0][:3], ['powershell', '-NoProfile', '-Command'])

    @unittest.skipUnless(POWERSHELL, 'requires PowerShell to exercise the shortcut script')
    def test_real_script_marks_creation_order_and_preserves_quoted_values(self):
        fixture = r'''
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$script:link = [pscustomobject]@{TargetPath='';Arguments=''}
$script:link | Add-Member ScriptMethod Save {
    [Console]::Error.WriteLine('ACTION=save')
    [Console]::Out.WriteLine((@{path=$script:path;target=$this.TargetPath;arguments=$this.Arguments} |
                            ConvertTo-Json -Compress))
}
$script:shell = [pscustomobject]@{}
$script:shell | Add-Member ScriptMethod CreateShortcut {
    param($path)
    [Console]::Error.WriteLine('ACTION=create-shortcut')
    $script:path = $path
    return $script:link
}
function New-Object {
    param($ComObject)
    if ($ComObject -ne 'WScript.Shell') { throw 'Unexpected COM class' }
    [Console]::Error.WriteLine('ACTION=new-object')
    return $script:shell
}
'''
        def run(command, **kwargs):
            return subprocess.run([POWERSHELL, *command[1:-1], fixture + command[-1]], **kwargs)
        values = dict(path="C:\\fixture é's\\SCG Router.lnk", target="C:\\fixture é's\\pythonw.exe",
                      arguments='"C:\\fixture é\'s\\native_launch.py" --action remove')
        result = create_shortcut(run, **values)
        self.assertEqual(json.loads(result.stdout), values)
        phases = [line for line in result.stderr.decode().splitlines()
                  if line.startswith(('SCG_SHORTCUT_STAGE=', 'ACTION='))]
        self.assertEqual(phases, [
            'SCG_SHORTCUT_STAGE=entry', 'SCG_SHORTCUT_STAGE=new-object', 'ACTION=new-object',
            'SCG_SHORTCUT_STAGE=create-shortcut', 'ACTION=create-shortcut',
            'SCG_SHORTCUT_STAGE=target', 'SCG_SHORTCUT_STAGE=arguments',
            'SCG_SHORTCUT_STAGE=save', 'ACTION=save', 'SCG_SHORTCUT_STAGE=complete'])
        fixture = fixture.replace("[Console]::Error.WriteLine('ACTION=save')", "throw 'synthetic Save failure'")
        with self.assertRaises(subprocess.CalledProcessError) as failure:
            create_shortcut(run, **values)
        self.assertIn(b'SCG_SHORTCUT_STAGE=save', failure.exception.stderr)
        self.assertNotIn(b'SCG_SHORTCUT_STAGE=complete', failure.exception.stderr)


class NativeHandleTests(unittest.TestCase):
    def test_wait_failure_is_not_exit_and_a_64_bit_handle_is_closed_once(self):
        handle = 0x100000001
        kernel = SimpleNamespace(OpenProcess=mock.Mock(return_value=handle),
                                 WaitForSingleObject=mock.Mock(side_effect=[258, 0, 0xFFFFFFFF]),
                                 CloseHandle=mock.Mock(return_value=True))
        with mock.patch.object(ctypes, 'WinDLL', return_value=kernel, create=True), \
                mock.patch.object(ctypes, 'get_last_error', return_value=6, create=True):
            child = NativeChild(1234, 1, 41)
            self.assertIs(kernel.OpenProcess.restype, wintypes.HANDLE)
            self.assertEqual(kernel.WaitForSingleObject.argtypes[0], wintypes.HANDLE)
            kernel.OpenProcess.assert_called_once_with(0x00100000, False, 1234)
            self.assertFalse(child.wait_exit(0))
            self.assertTrue(child.wait_exit(1))
            with self.assertRaisesRegex(AssertionError, 'wait failed: winerror=6'):
                child.wait_exit(0)
            self.assertEqual(kernel.WaitForSingleObject.call_args_list,
                             [mock.call(handle, 0), mock.call(handle, 1000), mock.call(handle, 0)])
            child.close()
            child.close()
            kernel.CloseHandle.assert_called_once_with(handle)

    def test_failed_open_and_natural_expiry_cannot_satisfy_liveness(self):
        kernel = SimpleNamespace(OpenProcess=mock.Mock(return_value=0),
                                 WaitForSingleObject=mock.Mock(return_value=258),
                                 CloseHandle=mock.Mock(return_value=True))
        with mock.patch.object(ctypes, 'WinDLL', return_value=kernel, create=True), \
                mock.patch.object(ctypes, 'get_last_error', return_value=5, create=True):
            with self.assertRaisesRegex(AssertionError, 'OpenProcess failed: winerror=5'):
                NativeChild(1234, 1, 41)
            kernel.WaitForSingleObject.assert_not_called()
            kernel.OpenProcess.return_value = 11
            child = NativeChild(1234, 1, 41)
            with mock.patch('tests.windows_native_fixture.time.monotonic', return_value=42), \
                    redirect_stdout(io.StringIO()) as output:
                with self.assertRaisesRegex(AssertionError, 'lifetime during expired-phase'):
                    child.assert_alive('expired-phase')
            self.assertIn('remaining=-1.000s', output.getvalue())
            child.close()


class CleanupTests(unittest.TestCase):
    def _run(self, **changes):
        doc = dict(definitions=0, instances=0, errors=[])
        doc.update(changes)
        return mock.Mock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps(doc)))

    def test_error_is_secondary_to_the_original_failure_but_fails_a_passing_test(self):
        run = self._run(errors=[dict(index=0, stage='delete', hresult=-2147024891)])
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            with self.assertRaisesRegex(RuntimeError, 'primary failure'):
                try:
                    raise RuntimeError('primary failure')
                finally:
                    cleanup(run, [NAME])
            with self.assertRaisesRegex(AssertionError, r'task\[0\] delete: hresult=-2147024891'):
                cleanup(run, [NAME])
        self.assertIn('delete: hresult=-2147024891', errors.getvalue())
        self.assertEqual(json.loads(run.call_args.kwargs['input']), {'names': [NAME]})
        self.assertEqual(run.call_args.kwargs['timeout'], 60)

    def test_residual_or_unreadable_tasks_and_handle_failure_cannot_pass_cleanup(self):
        for result in (dict(definitions=1), dict(instances=1), dict(definitions=-1),
                       dict(instances='0')):
            with self.subTest(result=result), redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(AssertionError, 'cleanup failed'):
                    cleanup(self._run(**result), [NAME])
        children = [SimpleNamespace(wait_exit=mock.Mock(side_effect=AssertionError('not public')),
                                    close=mock.Mock(side_effect=AssertionError('not public'))),
                    SimpleNamespace(wait_exit=mock.Mock(return_value=True), close=mock.Mock())]
        run = self._run()
        with redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(AssertionError, 'process-exit: handle failure') as error:
                cleanup(run, [NAME], children)
        self.assertNotIn('not public', str(error.exception))
        self.assertTrue(run.called)
        for child in children:
            child.wait_exit.assert_called_once_with(15)
            child.close.assert_called_once_with()

    def test_transport_failure_is_safe_and_non_fixture_names_never_reach_scheduler(self):
        run = mock.Mock(side_effect=subprocess.TimeoutExpired('private command', 20,
                                                             stderr='private stderr'))
        with redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(AssertionError, 'result unavailable') as error:
                cleanup(run, [NAME])
            self.assertNotIn('private', str(error.exception))
            run.reset_mock()
            with self.assertRaisesRegex(AssertionError, 'result unavailable'):
                cleanup(run, ['SCG-Router'])
            run.assert_not_called()

    def test_clean_readback_confirms_zero_definitions_and_instances(self):
        with redirect_stdout(io.StringIO()) as output:
            cleanup(self._run(), [NAME])
        self.assertIn('definitions=0 instances=0 errors=0', output.getvalue())

    @unittest.skipUnless(POWERSHELL, 'requires PowerShell to exercise the cleanup script')
    def test_script_skips_absent_definition_and_continues_after_delete_failure(self):
        # Only the external COM boundary is simulated; execute the real cleanup script.
        fake_scheduler = r'''
$script:first = 'SCG-CI-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
$script:second = $script:first + '-Update'
$script:deleted = @(); $script:tasks = @{}
function NewFixtureTask($name) {
    $task = [pscustomobject]@{Name=$name; Enabled=$true; State=4}
    $task | Add-Member ScriptMethod Stop { param($flags) $this.State = 3 }
    return $task
}
$script:tasks[$script:second] = NewFixtureTask $script:second
$script:tasks['foreign-sentinel'] = NewFixtureTask 'foreign-sentinel'
if ($script:mode -eq 'failure') { $script:tasks[$script:first] = NewFixtureTask $script:first }
$script:folder = [pscustomobject]@{}
$script:folder | Add-Member ScriptMethod GetTasks { param($flags) @($script:tasks.Values) }
$script:folder | Add-Member ScriptMethod DeleteTask {
    param($name, $flags)
    $script:deleted += $name
    if ($name -eq $script:first) {
        throw [Runtime.InteropServices.COMException]::new('synthetic delete failure', -2147024891)
    }
    $script:tasks.Remove($name)
}
$script:service = [pscustomobject]@{}
$script:service | Add-Member ScriptMethod Connect {}
$script:service | Add-Member ScriptMethod GetFolder { param($path) $script:folder }
$script:service | Add-Member ScriptMethod GetRunningTasks {
    param($flags)
    foreach ($task in $script:tasks.Values) {
        if ($task.State -eq 4) { [pscustomobject]@{Path=('\' + $task.Name)} }
    }
}
function New-Object { param($ComObject) $script:service }
'''
        trace = r'''
[Console]::Error.WriteLine((@{deleted=@($script:deleted); remaining=@($script:tasks.Keys)} | ConvertTo-Json -Compress))
'''
        for mode in ('missing', 'failure'):
            with self.subTest(mode=mode), redirect_stdout(io.StringIO()):
                results = []
                def run(command, **kwargs):
                    script = "$script:mode = '%s'\n" % mode + fake_scheduler + command[-1] + trace
                    result = subprocess.run([POWERSHELL, *command[1:-1], script], **kwargs)
                    results.append(result)
                    return result
                if mode == 'failure':
                    with self.assertRaisesRegex(AssertionError, r'task\[0\] delete: hresult=-2147024891'):
                        cleanup(run, [NAME, NAME + '-Update'])
                else:
                    cleanup(run, [NAME, NAME + '-Update'])
                self.assertEqual(results[0].returncode, 0)
                seen = json.loads(results[0].stderr)
                self.assertEqual(seen['deleted'], ([NAME] if mode == 'failure' else []) + [NAME + '-Update'])
                self.assertEqual(set(seen['remaining']), {'foreign-sentinel'} | ({NAME} if mode == 'failure' else set()))
