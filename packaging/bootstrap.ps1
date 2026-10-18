# Public setup and in-place repair for hosts without repository access.
# Run from the public download; never bypass execution policy.
# PowerShell 5.1+, no Python needed up front: resolves the pinned CPython
# runtime from runtimes.json, verifies every download by SHA-256, then runs
# the verified bundle installer. The feed is public: no token is needed.
# Usage:
#   .\bootstrap.ps1 [-Channel beta] [-ChooseClients]
param([string]$Channel = 'stable', [switch]$ChooseClients)
$ErrorActionPreference = 'Stop'
$homeDir = if ($env:ROUTER_HOME) { $env:ROUTER_HOME } else { Join-Path $HOME '.codex\mixed-model-router' }
$homeDir = [IO.Path]::GetFullPath($homeDir)
$repair = if (Test-Path (Join-Path $homeDir 'current')) { @('--repair') } else { @() }
if ($repair) { Write-Host 'Updating or repairing SCG Router. Your key and saved choices stay in place.' }
if (-not $PSBoundParameters.ContainsKey('Channel') -and -not $env:CHANNEL) {
  $savedChannelPath = Join-Path $homeDir 'channel'
  if (Test-Path $savedChannelPath) {
    $savedChannel = (Get-Content -Raw $savedChannelPath).Trim()
    if ($savedChannel -in @('stable', 'beta')) { $Channel = $savedChannel }
  }
}
if ($env:CHANNEL) { $Channel = $env:CHANNEL }
$Channel = $Channel.ToLowerInvariant()
if ($Channel -notin @('stable', 'beta')) {
  Write-Error -ErrorAction Continue 'Channel must be stable or beta.'
  exit 2
}
$feedOrigin = if ($env:FEED_ORIGIN) { $env:FEED_ORIGIN } else { 'https://dist.softwarecombined.com' }
New-Item -ItemType Directory -Force -Path $homeDir | Out-Null
Invoke-RestMethod -Uri "$feedOrigin/runtimes.json" -OutFile (Join-Path $homeDir 'runtimes.json')
$rt = (Get-Content (Join-Path $homeDir 'runtimes.json') | ConvertFrom-Json).targets.'windows/x86_64'
# Percent-encode the URL path: a raw '+' in an S3 key is decoded as a space
# at the edge and denied, and upstream runtime names carry '+' (3.14.7+DATE).
$mirrorUrl = (($rt.mirror -split '/') | ForEach-Object { [uri]::EscapeDataString($_) }) -join '/'
$py = Join-Path $homeDir ("runtime\" + $rt.exec)
function Test-RouterPython([string]$candidate) {
  if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { return $false }
  try {
    & $candidate -c "import sys,compression.zstd;assert sys.version_info >= (3,14)" 2>$null
    return $LASTEXITCODE -eq 0
  } catch { return $false }
}
if (-not (Test-RouterPython $py)) {
  Invoke-WebRequest -Uri "$feedOrigin/$mirrorUrl" -OutFile (Join-Path $homeDir 'runtime.tar.gz')
  $hash = (Get-FileHash (Join-Path $homeDir 'runtime.tar.gz') -Algorithm SHA256).Hash.ToLower()
  if ($hash -ne $rt.sha256.ToLower()) { Write-Error -ErrorAction Continue 'runtime checksum mismatch'; exit 1 }
  $runtimeDir = Join-Path $homeDir 'runtime'
  if (Test-Path $runtimeDir) { $runtimeDir = Join-Path $runtimeDir $hash }
  New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
  $py = Join-Path $runtimeDir $rt.exec
  if (-not (Test-RouterPython $py)) {
    tar -xzf (Join-Path $homeDir 'runtime.tar.gz') -C $runtimeDir
    if ($LASTEXITCODE -ne 0) { exit 1 }
  }
}
& $py -c "import compression.zstd; print('runtime ok')"
if ($LASTEXITCODE -ne 0) { exit 1 }
$feed = Invoke-RestMethod -Uri "$feedOrigin/$Channel/latest.json"
$feed | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $homeDir 'latest.json')
$asset = ($feed.url -split '/')[-1]
Invoke-WebRequest -Uri "$feedOrigin/bundles/$asset" -OutFile (Join-Path $homeDir 'bundle.tar.gz')
$hash = (Get-FileHash (Join-Path $homeDir 'bundle.tar.gz') -Algorithm SHA256).Hash.ToLower()
if ($hash -ne $feed.sha256.ToLower()) { Write-Error -ErrorAction Continue 'bundle checksum mismatch'; exit 1 }
New-Item -ItemType Directory -Force -Path (Join-Path $homeDir 'bootstrap') | Out-Null
tar -xzf (Join-Path $homeDir 'bundle.tar.gz') -C (Join-Path $homeDir 'bootstrap')
if ($LASTEXITCODE -ne 0) { exit 1 }
# Pin this run to the channel the operator asked for: the installer resolves
# its own feed from the router home, which may still name the old channel.
# Persist the channel only once the install proves out, so an aborted
# bootstrap cannot move a stable host onto pre-releases.
$choose = if ($ChooseClients) { @('--choose-clients') } else { @() }
& $py (Join-Path $homeDir 'bootstrap\packaging\install.py') --home $homeDir --python $py --feed "$feedOrigin/$Channel/latest.json" @repair @choose
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$current = & $py -c 'import pathlib,sys;p=pathlib.Path(sys.argv[1]);print(p.resolve().name if p.is_symlink() and p.is_dir() else p.read_text().strip() if p.exists() else str())' (Join-Path $homeDir 'current')
$landed = $false
if ($current) {
  try { $landed = ([version]$current -ge [version]$feed.version) } catch { $landed = $false }
}
if (-not $landed) {
  Write-Error -ErrorAction Continue "install did not land $($feed.version) (current '$current'); channel left unchanged"
  exit 1
}
# A channel switch invalidates the old channel's anti-replay serial.
$oldChannel = if (Test-Path (Join-Path $homeDir 'channel')) { ("" + (Get-Content -Raw (Join-Path $homeDir 'channel'))).Trim() } else { '' }
if ($oldChannel -ne $Channel) {
  $serial = Join-Path $homeDir 'feed-serial'
  if (Test-Path $serial) { Remove-Item -Force $serial }
}
Set-Content -Path (Join-Path $homeDir 'channel') -Value $Channel
