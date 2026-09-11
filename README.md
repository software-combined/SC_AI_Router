<img src="docs/assets/sc-logo-wide.png" alt="Software Combined" width="420">

# SC Router

[![Check](https://github.com/software-combined/SC_OpenRouter_adapter/actions/workflows/check.yml/badge.svg?branch=develop)](https://github.com/software-combined/SC_OpenRouter_adapter/actions/workflows/check.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

SC Router is a local model router for Codex and Claude Code. It serves both
clients from one loopback endpoint and lists ChatGPT or Claude subscription
models beside approved OpenRouter models in the picker.

The billing split is strict. Subscription models keep using the client's
existing ChatGPT or Claude sign-in, OpenRouter models use an OpenRouter API
key stored on the machine, and subscription credentials never accompany a
request billed to OpenRouter.

- One router for Codex and Claude Code, with per-turn model selection.
- Subscription and OpenRouter billing kept separate and visible in the picker.
- Loopback only, one per-install token, owner-only key file, and no request
  content in logs.
- Python 3.14 runtime with no third-party dependencies.

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

The quickest install is the bootstrap. It needs no GitHub account, token or
repository access: it downloads the pinned Python runtime and the release
bundle from the public feed, verifies both checksums and installs the
per-user service:

```sh
curl -fsSL https://dist.softwarecombined.com/bootstrap/bootstrap.sh -o bootstrap.sh
sh bootstrap.sh
```

On Windows, run the PowerShell bootstrap instead:

```powershell
Invoke-RestMethod https://dist.softwarecombined.com/bootstrap/bootstrap.ps1 -OutFile bootstrap.ps1
.\bootstrap.ps1
```

Add `--channel=beta` (PowerShell: `-Channel beta`) to follow pre-releases.

From a checkout (needs Python 3.14):

```sh
git clone https://github.com/software-combined/SC_OpenRouter_adapter.git
cd SC_OpenRouter_adapter
python3.14 packaging/release.py --out dist --url-base "file://$PWD/dist"
python3.14 packaging/install.py --feed "file://$PWD/dist/latest.json"
```

On Windows, run the same checkout commands from PowerShell with the Python
launcher:

```powershell
py -3 packaging/release.py --out dist --url-base "file://$PWD/dist"
py -3 packaging/install.py --feed "file://$PWD/dist/latest.json"
```

The installer commands later in this README run from a checkout. A bootstrap
install ships the same installer at
`<home>/releases/<version>/packaging/install.py`, where `<version>` is the
version recorded in `<home>/current`; run it with the pinned interpreter at
`<home>/runtime/python/bin/python3.14` (`python.exe` under the same path on
Windows) when the host has no Python 3.14 of its own.

The installer verifies the bundle checksum, self-tests the runtime, installs
the per-user service and writes the client configuration. If no OpenRouter key
is configured it creates an empty key file and tells you where to put the key;
re-run the installer afterwards. Restart the client so the router's model
catalogue is picked up.

Before a checkout install, `--preflight` reports missing prerequisites without
writing anything, and `--dry-run` shows what an install would do.

## Clients

Codex is attached by default: the installer registers the router as a model
provider and adds its catalogue, so the models appear in the picker after a
restart. Use `--client none` for a service-only install.

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

Every install checks the public feed at
`https://dist.softwarecombined.com/<channel>/latest.json`; `stable` is the
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
process binds the port.

- `python3.14 packaging/install.py --check-update` runs one check now.
- `python3.14 packaging/install.py --version <version>` rolls back to a
  previously installed release.
- A `--feed <latest.json>` install uses that document for the run only; later
  checks follow the channel.

## Uninstall

`python3.14 packaging/install.py --uninstall` stops and removes the service,
the update schedule and the client configuration. The state directory, key
file and loopback token are left in place for you to delete.

## Diagnostics

- Health: `http://127.0.0.1:<port>/<token>/health`, with the port and token
  from `mixed-router-state.json` in the router home. Keep that URL private.
- `python3.14 packaging/install.py --status` reports the installed version,
  service state, feed source, channel and key state.
- A 400 means the model, payload or local key configuration is invalid. A 409
  means the provider cannot serve the request, for example an unsupported
  reasoning level after a model switch; the message names the allowed levels.
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

Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).

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

## Development

```sh
python3.14 -m unittest discover -s tests -t .
python3.14 -m compileall -q ai_router tools tests packaging
python3.14 tools/check_source_limits.py
```

The runtime is Python 3.14 with the standard library only; installer scripts
stay Python 3.9-compatible. Branches start from `develop`, pull requests target
`develop`, and user-visible changes update `CHANGELOG.md` and
`packaging/VERSION`. Releases are cut by tagging the version as `v<VERSION>`.

More documentation:

- [Architecture](docs/architecture.md)
- [Claude Code setup](docs/claude-code.md)
- [Adding a model](docs/adding-a-model.md)
- [Compatibility](docs/compatibility.md)
- [Operations](docs/operations.md)
- [Installed runtime files](docs/runtime-files.md)

## Licence

SC Router is open source under the [Apache License 2.0](LICENSE). You can use,
modify and redistribute it, including commercially, under the terms of that
licence. Attribution and licence notices must be preserved as the licence
requires.

- Licence: [LICENSE](LICENSE)
- Notices: [NOTICE](NOTICE)
- Third-party material: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- Official licence text: <https://www.apache.org/licenses/LICENSE-2.0>

Copyright 2026 Software Combined Pty Ltd. Primary author and maintainer:
Cyril Allart <cyril@softwarecombined.com>.
