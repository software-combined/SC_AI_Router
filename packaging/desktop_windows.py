"""Resolve exactly one installed desktop package in the current Windows account."""


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
