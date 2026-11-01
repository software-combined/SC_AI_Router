# SCG Router

SCG Router connects Codex and Claude to subscription models and approved external providers.
Switch models mid-thread from the picker. Keep the same task and its history.
It also delivers the [SCG agent plugins](../plugins/README.md).

Install through the [staff download page](https://hub.softwarecombined.com/install).
See [setup](../docs/setup.md), [desktop controls](../docs/desktop-menu.md),
[compatibility](../docs/compatibility.md), and [operations](../docs/operations.md).

Source commands run from this directory. Python 3.14 or later is required;
the runtime uses the standard library only. Installer entrypoints remain
compatible with Python 3.9.

```sh
python3.14 tools/plugin_verification.py --base origin/development --run
python3.14 -m compileall -q ai_router tools tests packaging
python3.14 tools/check_source_limits.py
python3.14 tools/check_policy_scans.py
```

Build an offline bundle with `python3.14 packaging/release.py --out dist`.
This creates an artifact and does not install or publish it.
The source layout differs from the installed layout: release bundles retain
`ai_router/`, `packaging/`, `tools/`, and `plugins/` at their top level.
Existing runtime names, user state, feed signing trust, and desktop controls
remain compatible. See [repository transition](../docs/repository-transition.md).

Contribute through [the repository rules](../CONTRIBUTING.md).
Router changes follow [the Router changelog](CHANGELOG.md) and version marker
`packaging/VERSION`; plugin releases have their own versions.
