<img src="docs/assets/sc-logo-wide.png" alt="Software Combined" width="420">

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
the private router repository only while updates ride the transitional
GitHub feed, and an OpenRouter API key for OpenRouter models. Once a host
has polled a release that carries the feed token it updates from the
token-gated feed at `dist.softwarecombined.com` and needs neither `gh` nor
repository access.

## Platform support

| Platform | Router | Managed installer |
|---|---|---|
| macOS | Supported | Supported (`launchd` user agent) |
| Linux with a systemd user manager | Supported | Supported (`systemd` user units) |
| Windows 11 x64 | Lifecycle-proven, pending sign-out/in | Per-user Scheduled Tasks: install, scheduled update, rollback and uninstall passed on a staff machine on 2026-09-10; sign-out/in re-launch pending. Staff rollout stays gated on the remaining sign-out/in proof |

Windows support is per-user Scheduled Tasks; see the Windows section below
and `docs/compatibility.md` for the acceptance record. A Linux install needs a
running systemd user manager: run it in the signed-in desktop session, not
over a bare SSH shell without one.

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

Without repository access, install from the feed with the bootstrap: with
the feed token in `SCG_FEED_TOKEN`, download
`https://dist.softwarecombined.com/bootstrap/bootstrap.sh` with the
`X-SCG-Feed-Token` header and run it. It fetches the pinned Python runtime
and the release bundle from the feed, verifies both checksums, writes the
token for the updater, and installs; updates then need no `gh`.

Otherwise, recipients install from the published release channel, not from
a checkout.
A maintainer hands you the release directory; install from its feed file
so the installer verifies the published bundle instead of fetching the
default feed:

```sh
python3 packaging/install.py --feed file://$HANDOFF_DIR/latest.json
```

The exact download location is named at publication time.
Before installing on a machine that has run the router before, check for
a stale feed pin or beta channel: `cat` the `feed` and `channel` files in
the router home (a leftover `feed` file overrides the channel), see
[Linux upgrade and verification](docs/linux-upgrade.md). `--preflight`
checks install prerequisites but does not read those files.

Maintainers build a versioned bundle and install from it:

```sh
python3 packaging/release.py --out dist
python3 packaging/install.py --feed file://$PWD/dist/latest.json
```

The installer asks for nothing interactively. It verifies the bundle,
self-tests it, writes the service, and inserts the Codex config block.
If no key is configured it creates an empty key file and tells you to
paste the key in, then re-run. Restart Codex afterwards. `packaging/install.sh`
is the same installer for POSIX shells; `packaging/install.ps1` is the
PowerShell wrapper for Windows below.

## Install on Windows

Without repository access, run the feed bootstrap instead of this path:
download `https://dist.softwarecombined.com/bootstrap/bootstrap.ps1` with
the `X-SCG-Feed-Token` header and run it with `SCG_FEED_TOKEN` set; it
needs no `gh` and no Python preinstalled, because it fetches and verifies
both from the feed.

Requirements: Windows 11 x64, Python 3.14 from python.org (the installer
finds it through the `py` launcher; never rely on the bare `python` alias,
which a stock profile resolves to the Microsoft Store stub), GitHub CLI
signed in as this user, and the Codex desktop app. Run in your signed-in
desktop session from PowerShell:

From the same handed-off release directory, in your signed-in desktop
session:

```powershell
py -3 packaging/install.py --feed file://$HANDOFF_DIR/latest.json
```

`packaging/install.ps1` is the same installer for PowerShell (it ships in
release bundles built after this change; older bundles carry the installer
only). The installer registers two per-user Scheduled Tasks: `CodexMixedModelRouter`
runs at your logon (plus a one-minute
recovery trigger) as the signed-in user with least privilege and no stored
password, and `CodexMixedModelRouterUpdate` checks for releases every
fifteen minutes. Both run `pythonw.exe`, so no console window appears, and
their output goes to `logs\launchd.log` and `logs\update.log` under the
router home. The router home, key file and state file are restricted to the
installing user with `icacls`, verified after every write; the key file is
checked again at every read.

```powershell
schtasks /query /tn CodexMixedModelRouter /fo list /v
icacls $env:USERPROFILE\.codex\mixed-model-router\openrouter.key
```

Windows has no socket activation: during an update the outgoing router
drains, then the task relaunches into the new release, so a connection
attempted in that window (about fifteen seconds) fails until the new process
binds. Uninstall ends both tasks before deleting them.

## Updating

Releases install themselves within about fifteen minutes, whether or not
the router is busy, and the outgoing process finishes the requests it has
already accepted, so an in-flight chat is not dropped and nothing waits for
an idle window. On macOS launchd holds the listening socket, so new
connections queue for the incoming process too; on Linux there is no socket
activation, so a connection attempted mid-handover fails until the new
process binds the port. To update now, re-run the installer with
`--check-update`. Machines on the `beta` channel follow pre-releases.
After an update that adds a picker model, a desktop dialog offers to quit and reopen Codex (the
macOS app, the Windows Store app, or the Linux preview app when it is
installed) so the new models load, with a "Later" button for anyone who
would rather keep working. Where the desktop app is not installed, the
restart button simply does nothing.

Each tagged release publishes to the token-gated feed at
`https://dist.softwarecombined.com/<channel>/latest.json` as well as to
GitHub Releases. A host that has received a feed token polls the feed with
the `X-SCG-Feed-Token` header and no longer needs `gh` or repository
access; a host without one keeps using the GitHub route, so old and new
installs coexist. `logs/update.log` records the source of each install.

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
The Codex picker lists both routes for the GPT twins: the ChatGPT
subscription rows and the OpenRouter-billed Astra, Sol, Terra and Luna
rows labelled `· OpenRouter`. Picking a subscription row keeps the
ChatGPT subscription; picking its OpenRouter row bills the API key, so
an exhausted allowance still leaves those models selectable. In
no-subscription mode (`openai_mode: none`) only the OpenRouter rows
list. This is Codex-only: nothing changes for Claude Code, whose
`GET /v1/models` listing already includes every OpenRouter registry row,
and the `--client claude` catalogue merge keeps its mirror rule for
OpenRouter-billed Anthropic rows.
In Claude Code, point `ANTHROPIC_BASE_URL` at the router and choose
the model with `ANTHROPIC_MODEL`; see `docs/claude-code.md`.

Thread titles, descriptions and summaries are generated by a helper turn
on the subscription model. When the ChatGPT allowance is exhausted those
helpers are refused as well, and the client falls back to a slice of the
prompt as the title. Setting `openai_helper_fallback` to `true` in
`mixed-router-state.json` (default off, then restart the router) answers
just those helper turns from the OpenRouter twin row
(`openai/gpt-5.6-luna`), so generated titles survive an exhausted
allowance; the helper prompt then reaches OpenRouter and bills that key.
The portco allowlist still gates that row, and ordinary turns keep their
refusal.

## Costs

OpenAI models use the ChatGPT subscription. OpenRouter models bill the
API key per request. There is no local spend cap; watch usage in the
OpenRouter dashboard.

## Providers

One definition per upstream lives in `ai_router/provider_defs.py`: host,
endpoint prefixes, where its key resolves from, its live model catalogue,
its key-info endpoint, and its failure dialect. OpenRouter is the built-in
external provider; `openai` (the ChatGPT backend) and `anthropic`
(`api.anthropic.com`) are the subscription definitions that carry no router
key.

Several external providers can serve at once: each keeps its own owner-only
key file, its own picker label (`Vendor: Model · <Label>`), and its own
fail-closed state, so one missing or rejected key never stops the others.
Adding one is a table entry plus registry rows, and the boundary test keeps
provider host and key names out of the rest of the runtime.

## Without a ChatGPT subscription

Install with `--openai-mode none --setup`: a native window asks for one
OpenRouter key, the subscription choice and an Everyday help or Coding help
starter for the
global instructions (the loopback page is used on hosts with no dialog tool),
and Codex uses a custom provider (`scg_router`) whose
`base_url` carries the per-install path token. No ChatGPT login is needed
and no subscription traffic is sent: Astra, Sol, Terra and Luna are served
from OpenRouter in the picker, a directly requested subscription id still
answers 400, native service paths answer 404 locally, and OpenRouter models
work with tools, compaction, and web search where the model supports it.
Server-side thread titles and the approvals reviewer are unavailable; the
installer writes `approvals_reviewer = "user"` inside the marked block.

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
The key file is owner-only on every platform: mode 600 on macOS and Linux,
and on Windows an `icacls` grant to the installing user alone, applied to
the router home before the key is written (so the state file holding the
loopback token inherits it), with the key checked again at every read; a
widened ACL makes the router refuse the key. Supervisor logs (`launchd.log`, `update.log`) rotate
at service start (1 MB each, two backups on macOS and Linux, one on Windows); the structured `router.jsonl`
rotates at 5 MB with three backups.

## Links

Claude Code setup: `docs/claude-code.md`. Operator guide: `docs/operations.md`. Compatibility matrix:
`docs/compatibility.md`. Adding a model: `docs/adding-a-model.md`.

Monthly model allocation review: `model-allocation-review-process.md` (the process) and
`model-allocation-suggestion.md` (its output, refreshed on the 1st of each month).

## Licensing

SC Router is source-available under the [PolyForm Shield License
1.0.0](LICENSE). It is not an OSI-approved open-source licence.

You can use, modify and redistribute the software subject to that licence,
and internal use by organisations is permitted as long as the use complies
with it. PolyForm Shield restricts using the software to provide products or
services that compete with the licensor or its affiliates, including
products and services they provide using this software. Uses outside the
licence may be available under a separate commercial agreement with Software
Combined, as described in [COMMERCIAL_LICENSE.md](COMMERCIAL_LICENSE.md).

Attribution and licence notices must be preserved as the licence requires.
Third-party material and its terms are listed in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

- Licence: [LICENSE](LICENSE)
- Commercial licensing: [COMMERCIAL_LICENSE.md](COMMERCIAL_LICENSE.md)
- Official licence text: <https://polyformproject.org/licenses/shield/1.0.0>

Copyright 2026 Software Combined Pty Ltd. Primary author and maintainer:
Cyril Allart <cyril@softwarecombined.com>.

## Runtime files

A manual install copies ONLY these files beside the private state
directory at an idle boundary:
`ai_router/router.py`,
`ai_router/providers.py`,
`ai_router/claude.py`,
`ai_router/registry.py`,
`ai_router/credentials.py`,
`ai_router/tool_adapter.py`,
`ai_router/agent_handoffs.py`, `ai_router/sse.py`,
`ai_router/capabilities.py`,
`ai_router/compaction.py`,
`ai_router/standalone_outputs.py`,
`ai_router/discovered.py`,
`ai_router/errors.py`,
`ai_router/feed_verify.py`,
`ai_router/candidate.py`,
`ai_router/setup.py`,
`ai_router/key_store.py`,
`ai_router/setup_page.py`,
`ai_router/key_dialog.py`,
`ai_router/key_prompt.py`,
`ai_router/runtime.py`,
`ai_router/catalogue.py`,
`ai_router/local_services.py`,
`ai_router/live_refresh.py`,
`ai_router/models.py`,
`ai_router/apply_catalogue.py`,
`ai_router/activation.py`,
`ai_router/__init__.py`,
`ai_router/__main__.py`,
`ai_router/model_metadata.py`,
`ai_router/model_refresh.py`,
`ai_router/winacl.py`,
`ai_router/image_items.py`,
`ai_router/model_policy.py`,
`ai_router/subscription_roster.py`,
`ai_router/retired_slugs.py`,
`ai_router/clients/__init__.py`,
`ai_router/clients/codex.py`,
`ai_router/transport.py`,
`ai_router/subscription_fallback.py`,
`ai_router/provider_defs.py`,
`ai_router/upstream.py`,
`ai_router/protocols/__init__.py`,
`ai_router/protocols/responses.py`,
`ai_router/protocols/messages.py`,
`ai_router/models.json`,
`ai_router/openrouter_base_instructions.txt`,
`ai_router/agents.py`,
`ai_router/agents_general.txt`,
`ai_router/agents_dev.txt`,
`tools/probe_codex_runtime.py`,
`tools/global_instructions.py`,
`tools/disable.py`. The installer also places `packaging/router_launch.py`
as `router_launch.py` beside the state directory and points the service at
it, so restarts follow the pointer without symlinks. Never copy state,
activation, catalogue, backup, or log files.
