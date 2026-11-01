<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/sc-logo-wide-dark.png">
    <img src="docs/assets/sc-logo-wide.png" alt="Software Combined" width="380">
  </picture>
</p>

<h1 align="center">SC_AI</h1>

<p align="center">The shared AI setup for Software Combined.</p>

SC_AI brings together the local SCG Router, agent plugins, reusable skills,
and the checks used to maintain them. Router connects supported assistants to
subscription models and approved external providers. Plugins teach assistants
how to complete work within the team's rules.

| About the project | Details |
|---|---|
| Who it is for | Software Combined staff and contributors using AI assistants |
| Maintained by | Software Combined Technology |
| Status | Router and plugins have separate build, release, and acceptance gates; see [tested setups](docs/compatibility.md) |

## Get started

Have Codex or Claude installed. You need your own subscription for subscription
models. External providers require a separate key and charge for usage.

1. Open [Install SCG Router](https://hub.softwarecombined.com/install) and choose your computer.
2. Open the installer and choose your assistant. Use the work-account route only when your organisation has enabled it.
3. Reopen your assistant, select an available model, and send a short greeting.

You should receive a reply. Installation alone does not prove the connection works.
See [setup options](docs/setup.md) and [desktop controls](docs/desktop-menu.md)
for platform requirements, connections, and recovery.

The Router also delivers the [agent plugins](plugins/README.md) to attached
Codex and Claude Code installations. Each plugin contains skills for a defined
area, such as documentation, review, or persistent agent teams. Read its guide
before use. A skill does not grant permission to change production systems.

## Use and limits

Keep subscription traffic on its subscription provider. External models use
separate credentials. External calls cost money; a personal key has no local
spend cap. Never paste keys into chats or support tickets.

Claude Code support remains in preview. Third-party models in Claude Code
sit outside Anthropic's supported model scope. See [integration scope and
data flows](docs/publication.md) before deciding to deploy.

## For maintainers

Router source, installers, tools, tests, and infrastructure live in `router/`.
Plugins remain under `plugins/`. The root setup plugin keeps its
`scg-openrouter` identity. See [architecture](docs/architecture.md) and
[the repository transition](docs/repository-transition.md) for boundaries
and compatibility.

Use Python 3.14 or later. Run Router checks and builds from `router/`:

```sh
cd router
python3.14 tools/plugin_verification.py --base origin/development --run
python3.14 -m compileall -q ai_router tools tests packaging
python3.14 tools/check_source_limits.py
python3.14 tools/check_policy_scans.py
```

The unit suite stays offline. Build locally with
`python3.14 packaging/release.py --out dist`; this does not publish or install.
See [contributing](CONTRIBUTING.md) for reviews, plugin validation, and releases.
Normal pull requests target `development`; `main` is the release branch.
Router and plugins retain separate version and release rules.

## Help and licence

Start with [operations](docs/operations.md) or [recovery](docs/recovery.md).
Report vulnerabilities through [the security policy](SECURITY.md).
Include the error and what you tried; leave out keys and personal data.

Repository code uses [Apache 2.0](LICENSE), with component notices in
[NOTICE](NOTICE) and [third-party notices](THIRD_PARTY_NOTICES.md).
Plugins retain the licences in their own manifests.
