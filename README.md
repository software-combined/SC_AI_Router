# Model router

A small program on your computer that serves the Codex picker and Claude
Code from one place, offering subscription models and approved
OpenRouter models side by side. The two logins stay separate:
subscription traffic keeps using the existing ChatGPT or Claude
sign-in, and OpenRouter traffic uses an API key that never leaves
your machine.

## Requirements

The Codex app and/or Claude Code, Python 3.14 (the installer finds it or
tells you how to get it), GitHub CLI (`gh`) signed in with read access to
the private router repository while updates ride the transitional GitHub
feed, and an OpenRouter API key for OpenRouter models.

## Platform support

| Platform | Router | Managed installer |
|---|---|---|
| macOS | Supported | Supported (`launchd` user agent) |
| Linux with a systemd user manager | Supported | Supported (`systemd` user units) |
| Windows | Runs under development | Not supported yet: the installer refuses before changing anything |

Windows support lands with Plan 057; until its acceptance passes, do not run
the installer on Windows. A Linux install needs a running systemd user
manager: run it in the signed-in desktop session, not over a bare SSH shell
without one.

### Linux: managed systemd user services

Run the installer below in your signed-in desktop user session. It checks
that the user systemd manager is available before installation, writes the
router service and update timer, and enables them for future logins. It
does not create a root service or enable lingering.
The repository is private: install GitHub CLI (`gh`) and sign in as this
same user with repository read access. Scheduled downloads use that login.

Older symlink installations are migrated to `router_launch.py` and a
`current` pointer file. Existing state, credentials and model settings are
preserved. The installer replaces legacy updater commands pointing at a
checkout or local feed with the installed updater and normal release channel.
A pre-existing `feed` file in the router home still explicitly overrides
that channel; see [Linux upgrade and verification](docs/linux-upgrade.md).

```sh
systemctl --user status codex-mixed-model-router.service
systemctl --user list-timers codex-mixed-model-router-update.timer
journalctl --user -u codex-mixed-model-router-update.service
```

Updates do not wait for idle traffic; systemd restarts the router through
the stable launcher and the outgoing process finishes the requests it has
already accepted. Linux has no socket activation, so connections attempted
during the handover fail until the new process binds the port. The service allows 150 seconds for the 120-second drain.
The first update check runs five minutes after installation, then fifteen
minutes after each check completes. Restart Codex after catalogue changes.

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

## Install on macOS or Linux

Recipients install from the published release channel, not from a checkout:

```sh
python3 packaging/install.py
```

Maintainers build a versioned bundle and install from it:

```sh
python3 packaging/release.py --out dist
python3 packaging/install.py --feed file://$PWD/dist/latest.json
```

The installer asks for nothing interactively. It verifies the bundle,
self-tests it, writes the service, and inserts the Codex config block.
If no key is configured it creates an empty key file and tells you to
paste the key in, then re-run. Restart Codex afterwards. `packaging/install.sh`
is the same installer for POSIX shells; `packaging/install.ps1` is reserved
for the future Windows backend and must not be used yet.

## Updating

Releases install themselves within about fifteen minutes, whether or not
the router is busy, and the outgoing process finishes the requests it has
already accepted, so an in-flight chat is not dropped and nothing waits for
an idle window. On macOS launchd holds the listening socket, so new
connections queue for the incoming process too; on Linux there is no socket
activation, so a connection attempted mid-handover fails until the new
process binds the port. To update now, re-run the installer with
`--check-update`. Machines on the `beta` channel follow pre-releases.

## Choosing a model

Switch models mid-thread from the picker; the same thread continues
with its text history and tools intact, subject to the new model's
limits. Readable summaries carry over; opaque native compaction
replays as a visible note rather than readable context. Image blocks
do not carry over to text-only models. A model tool-count ceiling
(Grok, 350 tools) loads tools on demand instead of failing: the turn
goes out with the search tool, already-found tools stay, and the rest
resolve through search. Grok image turns run text-only with a short
note where each image was. Each turn routes on its own model,
so if one model reports it is at capacity, switch to another
and carry on. Reasoning levels differ per model and the thread's effort
carries over; an effort the new model does not support is rejected with
the allowed levels (change effort before switching). Models labelled
Preview in the picker are not yet verified: they work, but report
anything odd.
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
token, and logs carry request metadata, never keys or tokens. Subscription headers never accompany OpenRouter requests; the key travels only as a per-request `Bearer` header.
The key file is owner-only on macOS and Linux; on Windows the installer
refuses before writing one, and Windows key protection lands with the
Windows backend. Supervisor logs (`launchd.log`, `update.log`) rotate
at service start (1 MB each, two backups); the structured `router.jsonl`
rotates at 5 MB with three backups.

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
`codex_router/agent_handoffs.py`, `codex_router/sse.py`,
`codex_router/capabilities.py`,
`codex_router/compaction.py`,
`codex_router/discovered.py`,
`codex_router/errors.py`,
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
`codex_router/model_metadata.py`,
`codex_router/winacl.py`,
`codex_router/model_policy.py`,
`codex_router/clients/__init__.py`,
`codex_router/clients/codex.py`,
`codex_router/transport.py`,
`codex_router/protocols/__init__.py`,
`codex_router/protocols/responses.py`,
`codex_router/protocols/messages.py`,
`codex_router/models.json`,
`codex_router/openrouter_base_instructions.txt`,
`tools/probe_codex_runtime.py`,
`tools/global_instructions.py`,
`tools/disable.py`. The installer also places `packaging/router_launch.py`
as `router_launch.py` beside the state directory and points the service at
it, so restarts follow the pointer without symlinks. Never copy state,
activation, catalogue, backup, or log files.
