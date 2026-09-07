# Thin wrapper: the installer lives in install.py (Plan 041).
$ErrorActionPreference = 'Stop'
& python "$PSScriptRoot/install.py" @args
