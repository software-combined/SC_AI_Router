<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/sc-logo-wide-dark.png">
    <img alt="Software Combined" src="docs/assets/sc-logo-wide.png" width="380">
  </picture>
</p>

<h1 align="center">SC Unlimited AI</h1>

<p align="center">
One local endpoint for Codex and Claude Code. Your ChatGPT or Claude subscription models and OpenRouter models, side by side in the picker, with the billing kept apart.
</p>

<p align="center">
  <a href="https://github.com/software-combined/SC_OpenRouter_adapter/actions/workflows/check.yml"><img alt="Checks on GitHub Actions" src="https://img.shields.io/badge/checks-GitHub_Actions-blue"></a>
  <a href="https://github.com/software-combined/SC_Unlimited_ai/releases/latest"><img alt="Releases on GitHub" src="https://img.shields.io/badge/releases-GitHub-blue"></a>
  <a href="LICENSE"><img alt="Licence: Apache-2.0" src="https://img.shields.io/badge/licence-Apache--2.0-blue"></a>
  <img alt="Python 3.14, standard library only" src="https://img.shields.io/badge/python-3.14%20stdlib%20only-3776AB">
</p>

SC Unlimited AI is a small service that runs on your own machine. It speaks the
Codex and Claude Code wire protocols on a loopback port, so both clients see
one model list: the models your existing ChatGPT or Claude sign-in already
includes, plus approved models billed to an OpenRouter API key. You choose
the model per turn from the client's normal picker and can switch
mid-thread.

The billing split is strict. Subscription models keep using the client's
own sign-in, OpenRouter models use a key stored only on your machine, and
subscription credentials never accompany a request billed to OpenRouter.

- **One router, two clients.** Codex (desktop app or CLI) and Claude Code
  attach to the same service, with per-turn model selection.
- **Billing you can see.** Rows billed to the OpenRouter key carry an
  `· OpenRouter` suffix; every other row uses the subscription.
- **Small trust surface.** Loopback only, one per-install path token, an
  owner-only key file, and no request content in logs.
- **No dependencies.** Python 3.14 standard library at runtime; the
  bootstrap brings its own pinned interpreter.
- **Self-updating.** Every install follows a public, token-free release feed
  on macOS, Linux and Windows.

## What it looks like

<p align="center">
  <img src="docs/assets/codex-picker-openrouter-row.png" alt="The Codex composer with an OpenRouter-billed Claude row selected" width="760">
</p>
<p align="center"><sub>The Codex composer with an OpenRouter-billed row selected. Rows billed to the API key carry the <code>· OpenRouter</code> suffix; the rest use the subscription.</sub></p>

<table align="center">
  <tr>
    <td align="center"><img src="docs/assets/key-window-macos.png" alt="The first-run key window on macOS" width="400"></td>
    <td align="center"><img src="docs/assets/update-dialog-macos.png" alt="The update notice on macOS" width="400"></td>
  </tr>
  <tr>
    <td align="center"><sub>The first-run key window. The key is checked before it is saved and kept only on that computer.</sub></td>
    <td align="center"><sub>The update notice. Updates install themselves; this dialog only appears when new picker models need a client restart.</sub></td>
  </tr>
</table>

## Platform support

| Platform | Service | Status |
|---|---|---|
| macOS | launchd user agent | Supported |
| Linux with a systemd user manager | systemd user units | Supported |
| Windows 11 x64 | per-user Scheduled Tasks | Install, update, rollback and uninstall verified; sign-out and sign-in relaunch still to be confirmed |

Linux needs a running systemd user manager in the signed-in desktop session;
the installer refuses a bare SSH session without one. Acceptance evidence and
the client versions it was recorded against live in
[docs/compatibility.md](docs/compatibility.md).

## Requirements

- Codex (desktop app or CLI) and/or Claude Code, installed and signed in.
- Python 3.14 for a source install. The bootstrap supplies a pinned runtime,
  so no system Python 3.14 is needed; macOS and Linux still need any
  `python3`, plus `curl`, `tar` and `shasum`. Windows needs no Python.
- An OpenRouter API key for any model billed to OpenRouter.

The router home is `~/.codex/mixed-model-router`
(`%USERPROFILE%\.codex\mixed-model-router` on Windows). Installed releases,
state, the key file and logs live there.

## Install

### From a checkout

Needs Python 3.14. Build a local release, then install from it:

```sh
git clone https://github.com/software-combined/SC_Unlimited_ai.git
cd SC_Unlimited_ai
python3.14 packaging/release.py --out dist --url-base "file://$PWD/dist"
python3.14 packaging/install.py --feed "file://$PWD/dist/latest.json"
```

On Windows, run the same commands from PowerShell with the Python launcher:

```powershell
py -3 packaging/release.py --out dist --url-base "file://$PWD/dist"
py -3 packaging/install.py --feed "file://$PWD/dist/latest.json"
```

### Bootstrap for Software Combined staff

Ask a maintainer for the bootstrap script through Software Combined's
internal channels. It needs no GitHub account, token or repository access:
it downloads the pinned Python runtime and release bundle from the release
feed, verifies both checksums and installs the per-user service.

`--channel=beta` (PowerShell: `-Channel beta`) follows pre-releases.

### What the installer does

The installer verifies the bundle checksum, self-tests the runtime, installs
the per-user service and writes the client configuration. If the installed
service has no OpenRouter key, the key window opens by itself and collects
it; a coding agent running the install must never handle the key. If no
window appears, re-run the installer with `--setup`: it restarts the current
release with a fresh setup link. A key exported in the invoking shell is not
passed to the installed service, so it does not count as configured.
`ROUTER_NO_KEY_WINDOW=1` suppresses only the dialog for unattended installs.
Restart the client so it picks up the router's model catalogue.

The installer commands in this README run from a checkout. A bootstrap
install ships the same installer at
`<home>/releases/<version>/packaging/install.py`, where `<version>` is the
version recorded in `<home>/current`; run it with the pinned interpreter at
`<home>/runtime/python/bin/python3.14` (`python.exe` under the same path on
Windows) when the host has no Python 3.14 of its own. Before a checkout
install, `--preflight` reports missing prerequisites without writing
anything, and `--dry-run` shows what an install would do.

## Clients

Codex is attached by default: the installer registers the router as a model
provider and adds its catalogue, so the models appear in the picker after a
restart. `--clients both` attaches Codex and Claude Code; `--client none`
installs the service only.

Claude Code support is in preview. Point it at the router with the port and
token from `mixed-router-state.json` in the router home:

```sh
export ANTHROPIC_BASE_URL="http://127.0.0.1:<port>/<token>/"
export CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=true
```

Do not set `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN`; either would override
the subscription sign-in. See [docs/claude-code.md](docs/claude-code.md).

## Models and billing

Switch models mid-thread from the picker. The thread keeps its text history and
tools, subject to the new model's limits; image blocks do not carry over to
text-only models, and an unsupported reasoning level is rejected with the
levels the model accepts.

- Rows labelled `· OpenRouter` are billed to the OpenRouter API key. The
  remaining rows use the ChatGPT or Claude subscription.
- The GPT twins appear on both routes, so a subscription row and its
  OpenRouter twin are selectable side by side.
- Rows labelled Preview are usable but not yet verified; report anything odd.
- `--openai-mode none --setup` installs without a ChatGPT subscription and
  serves the picker entirely from OpenRouter.

There is no local spend cap. Subscription usage follows the client's plan and
OpenRouter usage is billed to the API key, so watch that spend in the
OpenRouter dashboard.

## Updates

Installs check their release feed for the selected channel. `stable` is the
default, and writing `beta` into the `channel` file in the router home selects
pre-releases. Switching channels by hand also means deleting `feed-serial`
beside it: the channels publish independently, so a higher serial left over
from the other channel refuses the new channel's updates. A `feed` file left
in the router home by an older install overrides the channel, so check or
remove it before relying on automatic updates. Checks run every four hours:
Linux also checks five minutes after the timer activates, and macOS checks
when the job loads. The feed needs no token, account or repository access,
and every bundle is verified by SHA-256 with version and identity checks;
the channel path also enforces the serial replay guard.

The outgoing process finishes requests it has already accepted before the
service restarts; on macOS launchd queues new connections through the
handover, while Linux and Windows refuse new connections until the new
process binds the port. After an update that adds picker models, the router
offers a client restart and never forces one; the prompts each platform
shows are described in
[docs/operations.md](docs/operations.md#new-model-notifications).

- `python3.14 packaging/install.py --check-update` runs one check now.
- `python3.14 packaging/install.py --version <version>` rolls back to a
  previously installed release.
- A `--feed <latest.json>` install uses that document for the run only; later
  checks follow the channel.

## Uninstall

`python3.14 packaging/install.py --uninstall` stops and removes the service,
the update schedule and the client configuration. The state directory, key
file and loopback token are left in place for you to delete.

## Common commands

```sh
# Install or reinstall for the invoking client (add --clients both to attach both).
# With no key installed the key window opens by itself; --setup forces it.
python3.14 packaging/install.py

# Read-only checks: prerequisites, then installed state (add --json for machines)
python3.14 packaging/install.py --preflight
python3.14 packaging/install.py --status

# Update now, or return to a previously installed version
python3.14 packaging/install.py --check-update
python3.14 packaging/install.py --version <installed version>

# Detach every client and remove the service (state and key stay behind)
python3.14 packaging/install.py --uninstall
```

`--check-update` is not a dry run: it installs a newer release when the channel
has one. If something looks wrong, start at
[docs/troubleshooting.md](docs/troubleshooting.md).

## Diagnostics

- Health: `http://127.0.0.1:<port>/<token>/health`, with the port and token
  from `mixed-router-state.json` in the router home. Keep that URL private.
- `python3.14 packaging/install.py --status` reports the installed version,
  service state, feed source, channel and key state without printing secrets.
- A 400 means the model, payload or local key configuration is invalid. A 409
  means the provider cannot serve the request, for example an unsupported
  reasoning level after a model switch; the message names the allowed levels.
  A refusal on an OpenRouter turn names the provider code when one is present
  and says to switch the thread back to the previous model or start a new
  thread.
- A 503 with `Retry-After` means the request was not served: either the router
  is draining for an update (`SERVER_DRAINING`) or an upstream 429 was mapped
  to a retryable answer (`UPSTREAM_RATE_LIMITED`). The JSON body names the
  code; retry after the delay.
- Logs live under `logs/` in the router home, and `update.log` records the
  source of each install.

## Security

- The router listens on `127.0.0.1` only, and every request needs the
  per-install path token.
- The provider key file is owner-only (mode 600 on macOS and Linux, an
  `icacls` grant to the installing user on Windows), and the router refuses a
  key file with a widened ACL.
- Subscription headers never accompany an OpenRouter request.
- Logs carry request metadata, never request content, keys or tokens.

Report a suspected vulnerability privately to
<cyril@softwarecombined.com>, as described in [SECURITY.md](SECURITY.md).

## Architecture

The request path is layered, and dependencies point inward:

| Layer | Owns |
|---|---|
| `ingress.py`, `relay.py`, `router.py` | Loopback HTTP: authentication and body limits, GET routes, upstream relay, drain and POST orchestration |
| `protocols/` | Responses and Messages method and path dispatch |
| `providers.py`, `claude.py` | Upstream adapters for subscription and OpenRouter traffic |
| `provider_defs.py`, `registry.py` | One definition per upstream; model facts |
| `transport.py`, `upstream.py` | Header rules, streaming and upstream failure policy |
| `packaging/` | Installer, `bundle.py` release lifecycle, per-OS service backends and updater |

- A new external provider is a definition plus registry rows. A provider with a
  different wire format is a new adapter, never a branch in the request path.
- Client, provider and operating system are separate concepts; installer
  orchestration calls one explicit platform backend.
- The full map, including the modules still moving between owners, is in
  [docs/architecture.md](docs/architecture.md).

## Contributing and development

Pull requests are welcome; [CONTRIBUTING.md](CONTRIBUTING.md) has the branch
rules and the gates. The short version:

```sh
python3.14 -m unittest discover -s tests -t .
python3.14 -m compileall -q ai_router tools tests packaging
python3.14 tools/check_source_limits.py
python3.14 tools/check_policy_scans.py
```

The runtime is Python 3.14 with the standard library only; installer scripts
stay Python 3.9-compatible. Branches start from `develop`, pull requests
target `develop`, and user-visible changes update `CHANGELOG.md` and
`packaging/VERSION`. Releases are cut by tagging the version as `v<VERSION>`.

## Documentation

- [Architecture](docs/architecture.md)
- [Operations](docs/operations.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Claude Code setup](docs/claude-code.md)
- [Adding a model](docs/adding-a-model.md)
- [Compatibility](docs/compatibility.md)
- [Installed runtime files](docs/runtime-files.md)
- [Provenance](docs/PROVENANCE.md)
- [All documentation](docs/README.md)

The release bundle carries this README, the `docs/` pages and the licence
files, so an installed host can read them offline. Everything else stays in
the repository, including `CONTRIBUTING.md`, `SECURITY.md`, `docs/assets/`,
`infra/`, `plans/` and `tests/`.

## Licence

SC Unlimited AI is open source under the [Apache License 2.0](LICENSE). You can use,
modify and redistribute it, including commercially, under the terms of that
licence. Attribution and licence notices must be preserved as the licence
requires.

- Licence: [LICENSE](LICENSE)
- Notices: [NOTICE](NOTICE)
- Third-party material: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- Official licence text: <https://www.apache.org/licenses/LICENSE-2.0>

Copyright 2026 Software Combined Pty Ltd. Maintained by Cyril Allart
(<cyril@softwarecombined.com>) at [Software Combined](https://www.softwarecombined.com).
