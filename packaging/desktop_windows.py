"""Resolve exactly one installed desktop package in the current Windows account."""
import json
import ntpath
import os
from pathlib import Path
import re
import subprocess
import time


class QueryError(OSError):
    """A desktop failure with content-free diagnostic facts."""
    def __init__(self, operation, reason, **facts):
        super().__init__('The desktop app could not be checked')
        self.facts = dict(operation=operation, reason=reason, **facts)


def error_facts(error, operation):
    while error is not None:
        if isinstance(error, QueryError):
            return dict(error.facts)
        if error.__cause__ is None:
            break
        error = error.__cause__
    facts = dict(operation=operation, reason='timeout' if isinstance(
        error, subprocess.TimeoutExpired) else 'command_failed', error=type(error).__name__)
    for key in ('winerror', 'errno', 'returncode'):
        if type(getattr(error, key, None)) is int:
            facts[key] = getattr(error, key)
    return facts


def json_command(script, run, *, timeout=5, operation='process_snapshot'):
    started = time.monotonic()
    wrapped = ("$ErrorActionPreference='Stop';"
        "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);"
        "$scg_stage='query';try{" + script + "}catch{"
        "@{scg_error=$scg_stage;hresult=[int]$_.Exception.HResult}|ConvertTo-Json -Compress;exit 1}")
    try:
        answer = run(['powershell', '-NoProfile', '-Command', wrapped], capture_output=True,
                     text=True, encoding='utf-8', timeout=timeout, creationflags=0x08000000)
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        facts = error_facts(exc, operation)
        raise QueryError(operation, facts.pop('reason'), elapsed_ms=round(
            (time.monotonic() - started) * 1000, 1),
            **{key: value for key, value in facts.items() if key != 'operation'}) from None
    try:
        doc = json.loads(answer.stdout)
    except (ValueError, TypeError):
        doc = None
    if answer.returncode or doc is None:
        facts = dict(exit_code=answer.returncode,
                     elapsed_ms=round((time.monotonic() - started) * 1000, 1))
        if isinstance(doc, dict) and doc.get('scg_error') in (
                'query', 'start_apps', 'package', 'manifest', 'executable', 'process_snapshot'):
            facts['stage'] = doc['scg_error']
            if type(doc.get('hresult')) is int:
                facts['hresult'] = doc['hresult']
        raise QueryError(operation, 'query_exit' if answer.returncode else 'invalid_output', **facts)
    return doc


def snapshot_script(identity, tracked=(), names=()):
    """Select relevant process trees before querying their owners."""
    request = json.dumps(dict(root=identity['root'], user=identity['user'],
        names=list(names) + [ntpath.basename(identity['exe'])], tracked=list(tracked)))
    return ("$scg_stage='process_snapshot';$request=ConvertFrom-Json '%s';" % request.replace("'", "''") + r'''
$root=([string]$request.root).TrimEnd('\','/')+'\';
$session=(Get-Process -Id $PID).SessionId;
$all=@(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {$_.SessionId -eq $session});
$wanted=@{};
foreach($p in $all){
    if(($p.ExecutablePath -and $p.ExecutablePath.StartsWith($root,'OrdinalIgnoreCase')) -or
       $p.Name -in $request.names -or [int]$p.ProcessId -in $request.tracked){
        $wanted[[int]$p.ProcessId]=$true
    }
}
do{
    $changed=$false;
    foreach($p in $all){
        if($wanted.ContainsKey([int]$p.ParentProcessId) -and -not $wanted.ContainsKey([int]$p.ProcessId)){
            $wanted[[int]$p.ProcessId]=$true;$changed=$true
        }
    }
}while($changed);
$rows=@(foreach($p in $all){
    if(-not $wanted.ContainsKey([int]$p.ProcessId)){continue};
    try{
        $o=Invoke-CimMethod -InputObject $p -MethodName GetOwnerSid -ErrorAction Stop;
        if($o.ReturnValue -ne 0){throw 'owner'}
    }catch{
        $live=@(Get-CimInstance -ClassName Win32_Process -Filter ("ProcessId="+$p.ProcessId) -ErrorAction Stop);
        if($live.Count -eq 0){continue};throw
    }
    if($o.Sid -eq $request.user){
        if(-not $p.ExecutablePath -or -not $p.CreationDate){throw 'metadata'};
        @{pid=[int]$p.ProcessId;parent=[int]$p.ParentProcessId;user=$o.Sid;
          born=$p.CreationDate.ToString('o');exe=$p.ExecutablePath}
    }
});
ConvertTo-Json -InputObject $rows -Compress
''')


def claude_roaming_root(roaming, local, run=None):
    """Store builds virtualize the subscription profile under their package."""
    if not local or not (Path(local) / 'Packages').is_dir():
        return roaming
    system_root = os.environ.get('SystemRoot')
    if not system_root or not Path(system_root).is_absolute():
        raise OSError('Windows system directory could not be checked')
    powershell = Path(system_root) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    run = subprocess.run if run is None else run
    script = ("$ErrorActionPreference='Stop';"
              "$families=@(Get-AppxPackage -Name Claude | ForEach-Object {$_.PackageFamilyName});"
              "ConvertTo-Json -InputObject $families -Compress")
    try:
        answer = run([str(powershell), '-NoProfile', '-NonInteractive', '-Command', script],
                     capture_output=True, text=True, timeout=10,
                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        families = json.loads(answer.stdout)
        if (answer.returncode or not isinstance(families, list) or len(families) > 1
                or any(not isinstance(family, str) or not re.fullmatch(
                    r'Claude_[A-Za-z0-9]+', family) for family in families)):
            raise ValueError('invalid package identity')
    except (ValueError, TypeError, subprocess.SubprocessError) as exc:
        raise OSError('Claude profile location could not be checked') from exc
    if not families:
        return roaming
    return Path(local) / 'Packages' / families[0] / 'LocalCache' / 'Roaming'


def identity(bundle_id, query):
    names = {'com.openai.codex': "@('Codex','ChatGPT')",
             'com.anthropic.claudefordesktop': "@('Claude')"}
    if bundle_id not in names:
        raise OSError('Unknown desktop app')
    return query(
        "$scg_stage='start_apps';$names=%s;" % names[bundle_id] +
        "$a=@(Get-StartApps | Where-Object {$_.Name -in $names});"
        "if($a.Count -ne 1 -or $a[0].AppID -notmatch '!'){throw 'identity'};"
        "$family,$id=$a[0].AppID.Split('!');"
        "$scg_stage='package';$p=@(Get-AppxPackage | Where-Object {$_.PackageFamilyName -eq $family});"
        "if($p.Count -ne 1){throw 'identity'};"
        "$scg_stage='manifest';$m=Get-AppxPackageManifest $p[0];"
        "$e=@($m.Package.Applications.Application | Where-Object {$_.Id -eq $id});"
        "if($e.Count -ne 1 -or -not $e[0].Executable){throw 'identity'};"
        "$scg_stage='executable';$exe=Join-Path $p[0].InstallLocation $e[0].Executable;"
        "if(-not (Test-Path -LiteralPath $exe -PathType Leaf)){throw 'identity'};"
        "@{root=$p[0].InstallLocation;exe=$exe;app=$a[0].AppID;"
        "user=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value} | ConvertTo-Json -Compress")
