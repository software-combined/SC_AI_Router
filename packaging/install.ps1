# Staff install (Windows): stage canonical source beside private state.
# Fails closed; key federated via $env:OPENROUTER_API_KEY, never committed.
$ErrorActionPreference = 'Stop'
$src = Split-Path -Parent $PSScriptRoot
Write-Host "Source: $src"
Set-Location $src
python -m unittest discover -s tests -t .
if ($LASTEXITCODE -ne 0) { exit 1 }
Write-Host 'Source tests passed. Copy ONLY codex_router/router.py codex_router/providers.py codex_router/registry.py codex_router/credentials.py codex_router/tool_adapter.py codex_router/capabilities.py codex_router/compaction.py codex_router/runtime.py codex_router/catalogue.py codex_router/local_services.py codex_router/update_reasoning_catalog.py codex_router/apply_catalogue.py codex_router/__init__.py codex_router/__main__.py codex_router/models.json codex_router/openrouter_base_instructions.txt tools/probe_codex_runtime.py tools/disable.py beside the local private state at an idle boundary; never copy state, activation, catalogue, backup or log files.'
Write-Host 'Key order: $env:OPENROUTER_API_KEY, then openrouter.key beside the state directory, then OpenCode. The installer (Plan 041) creates the key file.'
