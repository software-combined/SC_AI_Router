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
the managed installer currently provisions a macOS `launchd` service, with
Linux `systemd` user units documented below.

### Arch Linux: install the ChatGPT desktop app first

The adapter routes the Codex picker, so it needs the ChatGPT desktop app
(`codex-desktop`) installed and signed in before the router is useful:

```sh
yay -S codex-desktop-git   # provides `codex-desktop`
```

This is an AUR repack of OpenAI's official Linux build
(`ilysenko/codex-desktop-linux`). Launch it once, sign in with ChatGPT,
then install the router. The `openai-codex-bin` CLI package is optional
and not required. (Use `paru -S codex-desktop-git` if you prefer paru.)

### Linux: run the router as a systemd user service

The macOS installer writes `launchd` plists; on Linux, provision the
equivalent pair of `systemd` user units instead. With `port` and `token`
from `~/.codex/mixed-model-router/mixed-router-state.json`:

`~/.config/systemd/user/codex-mixed-model-router.service`:

```ini
[Unit]
Description=SC Codex mixed model router (loopback)
After=network.target

[Service]
ExecStart=/usr/bin/python3.14 -m codex_router
WorkingDirectory=%h/.codex/mixed-model-router/current
Environment=ROUTER_HOME=%h/.codex/mixed-model-router
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

`~/.config/systemd/user/codex-mixed-model-router-update.service`:

```ini
[Unit]
Description=SC Codex mixed model router - check for updates

[Service]
Type=oneshot
ExecStart=/usr/bin/python3.14 /path/to/SC_OpenRouter_adapter/packaging/install.py --check-update
Environment=ROUTER_HOME=%h/.codex/mixed-model-router
```

`~/.config/systemd/user/codex-mixed-model-router-update.timer`:

```ini
[Unit]
Description=Check for SC mixed model router updates every 15 minutes

[Timer]
OnBootSec=5min
OnUnitActiveSec=15min

[Install]
WantedBy=timers.target
```

Then:

```sh
systemctl --user daemon-reload
systemctl --user enable --now codex-mixed-model-router.service
systemctl --user enable --now codex-mixed-model-router-update.timer
```

Note the service runs `python3.14 -m codex_router` directly: it needs an
`openrouter.key` in the router home first (the installer creates the empty
placeholder and prints the path), otherwise the router exits until a key
is pasted in. Verify with the `/health` URL from the state file, and
restart the ChatGPT desktop app after the installer writes the Codex
config block — it reads `config.toml` at startup.

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
OpenRouter-billed GPT rows stay out of the Codex picker so the
subscription GPT rows stand alone; requesting one directly still routes
to OpenRouter. The Claude listing will apply the mirror rule to
OpenRouter-billed Anthropic rows when it lands.
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
titles and the approvals reviewer are unavailable; the installer writes
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
