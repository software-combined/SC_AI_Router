# Router documentation

Start with the repository [README](../README.md) for the ordinary user path,
models and billing. These pages go deeper.

| Page | Use it for |
|---|---|
| [Setup](setup.md) | Staff setup, assistant choices, prerequisites and installation from source |
| [Repair older installations](recovery.md) | Public repair without uninstalling, saved choices and the maintainer notice |
| [Native installers](native-installers.md) | DMG, EXE and AppImage builds, staff downloads, migration and acceptance |
| [Desktop menu and tray](desktop-menu.md) | Connection switching, management, sign-in startup and Linux fallback controls |
| [Agent plugins](agent-plugins.md) | The bundled tools, standalone setup and their release rules |
| [Verification pipeline](ci-pipeline.md) | Parallel main acceptance, required checks and timing evidence |
| [Windows CI comparison](windows-ci-benchmark.md) | Frozen serial/split samples, execution equivalence and the acceptance decision |
| [Operations](operations.md) | Install, update, rollback, uninstall and the daily commands |
| [Troubleshooting](troubleshooting.md) | Symptom-first remedies: updates, serving, keys, client quirks |
| [Adding a model](adding-a-model.md) | Adding, probing and promoting a registry row |
| [Media generation](media-generation.md) | Preview image and video routes, client prerequisites and bounded verification |
| [Claude Code setup](claude-code.md) | Pointing Claude Code and the desktop app at the router |
| [Architecture](architecture.md) | Module ownership and the allowed dependency direction |
| [Installed runtime files](runtime-files.md) | What the release bundle contains |
| [Compatibility](compatibility.md) | Verified client and OS versions, per gate |
| [Muse first-turn rejection](muse-first-turn.md) | The demonstrated request-field trigger and retry diagnostics |
| [Linux upgrade](linux-upgrade.md) | Managed systemd user units and upgrade behaviour |
| [Kiro compatibility](kiro-compatibility.md) | The Kiro surface and its limits |
| [Context recovery](context-recovery.md) | What to do when a long turn or a compaction goes wrong |
| [Subscription restart recovery](subscription-restart.md) | Why ongoing chats need native discovery after an update and how recovery is verified |
| [Jev compaction benchmark](jev-compaction-benchmark.md) | What the archived-thread measurements showed about the experimental compaction |
| [Codex routing incident, 2026-09-13](codex-routing-incident-20260913.md) | One incident's evidence and what changed because of it |
| [Provenance](PROVENANCE.md) | Where the code came from |
| [Publication](publication.md) | Integration scope, safeguards and owner decisions |
| [Runtime licences](runtime-licenses.md) | Pinned archive and notice verification |
| [Changelog archive](changelog-archive.md) | Releases before the current minor series, unedited |
| [Agent install prompt](agent-install-prompt.md) | The prompt to hand a coding agent |
