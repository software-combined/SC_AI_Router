# SC_Codex_openRouter_adapter

Local Codex model router: ChatGPT subscription plus OpenRouter models in one
picker. Run with `python3.14 -m codex_router`. See `docs/` for operator and
compatibility notes; `plans/` holds the hardening roadmap. Full staff
documentation lands with the installer release.

## Operation

`ROUTER_HOME` (default `~/.codex/mixed-model-router`) holds
`mixed-router-state.json`, `activation.json`, and `logs/router.jsonl` (5 MB,
three rotations). The code may live anywhere. Startup refuses to serve if the
state file is missing or mistyped and prints which keys are wrong.
