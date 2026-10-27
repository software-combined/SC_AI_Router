# Disposable hosted-runner acceptance. Never use an existing staff account.
param([Parameter(Mandatory=$true)][string]$Python)
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_OS -ne 'Windows') {
    throw 'This tool requires a disposable Windows GitHub runner.'
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Runner setup requires administrator rights.' }
$name = 'scgci' + [Guid]::NewGuid().ToString('N').Substring(0, 12)
$password = ConvertTo-SecureString ('Aa1!' + [Guid]::NewGuid().ToString('N')) -AsPlainText -Force
$source = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$temporary = Join-Path $env:RUNNER_TEMP $name
$git = (Get-Command git -ErrorAction Stop).Source
$process = $null
$started = $false
$account = $null
$status = 1
try {
    $account = New-LocalUser -Name $name -Password $password -AccountNeverExpires -PasswordNeverExpires
    $sid = $account.SID.Value
    Add-LocalGroupMember -SID 'S-1-5-32-545' -Member $account
    New-Item -ItemType Directory -Path $temporary | Out-Null
    & icacls $temporary /grant "*${sid}:(OI)(CI)F" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Cannot prepare CI working directory.' }
    # Read source and toolchains; all mutable fixtures belong to the temporary user.
    foreach ($directory in @($source, (Split-Path $Python), (Split-Path $git))) {
        & icacls $directory /grant "*${sid}:(OI)(CI)RX" | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Cannot prepare CI prerequisites.' }
    }
    $report = Join-Path $temporary 'results.json'
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $Python
    $start.Arguments = '-I "' + (Join-Path $source 'tools/windows_standard.py') + '" --sid ' + $sid + ' --report "' + $report + '"'
    $start.WorkingDirectory = $source
    $start.UserName = $name
    $start.Domain = $env:COMPUTERNAME
    $start.Password = $password
    $start.LoadUserProfile = $true
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.EnvironmentVariables.Clear()
    $start.EnvironmentVariables['SystemRoot'] = $env:SystemRoot
    $start.EnvironmentVariables['WINDIR'] = $env:WINDIR
    $start.EnvironmentVariables['COMSPEC'] = $env:COMSPEC
    $start.EnvironmentVariables['USERNAME'] = $name
    $start.EnvironmentVariables['USERDOMAIN'] = $env:COMPUTERNAME
    $start.EnvironmentVariables['TEMP'] = $temporary
    $start.EnvironmentVariables['TMP'] = $temporary
    $start.EnvironmentVariables['PATH'] = (Split-Path $Python) + ';' + (Split-Path $git) + ';' + $env:SystemRoot + '\System32;' + $env:SystemRoot + '\System32\WindowsPowerShell\v1.0'
    $start.EnvironmentVariables['PYTHONIOENCODING'] = 'utf-8'
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $start
    if (-not $process.Start()) { throw 'Standard-user child did not start.' }
    $started = $true
    # Read both pipes concurrently; a full stderr pipe must not deadlock the suite.
    $stdout = $process.StandardOutput.ReadToEndAsync()
    $stderr = $process.StandardError.ReadToEndAsync()
    if (-not $process.WaitForExit(1200000)) {
        $process.Kill()
        $process.WaitForExit()
        throw 'Standard-user suite timed out.'
    }
    if (-not [Threading.Tasks.Task]::WaitAll([Threading.Tasks.Task[]]@($stdout, $stderr), 30000)) {
        throw 'Standard-user output pipes did not close.'
    }
    Write-Host ($stdout.GetAwaiter().GetResult())
    Write-Host ($stderr.GetAwaiter().GetResult())
    if (-not (Test-Path -LiteralPath $report)) { throw 'Standard-user completion report missing.' }
    $result = Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
    if ($result.sid -ne $sid -or $result.elevated -ne $false -or
        $result.suites.Count -ne 2 -or $result.status -ne $process.ExitCode) {
        throw 'Standard-user completion report does not match its process.'
    }
    foreach ($suite in $result.suites) {
        if ($suite.tests -le 0 -or -not $suite.success) { throw 'Standard-user suite failed.' }
        if ($suite.suite -eq 'native' -and $suite.skipped -ne 0) { throw 'Native standard-user contracts were skipped.' }
    }
    $status = $process.ExitCode
} finally {
    try {
        if ($null -ne $process) {
            try {
                if ($started -and -not $process.HasExited) { $process.Kill(); $process.WaitForExit() }
            } finally { $process.Dispose() }
        }
    } finally {
        try {
            if ($null -ne $account) {
                try {
                # Reuse retained native handles for the new account's children; no PID-only kills.
                    if ($started) {
                        & $Python -I (Join-Path $source 'tools/windows_standard.py') --sid $account.SID.Value --cleanup
                        if ($LASTEXITCODE -ne 0) { throw 'Standard-user process cleanup failed.' }
                    }
                    $profile = Get-CimInstance Win32_UserProfile | Where-Object SID -EQ $account.SID.Value
                    if ($profile) { $profile | Remove-CimInstance }
                } finally { Remove-LocalUser -SID $account.SID }
            }
        } finally {
            $password.Dispose()
            if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Recurse -Force }
        }
    }
}
exit $status
