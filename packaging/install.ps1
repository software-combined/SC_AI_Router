# Thin wrapper: the installer lives in install.py (Plan 041).
# Plan 057 W6: never run the bare `python` alias, which a stock Windows 11
# profile resolves to the Microsoft Store stub. The py launcher ships with
# every python.org install; install.py itself then locates Python 3.14.
$ErrorActionPreference = 'Stop'
$installer = Join-Path $PSScriptRoot 'install.py'
if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 $installer @args
} elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
    & python3 $installer @args
} else {
    # -ErrorAction Continue: under $ErrorActionPreference = 'Stop' a bare
    # Write-Error would terminate before the exit code matching install.py.
    Write-Error -ErrorAction Continue 'No Python launcher found: install Python 3.14 from python.org (it includes the py launcher), then re-run.'
    exit 2
}
exit $LASTEXITCODE
