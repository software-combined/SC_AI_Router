# Disposable hosted-runner acceptance. Never use an existing staff account.
param(
    [Parameter(Mandatory=$true)][string]$Python,
    [ValidateSet('all', 'core', 'native', 'native-runtime', 'native-shortcuts')][string]$Suite = 'all',
    [ValidateRange(1, 1200)][int]$TimeoutSeconds = 1200,
    [string]$EvidencePath
)
$ErrorActionPreference = 'Stop'

function Assert-StandardReport {
    param([string]$Path, [string]$Suite, [string]$Sid, [int]$ExitCode)
    if (-not (Test-Path -LiteralPath $Path)) { throw 'Standard-user completion report missing.' }
    $result = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json -ErrorAction Stop
    [string[]]$expected = if ($Suite -eq 'all') { @('core', 'native') } else { @($Suite) }
    $rows = @($result.suites)
    if ($result.sid -cne $Sid -or $result.elevated -isnot [bool] -or $result.elevated -or
        $result.status -ne 0 -or $ExitCode -ne 0 -or $rows.Count -ne $expected.Count) {
        throw 'Standard-user completion report does not match its process.'
    }
    for ($index = 0; $index -lt $expected.Count; $index++) {
        $row = $rows[$index]
        if ($row.suite -cne $expected[$index] -or $row.tests -le 0 -or
            $row.success -isnot [bool] -or -not $row.success) { throw 'Standard-user suite failed.' }
        if ($row.suite -like 'native*' -and $row.skipped -ne 0) { throw 'Native standard-user contracts were skipped.' }
    }
    return $result
}
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
$gitCore = (& $git --exec-path).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Git prerequisites are unavailable.' }
$gitRoot = Split-Path (Split-Path (Split-Path $gitCore))
$gitBin = Join-Path $gitRoot 'bin'
$gitUnix = Join-Path $gitRoot 'usr/bin'
if (-not (Test-Path (Join-Path $gitBin 'bash.exe')) -or -not (Test-Path (Join-Path $gitUnix 'grep.exe'))) {
    throw 'The complete Git for Windows toolchain is required.'
}
$process = $null
$started = $false
$account = $null
$report = $null
$validated = $false
$status = 1
try {
    $account = New-LocalUser -Name $name -Password $password -AccountNeverExpires -PasswordNeverExpires
    $sid = $account.SID.Value
    Add-LocalGroupMember -SID 'S-1-5-32-545' -Member $account
    New-Item -ItemType Directory -Path $temporary | Out-Null
    & icacls $temporary /grant "*${sid}:(OI)(CI)F" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Cannot prepare CI working directory.' }
    # Read source and toolchains; all mutable fixtures belong to the temporary user.
    foreach ($directory in @($source, (Split-Path $Python), $gitRoot)) {
        & icacls $directory /grant "*${sid}:(OI)(CI)RX" | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Cannot prepare CI prerequisites.' }
    }
    $report = Join-Path $temporary 'results.json'
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $Python
    $start.Arguments = '-I "' + (Join-Path $source 'tools/windows_standard.py') + '" --sid ' + $sid + ' --report "' + $report + '" --suite ' + $Suite
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
    $start.EnvironmentVariables['PATH'] = (Split-Path $Python) + ';' + $gitBin + ';' + $gitUnix + ';' + (Split-Path $git) + ';' + $env:SystemRoot + '\System32;' + $env:SystemRoot + '\System32\WindowsPowerShell\v1.0'
    $start.EnvironmentVariables['PYTHONIOENCODING'] = 'utf-8'
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $start
    if (-not $process.Start()) { throw 'Standard-user child did not start.' }
    $started = $true
    # Read both pipes concurrently; a full stderr pipe must not deadlock the suite.
    $stdout = $process.StandardOutput.ReadToEndAsync()
    $stderr = $process.StandardError.ReadToEndAsync()
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        $process.Kill()
        $process.WaitForExit()
        throw 'Standard-user suite timed out.'
    }
    if (-not [Threading.Tasks.Task]::WaitAll([Threading.Tasks.Task[]]@($stdout, $stderr), 30000)) {
        throw 'Standard-user output pipes did not close.'
    }
    Write-Host ($stdout.GetAwaiter().GetResult())
    Write-Host ($stderr.GetAwaiter().GetResult())
    $result = Assert-StandardReport -Path $report -Suite $Suite -Sid $sid -ExitCode $process.ExitCode
    $validated = $true
    $status = $process.ExitCode
} finally {
    try {
        try {
            if ($EvidencePath) {
                $evidence = @{identity_verified=$validated; selection=$Suite; suites=@()}
                try {
                    if ($report -and (Test-Path -LiteralPath $report)) {
                        $recorded = Get-Content -LiteralPath $report -Raw | ConvertFrom-Json -ErrorAction Stop
                        $evidence.suites = $recorded.suites
                        $evidence.status = $recorded.status
                    }
                } catch { $evidence.report_error = 'unreadable report' }
                $evidence | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $EvidencePath -Encoding utf8
            }
        } finally {
            if ($null -ne $process) {
                try {
                    if ($started -and -not $process.HasExited) { $process.Kill(); $process.WaitForExit() }
                } finally { $process.Dispose() }
            }
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
