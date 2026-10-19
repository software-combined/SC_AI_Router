"""Resolve exactly one installed desktop package in the current Windows account."""
import json
import os
from pathlib import Path
import re
import subprocess


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
        "$names=%s;" % names[bundle_id] +
        "$a=@(Get-StartApps | Where-Object {$_.Name -in $names});"
        "if($a.Count -ne 1 -or $a[0].AppID -notmatch '!'){throw 'identity'};"
        "$family,$id=$a[0].AppID.Split('!');"
        "$p=@(Get-AppxPackage | Where-Object {$_.PackageFamilyName -eq $family});"
        "if($p.Count -ne 1){throw 'identity'};"
        "$m=Get-AppxPackageManifest $p[0];"
        "$e=@($m.Package.Applications.Application | Where-Object {$_.Id -eq $id});"
        "if($e.Count -ne 1 -or -not $e[0].Executable){throw 'identity'};"
        "$exe=Join-Path $p[0].InstallLocation $e[0].Executable;"
        "if(-not (Test-Path -LiteralPath $exe -PathType Leaf)){throw 'identity'};"
        "@{root=$p[0].InstallLocation;exe=$exe;app=$a[0].AppID;"
        "user=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value} | ConvertTo-Json -Compress")
