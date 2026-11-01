# Agent plugins

This repo hosts the `scg-agent-plugins` marketplace. Browse
[plugins and skills by domain](../plugins/README.md) for sales, development,
finance, operations, customer success, support, documentation and agent tools.
Every plugin works in Codex and Claude Code.

Plugin source lives under `plugins/<domain>/<plugin-name>/`. Department briefs
share the agent plugin and are linked from their domain pages. Installed plugin
names, skill names and client paths stay the same.

The router is the delivery channel. Its release bundle carries the plugin
trees, and each install or scheduled update that lands a new release
materialises a router-owned local marketplace and registers it with the
attached clients, so on a router host the plugins arrive and refresh with the
router and need no Git account, GitHub access or marketplace command. On Windows,
updates also find Codex in the app's own CLI directories under `%LOCALAPPDATA%`,
even when those directories are missing from the scheduled job's PATH. Once
Codex runs from that copy, the same pass retires any earlier Git-backed plugin
runner it recognises, with its macOS LaunchAgent or Linux systemd timer, since
that runner only ever refreshes Codex. A refused Linux scheduler operation
keeps the old files and reports retirement as pending, so a later install can
retry. A host without the router can still install the plugins from the Git
marketplace:

```sh
codex plugin marketplace add software-combined/SC_AI --ref main
codex plugin add scg-ponytail@scg-agent-plugins
codex plugin add scg-review@scg-agent-plugins
codex plugin add scg-optimise-ci@scg-agent-plugins
```

SCG Review uses the single `scg-ponytail:ponytail` skill for its simplifier
and every review lane. Install Ponytail before Review; a missing, disabled or
unreadable Ponytail blocks the review. Claude Code users install the same
dependency with `claude plugin install scg-ponytail@scg-agent-plugins` before
installing or updating `scg-review`. Client inventories resolve the installed
skill path, so a cache version is never part of the instructions. Plugin caches
are delivery copies; the authored skill lives in this repository.

SCG Review is model agnostic. Each user sets preferred reviewer models and
fallbacks in their local Git hook configuration; see
[reviewer preferences](../plugins/development/scg-review/references/setup.md#reviewer-preferences).
The shared skill keeps the same review and secret-scanning gates.

Installing the router later moves that Codex registration to the router's own
copy. A plugin you turned off in Codex or Claude Code stays off.

Plugin releases ride `plugin.json` versions plus `plugins/CHANGELOG.md`,
separate from the router tag train (`packaging/VERSION` never moves for a
plugin-only change). See [repository instructions](../AGENTS.md#9-agent-plugins) for the plugin rules.

Small skill and reference updates use the shared
[`plugin_verification.py`](../router/tools/plugin_verification.py) entry point locally
and in CI. It prints the comparison base, changed paths, selected suites and
reason. The narrow path keeps plugin contracts, paired manifests, public-content
checks and packaged delivery tests. Strict manifest and skill validation,
secret scans and independent reviews remain required.

Executable plugin changes and uncertain or mixed scope retain full Router tests.
Changes to the selector or its workflow wiring also require full verification;
the policy cannot exempt its own update. See
[verification before commit](../AGENTS.md#5-verification-before-commit) for commands.
