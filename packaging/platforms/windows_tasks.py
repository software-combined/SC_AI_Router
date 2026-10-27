"""Task Scheduler's structured API and mutation-time ownership gate. Python 3.9+."""
import json
import ntpath
import re
import subprocess
import xml.etree.ElementTree as ET

_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
Set-StrictMode -Version Latest
$pendingMarker = 'codex-router-installer:pending-activation'
function Get-InstanceId($instance) {
    try {
        # A property getter can return empty without throwing in PowerShell.
        $null = $instance.Refresh()
        $id = [string]$instance.InstanceGuid
        if ([string]::IsNullOrWhiteSpace($id)) {
            $null = $instance.Refresh()  # Confirm exit after a property-read race; otherwise refuse.
            throw 'unreadable task instance'
        }
        return $id
    } catch {
        # SCHED_E_TASK_NOT_RUNNING (0x8004130B) proves the instance is gone.
        if ($_.Exception.GetBaseException().HResult -eq -2147216629) { return $null }
        throw
    }
}
function Test-Python($path) {
    try {
        $info = [Diagnostics.FileVersionInfo]::GetVersionInfo($path)
        return ([IO.Path]::IsPathRooted($path) -and $info.ProductName -eq 'Python' -and
            $info.OriginalFilename -match '^pythonw?(_d)?\.exe$')
    } catch { return $false }
}
try {
    $r = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $service = New-Object -ComObject Schedule.Service
    $service.Connect()
    $folder = $service.GetFolder('\')
    $task = $null
    try { $task = $folder.GetTask($r.name) } catch {
        $code = $_.Exception.GetBaseException().HResult
        if ($code -eq -2147024891 -and $r.operation -eq 'query') {
            @{kind = 'denied'} | ConvertTo-Json -Compress
            exit 0
        }
        if ($code -ne -2147024894) { throw }
    }
    if ($null -eq $task) {
        foreach ($instance in $service.GetRunningTasks(1)) {
            if ($instance.Path -ieq ('\' + $r.name)) { throw 'unowned running instance' }
        }
    }
    if ($null -ne $task) {
        $d = $task.Definition
        $principal = $d.Principal.UserId
        if ($principal -notmatch '^S-1-') {
            $principal = ([Security.Principal.NTAccount]::new($principal)).Translate(
                [Security.Principal.SecurityIdentifier]).Value
        }
        $owned = $principal -eq $r.sid -and $d.Principal.LogonType -eq 3 -and
            $d.Principal.RunLevel -eq 0 -and $d.Actions.Count -eq 1 -and
            $d.Actions.Item(1).Type -eq 0 -and
            $d.Actions.Item(1).Arguments -ieq $r.arguments -and
            $d.RegistrationInfo.Author -eq 'codex-router-installer'
        if ($owned) {
            # Read CPython's version resource; never execute a task's claimed interpreter.
            $owned = Test-Python ($d.Actions.Item(1).Path)
        }
        if (-not $owned) {
            @{kind = 'foreign'} | ConvertTo-Json -Compress
            exit 0
        }
    }
    $created = $null -eq $task
    if ($r.operation -eq 'register') {
        $definition = $service.NewTask(0)
        $definition.XmlText = $r.xml
        $definition.Principal.UserId = $r.sid
        $definition.Data = if (($created -and $r.pending) -or
            (-not $created -and $task.Definition.Data -eq $pendingMarker)) {
            $pendingMarker
        } else { '' }
        $definition.Settings.Enabled = -not $created -and $task.Enabled
        $flags = if ($null -eq $task) { 2 } else { 4 }
        $task = $folder.RegisterTaskDefinition($r.name, $definition, $flags, $r.sid, $null, 3, $null)
    } elseif ($null -ne $task) {
        if ($r.operation -eq 'restore') {
            $definition = $service.NewTask(0)
            $definition.XmlText = $r.xml
            $task = $folder.RegisterTaskDefinition($r.name, $definition, 4, $r.sid, $null, 3, $null)
        } elseif ($r.operation -eq 'rebind') {
            if (-not (Test-Python $r.executable)) { throw 'invalid runtime' }
            $definition = $task.Definition
            $definition.Actions.Item(1).Path = $r.executable
            $task = $folder.RegisterTaskDefinition($r.name, $definition, 4, $r.sid, $null, 3, $null)
        } elseif ($r.operation -in @('handover', 'complete', 'disable') -or
            ($r.operation -eq 'enable' -and $task.Definition.Data -eq $pendingMarker)) {
            $definition = $task.Definition
            # Record restart intent with disabling; Run must retain it until health succeeds.
            $definition.Settings.Enabled = if ($r.operation -in @('handover', 'disable')) {
                $false
            } elseif ($r.operation -eq 'enable') { $true } else { $task.Enabled }
            $definition.Data = if ($r.operation -eq 'handover') { $pendingMarker } else { '' }
            $task = $folder.RegisterTaskDefinition($r.name, $definition, 4, $r.sid, $null, 3, $null)
        }
        switch ($r.operation) {
            'run' { $task.Enabled = $true; $null = $task.Run($null) }
            'enable' { $task.Enabled = $true }
            'disable' { $task.Enabled = $false }
            'stop' {
                try { $task.Stop(0) } catch {
                    if ($_.Exception.GetBaseException().HResult -ne -2147216629) { throw }
                }
                foreach ($instance in $task.GetInstances(0)) {
                    try { $instance.Stop() } catch {
                        if ($_.Exception.GetBaseException().HResult -ne -2147216629) { throw }
                    }
                }
            }
            'delete' { $folder.DeleteTask($r.name, 0); $task = $null }
        }
        if ($r.operation -in @('run', 'enable') -and -not $task.Enabled) { throw 'disabled' }
    }
    if ($null -eq $task) {
        @{kind = 'missing'} | ConvertTo-Json -Compress
    } else {
        # Include hidden instances and old invocations after their definition changes.
        $instances = @(foreach ($instance in $task.GetInstances(0)) {
            $id = Get-InstanceId $instance
            if ($id) { $id }
        })
        $reply = @{kind = 'present'; state = [int]$task.State; instances = $instances
          enabled = [bool]$task.Enabled
          pending = $task.Definition.Data -eq $pendingMarker
          executable = [string]$task.Definition.Actions.Item(1).Path}
        $reply.catchup = [bool]$task.Definition.Settings.StartWhenAvailable
        $reply.signin = $false
        foreach ($trigger in $task.Definition.Triggers) {
            if ($trigger.Type -eq 9 -and $trigger.Enabled -and $trigger.UserId) {
                $user = [string]$trigger.UserId
                if ($user -notmatch '^S-1-') {
                    $user = ([Security.Principal.NTAccount]::new($user)).Translate(
                        [Security.Principal.SecurityIdentifier]).Value
                }
                if ($user -eq $r.sid) { $reply.signin = $true }
            }
        }
        if ($r.operation -eq 'snapshot') { $reply.xml = $task.Definition.XmlText }
        $reply | ConvertTo-Json -Depth 4 -Compress
    }
} catch {
    $failure = $_.Exception.GetBaseException()
    @{kind = 'error'; hresult = [int]$failure.HResult; type = $failure.GetType().Name} |
        ConvertTo-Json -Compress
    exit 1
}
"""


class OwnershipError(SystemExit):
    """A task belongs elsewhere, or its owner cannot be read."""


def invoke(run, sid, name, arguments, operation='query', xml=None, *, pending=True, executable=None):
    """Names and paths travel as JSON data, never interpolated PowerShell."""
    request = dict(sid=sid, name=name, arguments=arguments, operation=operation,
                   xml=xml, pending=pending, executable=executable)
    detail = ''
    try:
        result = run(['powershell', '-NoLogo', '-NoProfile', '-NonInteractive',
                      '-Command', _SCRIPT], input=json.dumps(request),
                     capture_output=True, text=True, encoding='utf-8', timeout=20)
        if result.returncode != 0:
            detail = _failure(result.stdout)
            raise ValueError('Task Scheduler query or operation failed')
        doc = json.loads(result.stdout)
        if doc['kind'] in ('foreign', 'denied'):
            raise OwnershipError('Windows task %s is %s; left untouched' % (name, doc['kind']))
        if doc['kind'] == 'missing':
            if operation not in ('query', 'delete'):
                raise ValueError('task disappeared')
            return None
        if (doc['kind'] != 'present' or type(doc['state']) is not int
                or type(doc.get('pending')) is not bool
                or type(doc.get('enabled')) is not bool
                or not isinstance(doc.get('executable'), str) or not ntpath.isabs(doc['executable'])
                or doc['state'] not in (0, 1, 2, 3, 4)
                or not isinstance(doc['instances'], list)
                or any(not isinstance(item, str) or not item for item in doc['instances'])):
            raise ValueError('malformed task state')
        if doc['state'] == 0:
            raise ValueError('unknown task state')
        if operation == 'snapshot' and (not isinstance(doc.get('xml'), str) or not doc['xml']):
            raise ValueError('missing task definition')
        return doc
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError):
        raise SystemExit('cannot verify Windows task %s during %s%s' % (name, operation, detail))


def _failure(stdout):
    """Numeric HRESULT and a class identifier only, never arbitrary child output."""
    try:
        doc = json.loads(stdout)
        if (doc.get('kind') == 'error' and type(doc.get('hresult')) is int
                and isinstance(doc.get('type'), str)
                and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', doc['type'])):
            return ' (0x%08X %s)' % (doc['hresult'] & 0xFFFFFFFF, doc['type'])
    except (ValueError, TypeError, AttributeError):
        pass
    return ''


def _matches(current, previous, executable):
    return (current is not None and current['executable'] == executable
            and all(current[key] == previous[key] for key in ('enabled', 'pending')))


def runtime_matches(call, home, executable, names):
    """Inspect owned actions without taking snapshots or registering tasks."""
    for name in names:
        current = call(name, home)
        if (current is None or current['executable'] != executable
                or not update_policy_ready(current)):
            return False
    return True


def update_policy_ready(row):
    return row.get('catchup') is True and row.get('signin') is True


def update_policy_xml(xml, sid, executable):
    """Add shared task policy while retaining existing settings, arguments and task data."""
    root = ET.fromstring(xml)
    prefix = '{http://schemas.microsoft.com/windows/2004/02/mit/task}'
    triggers, settings = root.find(prefix + 'Triggers'), root.find(prefix + 'Settings')
    if triggers is None or settings is None or not sid:
        raise ValueError('invalid update task definition')
    logon = next((item for item in triggers.findall(prefix + 'LogonTrigger')
                  if item.findtext(prefix + 'UserId') == sid), None)
    if logon is None:
        logon = ET.SubElement(triggers, prefix + 'LogonTrigger')
        ET.SubElement(logon, prefix + 'UserId').text = sid
    for parent, name in ((logon, 'Enabled'), (settings, 'StartWhenAvailable')):
        child = parent.find(prefix + name)
        if child is None:
            child = ET.SubElement(parent, prefix + name)
        child.text = 'true'
    root.find(prefix + 'Actions/' + prefix + 'Exec/' + prefix + 'Command').text = executable
    return ET.tostring(root, encoding='unicode')


def rebind(call, home, executable, names, sid):
    """Snapshot all definitions before mutation; restore every attempted change on failure."""
    previous = {name: call(name, home, 'snapshot') for name in names}
    if any(row is None for row in previous.values()):
        raise SystemExit('Windows runtime repair requires all three owned tasks')
    changed = []
    try:
        for name, before in previous.items():
            policy = not update_policy_ready(before)
            if before['executable'] == executable and not policy:
                continue
            changed.append(name)
            if policy:
                call(name, home, 'restore', xml=update_policy_xml(before['xml'], sid, executable))
            else:
                call(name, home, 'rebind', executable=executable)
            current = call(name, home)
            if (not _matches(current, before, executable)
                    or not update_policy_ready(current)):
                raise SystemExit('Windows task runtime readback failed')
    except BaseException:
        failed = []
        for name in reversed(changed):
            try:
                before = previous[name]
                call(name, home, 'restore', xml=before['xml'])
                restored = call(name, home, 'snapshot')
                if (not _matches(restored, before, before['executable'])
                        or restored['xml'] != before['xml']):
                    raise ValueError('runtime rollback readback failed')
            except BaseException:
                failed.append(name)
        if failed:
            raise SystemExit('Windows runtime repair could not restore every task; retained runtimes kept') from None
        raise
    return bool(changed)
