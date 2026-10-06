<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/sc-logo-wide-dark.png">
    <img alt="Software Combined" src="docs/assets/sc-logo-wide.png" width="380">
  </picture>
</p>

<h1 align="center">SC AI Router</h1>

<p align="center">
Use Codex and Claude with your subscription and approved OpenRouter models.
</p>

<p align="center">
  <a href="https://github.com/software-combined/SC_AI_Router/actions/workflows/check.yml"><img alt="Checks on GitHub Actions" src="https://img.shields.io/badge/checks-GitHub_Actions-blue"></a>
  <a href="https://github.com/software-combined/SC_AI_Router/releases/latest"><img alt="Releases on GitHub" src="https://img.shields.io/badge/releases-GitHub-blue"></a>
  <a href="LICENSE"><img alt="Licence: Apache-2.0" src="https://img.shields.io/badge/licence-Apache--2.0-blue"></a>
</p>

SC AI Router runs on your computer and connects your coding assistants to the
models you choose. For example, you can keep a chat open and switch between
a subscription model and an approved model billed to your own OpenRouter key.

| About the project | Details |
|---|---|
| Who it is for | Software Combined staff using Codex or Claude |
| Status | Claude Code is in preview; [tested setups and remaining checks](docs/compatibility.md) |
| Maintained by | Cyril Allart and Brent Maxwell; [contribution rules](CONTRIBUTING.md) |

## Get started

Have your assistant installed and an OpenRouter key if you want to use models
billed to OpenRouter. Those models cost money and have no local spend cap.

1. Ask a maintainer for the setup script for your computer. You do not need
   a GitHub account or access to this repository.
2. Run setup and choose the assistant you use. Enter your key only in the
   setup window when prompted; never paste it into a chat or support ticket.
3. Quit and reopen your assistant, select a model labelled `· OpenRouter`,
   and send a short greeting. Claude desktop uses its separate gateway profile.

You should see the model in the picker and receive a reply. Installation alone
does not confirm that the assistant works. See [setup options](docs/setup.md)
for prerequisites, changing assistants and installation from source.

If you are reading the installed `<home>/README.md`, open
`<home>/releases/<version>/README.md` for working guide links. The default home is
`~/.codex/mixed-model-router` (`%USERPROFILE%\.codex\mixed-model-router` on
Windows); read `<version>` from `<home>/current`.

<p align="center">
  <img src="docs/assets/codex-picker-openrouter-row.png" alt="The Codex composer with an OpenRouter-billed Claude row selected" width="760">
</p>
<p align="center"><sub>Rows labelled <code>· OpenRouter</code> charge your OpenRouter key.</sub></p>

## Use it

- Switch models mid-thread from the picker to keep working in the same chat.
  Codex and Claude Code in the terminal can use subscription models alongside
  OpenRouter models.
- Claude desktop's gateway profile uses OpenRouter models. Its subscription
  remains in the signed-in profile; see [Claude setup](docs/claude-code.md).
- Updates install automatically. Restart the assistant when asked to load
  new models. See [update and recovery instructions](docs/operations.md).

The router also delivers SCG tools for code review, agent coordination,
documentation and other work. See [agent plugins](docs/agent-plugins.md).

Switching keeps text and tools within the new model's limits. Images become
a note that the model cannot read them; unsupported reasoning levels are rejected.

## Limits and important notes

Subscription models use the assistant's own sign-in. OpenRouter models use your
local key; subscription credentials never accompany an OpenRouter request.
Watch paid usage in the OpenRouter dashboard.

macOS and Linux are supported; check the [Linux desktop requirements](docs/setup.md#before-you-start).
Windows sign-in relaunch and complete Claude desktop
task sharing still need confirmation. Models marked Preview also have
unfinished checks. See [compatibility](docs/compatibility.md).

The macOS [Switch Codex helper](docs/operations.md#switch-codex) works around
subscription usage limits. Archiving and automatic chat titles do not work
while switched. Experimental [compaction](docs/operations.md#experimental-compaction)
sends selected history to an external service and bills its key; confirm that
sharing is permitted before enabling it. Logs exclude request content, keys
and tokens; see [security](SECURITY.md).

## Help

If a model is missing, quit and reopen the assistant first. For other symptoms,
use [troubleshooting](docs/troubleshooting.md) or contact Software Combined IT.
Include what you tried and the error message. For diagnostics, use the redacted
support bundle described in that guide, never raw state, logs or credentials.

Report a suspected vulnerability privately to
<cyril@softwarecombined.com>, as described in [SECURITY.md](SECURITY.md).

## For maintainers

The runtime uses Python 3.14 and its standard library. See
[development setup and required checks](CONTRIBUTING.md),
[architecture](docs/architecture.md) and [operations](docs/operations.md).

Branch from `develop` and target pull requests at `develop`. Maintainers
promote releases to `main`; release tags and verification follow
[the release procedure](docs/operations.md#how-to-ship).
The release bundle includes the README, Markdown guides and licence files;
images and contribution instructions are available in the repository.

## More information

| Guide | When to use it |
|---|---|
| [Setup](docs/setup.md) | Install, change assistants or build from source |
| [Operations](docs/operations.md) | Update, roll back, diagnose or uninstall |
| [All documentation](docs/README.md) | Find model, compatibility and deeper technical guides |

## Licence

SC AI Router is open source under the [Apache License 2.0](LICENSE). You can use,
modify and redistribute it, including commercially, under the terms of that
licence. Attribution and licence notices must be preserved as the licence
requires.

- Licence: [LICENSE](LICENSE)
- Notices: [NOTICE](NOTICE)
- Third-party material: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- Official licence text: <https://www.apache.org/licenses/LICENSE-2.0>

Copyright 2026 Software Combined Pty Ltd. Maintained by Cyril Allart
(<cyril@softwarecombined.com>) at [Software Combined](https://www.softwarecombined.com).
