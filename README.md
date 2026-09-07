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

## Adding a model

Add one row to `codex_router/models.json`, then run
`python3.14 -m codex_router.catalogue --check <catalogue>` (or the Plan 039
dynamic path), restart the router, and probe the new model once at low
effort. Reviewers should reject slug literals anywhere outside the registry.

## Request routing and safety

OpenAI routes keep the ChatGPT subscription authentication. Only OpenRouter
routes attach the federated OpenRouter key, sent as a fresh `Bearer` header
built per request; subscription headers never accompany OpenRouter requests.

Reasoning effort is validated before anything is sent: requesting an effort a
model does not support fails loudly with `409` naming the model and its
allowed efforts, never silently downgrades. Mid-thread model switches carry
the old effort over, so change effort before switching models.

Compaction is transparent: a plain-language summary with exact values quoted
verbatim, plus retained recent messages. Empty summaries are rejected with
`409`. Request URLs and upstream credentials never enter access logs, and no
payload text enters the event log.

## Verify

```sh
python3.14 -m unittest discover -s tests -t .
python3.14 -m compileall -q codex_router tools tests
python3.14 tools/check_source_limits.py
```

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `409` naming a fresh task | Opaque history the model cannot read | Start a fresh task |
| `400` on every OpenRouter request | Missing or mistyped state keys, or payload shape | Check the router log event, then state keys |
| Chat shows first sentence as title | Title generation call failed | Retry in a fresh task |
