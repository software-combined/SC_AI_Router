# Model router

A small program on your computer that serves the Codex picker and Claude
Code from one place, offering subscription models and approved
OpenRouter models side by side. The two logins stay separate:
subscription traffic keeps using the existing ChatGPT or Claude
sign-in, and OpenRouter traffic uses an API key that never leaves
your machine.

## Requirements

The Codex app and/or Claude Code, Python 3 (the installer finds or asks for a
3.14 interpreter to run the router itself), and an OpenRouter API key
for OpenRouter models. The router itself runs on macOS, Windows, and Linux;
the managed installer currently provisions a macOS `launchd` service.

## Install

Build a versioned bundle and install it:

```sh
python3 packaging/release.py --out dist
python3 packaging/install.py --feed file://$PWD/dist/latest.json
```

The installer asks for nothing interactively. It verifies the bundle,
self-tests it, writes the service, and inserts the Codex config block.
If no key is configured it creates an empty key file and tells you to
paste the key in, then re-run. Restart Codex afterwards.

## Updating

Releases install themselves within about fifteen minutes while the
router is idle. The router finishes in-flight requests, then swaps to
the new release. To update now, re-run the installer with
`--check-update`. Machines on the `beta` channel follow pre-releases.

## Choosing a model

Start a fresh task when switching providers. Reasoning levels differ
per model; unavailable levels are hidden. Models labelled Preview in
the picker are not yet verified: they work, but report anything odd.
In Claude Code, point `ANTHROPIC_BASE_URL` at the router and choose
the model with `ANTHROPIC_MODEL`; see `docs/claude-code.md`.

## Costs

OpenAI models use the ChatGPT subscription. OpenRouter models bill the
API key per request. There is no local spend cap; watch usage in the
OpenRouter dashboard.

## Without a ChatGPT subscription

Install with `--openai-mode none --setup`, paste one OpenRouter key into
the setup window, and Codex uses a custom provider (`scg_router`) whose
`base_url` carries the per-install path token. No ChatGPT login is needed
and no subscription traffic is sent: OpenAI models answer 400, native
service paths answer 404 locally, and OpenRouter models work with tools,
compaction, and web search where the model supports it. Server-side thread
titles and the approvals reviewer are unavailable; set
`approvals_reviewer = "user"` inside the marked block.

## Troubleshooting

Logs live under `logs/` beside the state directory. Check health at
`http://127.0.0.1:<port>/<token>/health` with the port and token from
`mixed-router-state.json` (do not share that URL). A 400 means the
model, payload, or local key configuration is invalid. A 409 means the
provider cannot serve the request, for example an unsupported reasoning effort after switching models (the message names the allowed efforts). A 503 with `Retry-After` means the
router is draining for an update; retry. If the router stays down,
reinstall the previous release at an idle moment.

## Uninstall

Run the installer with `--uninstall`. It removes the config block and
the services and leaves the state directory, including the key file and
bearer token, in place for you to delete.

## Security

The router listens on loopback only. Each install generates its own
token, the key file is owner-only, and logs carry request metadata,
never keys or tokens. Subscription headers never accompany OpenRouter requests; the key travels only as a per-request `Bearer` header.

## Links

Claude Code setup: `docs/claude-code.md`. Operator guide: `docs/operations.md`. Compatibility matrix:
`docs/compatibility.md`. Adding a model: `docs/adding-a-model.md`.

## Runtime files

A manual install copies ONLY these files beside the private state
directory at an idle boundary:
`codex_router/router.py`,
`codex_router/providers.py`,
`codex_router/claude.py`,
`codex_router/registry.py`,
`codex_router/credentials.py`,
`codex_router/tool_adapter.py`,
`codex_router/capabilities.py`,
`codex_router/compaction.py`,
`codex_router/discovered.py`,
`codex_router/feed_verify.py`,
`codex_router/candidate.py`,
`codex_router/setup.py`,
`codex_router/runtime.py`,
`codex_router/catalogue.py`,
`codex_router/local_services.py`,
`codex_router/live_refresh.py`,
`codex_router/models.py`,
`codex_router/apply_catalogue.py`,
`codex_router/activation.py`,
`codex_router/__init__.py`,
`codex_router/__main__.py`,
`codex_router/models.json`,
`codex_router/openrouter_base_instructions.txt`,
`tools/probe_codex_runtime.py`,
`tools/global_instructions.py`,
`tools/disable.py`. The installer also places `packaging/router_launch.py`
as `router_launch.py` beside the state directory and points the service at
it, so restarts follow the pointer without symlinks. Never copy state,
activation, catalogue, backup, or log files.
