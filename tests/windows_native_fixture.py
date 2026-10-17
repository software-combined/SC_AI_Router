"""Disposable Windows children and cleanup, independent of the task code under test."""
import ctypes
from ctypes import wintypes
import json
import re
import subprocess
import sys
import time


def write_launcher(home, script, lifetime):
    stem = script.removesuffix('.py')
    gate, heartbeat = home / (stem + '.gate'), home / (stem + '.alive')
    gate.touch()
    (home / script).write_text(
        'import os, time\nfrom pathlib import Path\nhome = Path(__file__).parent\n'
        'name = Path(__file__).stem\nstart = time.monotonic()\n'
        'end = start + %d\n' % lifetime +
        'while (home / (name + ".gate")).exists() and time.monotonic() < end:\n'
        '    (home / (name + ".alive")).write_text(\n'
        '        f"{os.getpid()} {start} {end} {time.monotonic()}")\n'
        '    time.sleep(0.1)\n', encoding='utf-8')
    return gate, heartbeat


class NativeChild:
    """A handle to the fixture's own process, retained across definition deletion."""
    def __init__(self, pid, started, end):
        self.started, self.end = started, end
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        self.kernel.WaitForSingleObject.restype = wintypes.DWORD
        self.kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.handle = self.kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE only.
        if not self.handle:
            raise AssertionError('fixture OpenProcess failed: winerror=%d' % ctypes.get_last_error())

    @classmethod
    def capture(cls, heartbeat):
        deadline = time.monotonic() + 2
        while True:
            try:
                pid, started, end, _ = heartbeat.read_text().split()
                return cls(int(pid), float(started), float(end))
            except (OSError, ValueError):  # A read can overlap the heartbeat's short write.
                if time.monotonic() >= deadline:
                    raise AssertionError('fixture heartbeat was unavailable') from None
                time.sleep(0.01)

    def wait_exit(self, timeout):
        result = self.kernel.WaitForSingleObject(self.handle, int(timeout * 1000))
        if result not in (0, 258):  # WAIT_OBJECT_0 and WAIT_TIMEOUT.
            raise AssertionError('fixture process wait failed: winerror=%d' % ctypes.get_last_error())
        return result == 0

    def assert_alive(self, phase):
        alive, now = not self.wait_exit(0), time.monotonic()
        remaining = self.end - now
        print('Windows fixture %s: child_alive=%s age=%.3fs remaining=%.3fs' %
              (phase, alive, now - self.started, remaining), flush=True)
        if not alive or remaining <= 0:
            raise AssertionError('fixture child exited or reached its lifetime during ' + phase)

    def close(self):
        if self.handle:
            if not self.kernel.CloseHandle(self.handle):
                raise AssertionError('fixture CloseHandle failed: winerror=%d' % ctypes.get_last_error())
            self.handle = None


_CLEANUP = r'''
$ErrorActionPreference = 'Stop'
$errors = [Collections.Generic.List[object]]::new()
$definitions = 0; $instances = 0; $index = -1; $stage = 'connect'
try {
    $r = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $s = New-Object -ComObject Schedule.Service; $s.Connect()
    $folder = $s.GetFolder('\')
    function FindTask($name) {
        foreach ($task in $folder.GetTasks(1)) { if ($task.Name -eq $name) { return $task } }
        return $null
    }
    function Running($name) {
        foreach ($item in $s.GetRunningTasks(1)) { if ($item.Path -eq ('\' + $name)) { $item } }
    }
    function Active($task, $name) {
        $state = [int]$task.State
        if ($state -notin @(1, 2, 3, 4)) { throw 'unknown task state' }
        return $state -in @(2, 4) -or @(Running $name).Count -gt 0
    }
    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    for ($index = 0; $index -lt $r.names.Count; $index++) {
        $name = $r.names[$index]
        try {
            $stage = 'find'; $task = FindTask $name
            if ($null -eq $task) { continue } # Fresh enumeration proves this name absent.
            $stage = 'disable'; $task.Enabled = $false
            $stage = 'stop'; if (Active $task $name) { $task.Stop(0) }
            $stage = 'wait'
            while (Active $task $name) {
                if ([DateTime]::UtcNow -ge $deadline) { throw 'task exit timeout' }
                Start-Sleep -Milliseconds 50
            }
            $stage = 'delete'; $folder.DeleteTask($name, 0)
        } catch {
            $errors.Add(@{index=$index; stage=$stage; hresult=$_.Exception.GetBaseException().HResult})
        }
    }
    for ($index = 0; $index -lt $r.names.Count; $index++) {
        $stage = 'readback'
        if ($null -ne (FindTask $r.names[$index])) { $definitions++ }
        $instances += @(Running $r.names[$index]).Count
    }
} catch {
    $definitions = -1; $instances = -1
    $errors.Add(@{index=$index; stage=$stage; hresult=$_.Exception.GetBaseException().HResult})
}
@{definitions=$definitions; instances=$instances; errors=@($errors.ToArray())} | ConvertTo-Json -Depth 4 -Compress
'''


def cleanup(run, names, children=()):
    """Report cleanup independently; a secondary failure must not hide the primary one."""
    primary = sys.exc_info()[1]
    errors, definitions, instances = [], -1, -1
    try:
        for child in children:
            try:
                if not child.wait_exit(15):
                    errors.append('process-exit: timeout')
            except Exception:
                errors.append('process-exit: handle failure')
        try:
            if not names or any(not re.fullmatch(
                    r'SCG-CI-[0-9a-f]{32}(?:-Update|-Express)?(?:-S-\d+(?:-\d+)+)?', name)
                    for name in names):
                raise ValueError('non-fixture task name')
            result = run(['powershell', '-NoProfile', '-NonInteractive', '-Command', _CLEANUP],
                         input=json.dumps({'names': names}), text=True, capture_output=True, timeout=20)
            if result.returncode:
                errors.append('scheduler: returncode=%d' % result.returncode)
            doc = json.loads(result.stdout)
            definitions, instances = doc['definitions'], doc['instances']
            if type(definitions) is not int or type(instances) is not int:
                raise ValueError('invalid counts')
            for error in doc['errors']:
                if error['stage'] not in ('connect', 'find', 'disable', 'stop', 'wait', 'delete', 'readback'):
                    raise ValueError('invalid stage')
                errors.append('task[%d] %s: hresult=%d' %
                              (error['index'], error['stage'], error['hresult']))
        except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError):
            errors.append('scheduler: cleanup result unavailable')
    finally:
        for child in children:
            try:
                child.close()
            except Exception:
                errors.append('process-close: handle failure')
    if definitions != 0 or instances != 0:
        errors.append('readback: exact fixture tasks remain or could not be verified')
    print('Windows fixture cleanup: definitions=%s instances=%s errors=%d' %
          (definitions, instances, len(errors)), flush=True)
    if errors:
        message = 'Windows fixture cleanup failed: ' + '; '.join(errors)
        if primary is not None:
            print(message, file=sys.stderr, flush=True)
        else:
            raise AssertionError(message)
