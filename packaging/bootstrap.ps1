# First-install bootstrap for hosts without repo access (Plan 054 T).
# Run from the Technology library download; never bypass execution policy.
# PowerShell 5.1+, no Python needed up front: resolves the pinned CPython
# runtime from runtimes.json, verifies every download by SHA-256, writes
# the feed token, then runs the verified bundle installer.
# Usage (token from the Technology library page):
#   $env:SCG_FEED_TOKEN = '<token>'; .\bootstrap.ps1 [-Channel beta]
param([string]$Channel = 'stable')
$ErrorActionPreference = 'Stop'
if ($env:CHANNEL) { $Channel = $env:CHANNEL }
$feedOrigin = if ($env:FEED_ORIGIN) { $env:FEED_ORIGIN } else { 'https://dist.softwarecombined.com' }
$homeDir = if ($env:ROUTER_HOME) { $env:ROUTER_HOME } else { Join-Path $HOME '.codex\mixed-model-router' }
$token = $env:SCG_FEED_TOKEN
if (-not $token) {
  Write-Error -ErrorAction Continue 'Set $env:SCG_FEED_TOKEN from the Technology library page first.'
  exit 2
}
New-Item -ItemType Directory -Force -Path $homeDir | Out-Null
$headers = @{ 'X-SCG-Feed-Token' = $token }
$tokenPath = Join-Path $homeDir 'feed-token'
Invoke-RestMethod -Uri "$feedOrigin/runtimes.json" -Headers $headers -OutFile (Join-Path $homeDir 'runtimes.json')
# Persist only after the token fetched successfully; keep the previous
# value for the updater's one-time 403 retry, as feed.py does.
$current = if (Test-Path $tokenPath) { ("" + (Get-Content -Raw $tokenPath)).Trim() } else { '' }
if ($current -and $current -ne $token) {
  Set-Content -NoNewline -Path "$tokenPath.previous" -Value ($current + "`n")
}
Set-Content -NoNewline -Path "$tokenPath.tmp" -Value ($token + "`n")
Move-Item -Force -Path "$tokenPath.tmp" -Destination $tokenPath
$rt = (Get-Content (Join-Path $homeDir 'runtimes.json') | ConvertFrom-Json).targets.'windows/x86_64'
# Percent-encode the URL path: a raw '+' in an S3 key is decoded as a space
# at the edge and denied, and upstream runtime names carry '+' (3.14.7+DATE).
$mirrorUrl = (($rt.mirror -split '/') | ForEach-Object { [uri]::EscapeDataString($_) }) -join '/'
Invoke-WebRequest -Uri "$feedOrigin/$mirrorUrl" -Headers $headers -OutFile (Join-Path $homeDir 'runtime.tar.gz')
$hash = (Get-FileHash (Join-Path $homeDir 'runtime.tar.gz') -Algorithm SHA256).Hash.ToLower()
if ($hash -ne $rt.sha256.ToLower()) { Write-Error -ErrorAction Continue 'runtime checksum mismatch'; exit 1 }
New-Item -ItemType Directory -Force -Path (Join-Path $homeDir 'runtime') | Out-Null
tar -xzf (Join-Path $homeDir 'runtime.tar.gz') -C (Join-Path $homeDir 'runtime')
if ($LASTEXITCODE -ne 0) { exit 1 }
$py = Join-Path $homeDir ("runtime\" + $rt.exec)
& $py -c "import compression.zstd; print('runtime ok')"
if ($LASTEXITCODE -ne 0) { exit 1 }
$feed = Invoke-RestMethod -Uri "$feedOrigin/$Channel/latest.json" -Headers $headers
$feed | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $homeDir 'latest.json')
$asset = ($feed.url -split '/')[-1]
Invoke-WebRequest -Uri "$feedOrigin/bundles/$asset" -Headers $headers -OutFile (Join-Path $homeDir 'bundle.tar.gz')
$hash = (Get-FileHash (Join-Path $homeDir 'bundle.tar.gz') -Algorithm SHA256).Hash.ToLower()
if ($hash -ne $feed.sha256.ToLower()) { Write-Error -ErrorAction Continue 'bundle checksum mismatch'; exit 1 }
New-Item -ItemType Directory -Force -Path (Join-Path $homeDir 'bootstrap') | Out-Null
tar -xzf (Join-Path $homeDir 'bundle.tar.gz') -C (Join-Path $homeDir 'bootstrap')
if ($LASTEXITCODE -ne 0) { exit 1 }
& $py (Join-Path $homeDir 'bootstrap\packaging\install.py') --home $homeDir
