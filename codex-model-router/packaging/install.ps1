# Staff install (Windows): stage canonical source beside private state.
# Fails closed; key federated via $env:OPENROUTER_API_KEY, never committed.
$ErrorActionPreference = 'Stop'
$src = Split-Path -Parent $PSScriptRoot
Write-Host "Source: $src"
Set-Location $src
python -m unittest test_mixed_router test_tool_adapter test_capabilities test_compaction test_apply_catalogue test_packaging
if ($LASTEXITCODE -ne 0) { exit 1 }
Write-Host 'Source tests passed. Copy ONLY mixed_router.py tool_adapter.py capabilities.py compaction.py probe_codex_runtime.py update_reasoning_catalog.py apply_catalogue.py disable.py beside the local private state at an idle boundary; never copy state, activation, catalogue, backup or log files.'
Write-Host 'Set $env:OPENROUTER_API_KEY from the staff secret store; never commit keys.'
