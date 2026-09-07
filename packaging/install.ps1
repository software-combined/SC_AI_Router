# Staff install (Windows): stage canonical source beside private state.
# Fails closed; key federated via $env:OPENROUTER_API_KEY, never committed.
$ErrorActionPreference = 'Stop'
$src = Split-Path -Parent $PSScriptRoot
Write-Host "Source: $src"
Set-Location $src
python -m unittest discover -s tests -t .
if ($LASTEXITCODE -ne 0) { exit 1 }
Write-Host 'Source tests passed. Copy ONLY codex_router/router.py codex_router/tool_adapter.py codex_router/capabilities.py codex_router/compaction.py tools/probe_codex_runtime.py codex_router/update_reasoning_catalog.py codex_router/apply_catalogue.py tools/disable.py beside the local private state at an idle boundary; never copy state, activation, catalogue, backup or log files.'
Write-Host 'Set $env:OPENROUTER_API_KEY from the staff secret store; never commit keys.'
