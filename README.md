# SC_Codex_openRouter_adapter

Local Codex model router: ChatGPT subscription plus OpenRouter models in one
picker. Run with `python3.14 -m codex_router`. See `docs/` for operator and
compatibility notes; `plans/` holds the hardening roadmap. Full staff
documentation lands with the installer release.

## Setup

Requirements: Python 3.14 or newer, the Codex app (desktop, CLI, or IDE
extension), and an OpenRouter API key. Clone the repository and run the suite
from the repo root:

```sh
python3.14 -m unittest discover -s tests -t .
```

Every setup then follows the same three steps: copy ONLY the runtime files
beside the private state directory, add the config block to the Codex
configuration, and restart Codex and check
`http://127.0.0.1:<port>/<token>/health` (port and token from
`mixed-router-state.json`) for `{"status": "ok", ...}`. The runtime files are
`codex_router/router.py`,
`codex_router/providers.py`,
`codex_router/registry.py`,
`codex_router/credentials.py`,
`codex_router/tool_adapter.py`,
`codex_router/capabilities.py`,
`codex_router/compaction.py`,
`codex_router/runtime.py`,
`codex_router/catalogue.py`,
`codex_router/update_reasoning_catalog.py`,
`codex_router/apply_catalogue.py`,
`codex_router/__init__.py`,
`codex_router/__main__.py`,
`codex_router/models.json`,
`codex_router/openrouter_base_instructions.txt`,
`tools/probe_codex_runtime.py`,
`tools/disable.py`. Never copy state, activation, catalogue, backup, or log
files.

### macOS

`packaging/install.sh` runs the suite and prints the copy step. The router
runs as the LaunchAgent `com.local.codex-mixed-model-router`
(`python3.14 -m codex_router` with `ROUTER_HOME` set, working directory the
release). State lives in `~/.codex/mixed-model-router`. Machines installed
before the installer release still run the legacy flat-file layout until
they are reinstalled.

### Windows

`packaging/install.ps1` runs the suite and prints the copy step. Supply the
key through the OpenCode credential file today. Until the scheduled-task
service from the installer release exists, start the router by hand
(`python -m codex_router` with `ROUTER_HOME` set). Unverified on a named
test machine.

### Linux

No packaging script ships yet; follow the three steps above by hand and run
the router under your process supervisor (a systemd user unit that restarts
on failure and keeps logs is the recommended shape). The Linux path is
unverified: report issues with the distro and Python build.

## Credentials

The router reads the OpenRouter key per request, in this order: the
`OPENROUTER_API_KEY` environment variable, an `openrouter.key` file beside
the state directory (owner-only, mode 600), then the OpenCode credential
file. Replace the file to rotate with no restart. Never pass the key on a
command line or write it into the service definition.

## Operation

`ROUTER_HOME` (default `~/.codex/mixed-model-router`) holds
`mixed-router-state.json`, `activation.json`, and `logs/router.jsonl` (5 MB,
three rotations). The code may live anywhere. Startup refuses to serve if the
state file is missing or mistyped and prints which keys are wrong.

## Adding a model

Add one row to `codex_router/models.json`, then run
`python3.14 -m codex_router.catalogue --check <catalogue>` (or the Plan 039
dynamic path), restart the router, and probe the new model once at low
effort. Reviewers should reject slug literals anywhere outside the registry.
