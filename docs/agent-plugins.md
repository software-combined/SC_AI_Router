# Agent plugins

This repo also hosts the `scg-agent-plugins` marketplace:
`scg-review` (pre-commit review), `scg-subagents` (subagent coordination),
`scg-prototypes` (prototype publishing), `scg-finance` (finance analysis) and
`scg-documentation` (technical writing) and `scg-ponytail` (coding simplicity).
Every plugin works in Codex and Claude
Code.

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
codex plugin marketplace add software-combined/SC_AI_Router --ref main
codex plugin add scg-ponytail@scg-agent-plugins
codex plugin add scg-review@scg-agent-plugins
```

SCG Review uses the single `scg-ponytail:ponytail` skill for its simplifier
and every review lane. Install Ponytail before Review; a missing, disabled or
unreadable Ponytail blocks the review. Claude Code users install the same
dependency with `claude plugin install scg-ponytail@scg-agent-plugins` before
installing or updating `scg-review`. Client inventories resolve the installed
skill path, so a cache version is never part of the instructions. Plugin caches
are delivery copies; the authored skill lives in this repository.

Installing the router later moves that Codex registration to the router's own
copy. A plugin you turned off in Codex or Claude Code stays off.

Plugin releases ride `plugin.json` versions plus `plugins/CHANGELOG.md`,
separate from the router tag train (`packaging/VERSION` never moves for a
plugin-only change). See [repository instructions](../AGENTS.md#9-agent-plugins) for the plugin rules.
