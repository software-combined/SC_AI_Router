# SC Agent Plugins

This repository is the canonical source for published SCG plugins.
Keep authoring inside the relevant `plugins/<name>` directory; installed plugin caches are delivery copies.
Preserve the review, secret-scan, model-availability and exact-staged-tree gates.
Use the current host's pre-commit-review procedure before every commit.

## Automatic updates are part of installation

Every new skill or plugin published here must receive automatic updates on
macOS, Linux and Windows through the shared SCG marketplace updater. Reuse the
native LaunchAgent, systemd user timer and Task Scheduler support; do not ship
a platform-only updater or add a separate schedule per skill.

When an agent clones, pulls, installs or updates this repository or one of its
skills for use on a machine, complete the setup in
`plugins/scg-review/references/updates.md` (or the installed plugin's bundled
update guide). Configure the native schedule, run the updater once and verify
the schedule and installed versions. This is part of the requested installation,
not an optional follow-up. Respect an explicit audit-only or no-mutation request.
If prerequisites or a custom existing schedule prevent setup, preserve it and
report the exact remaining step; never claim that a pull alone enables updates.

Keep these setup instructions discoverable in README and the plugin's skill
entrypoints. New plugins must bundle the shared updater and scheduler unchanged;
test their registration and execution on Linux and Windows CI and preserve
macOS coverage before release. Publishing is separate from recipient setup.

Required checks: `python3 -m unittest discover -s tests -v` and
`python3 -m unittest discover -s plugins/scg-review/support/git-hooks/tests -v`.
Validate the Codex manifest with the installed plugin-creator validator when available.

The hook adapter and its tests under `support/git-hooks` are an unchanged import
of the installed SCG adapter, with provenance in `support/PROVENANCE.md`.
Do not update an existing machine's hooks or scanner pin as a side effect of a
plugin refresh. Such changes need an explicit setup/migration operation.

Release by updating the plugin version and CHANGELOG, passing checks/review,
and merging into `main`. A release is not a proof that every client has updated.
Claude Code packaging is a later increment; do not claim it is currently supported.
