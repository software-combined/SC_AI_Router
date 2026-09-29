# Automatic updates

These skills ship with the SCG router. The router is the delivery channel: its
release bundle carries the plugin trees, and on every install the installer
materialises a router-owned local marketplace from that release and registers
it with each attached client. The scheduled router update runs the same
installer, so the skills refresh with the router. A host needs no Git account,
no GitHub access and no marketplace command typed by a person.

## How the skills update

Delivering the skills is part of installing or updating the router. There is no
separate plugin updater and no per-plugin schedule to configure.

- The installer writes a router-owned marketplace under
  `~/.local/share/scg-agent-plugins/marketplace` and registers that path with
  the attached Codex and/or Claude Code client.
- It installs each plugin from that marketplace. A refused registration is
  recorded and skipped; it never fails the router install or the other plugins.
- The same pass retires any earlier Git-backed plugin runner it recognises,
  preserving its files beside it as `*.migrated.<n>`.
- Every router release re-runs the installer, so a new skill or a plugin change
  arrives with the next router update.

Confirm the delivered versions and load the refreshed skills:

```sh
codex plugin list --marketplace scg-agent-plugins --json
```

Then start a new Codex task, or restart the client, so the refreshed skills are
loaded.

## Scope

Skill delivery never fails a router install and never modifies hooks, scanner
pins, credentials or global instructions. Read-only work needs no update step:
an up-to-date router already carries the current skills. On a host without the
router, these plugins can still be installed from the `scg-agent-plugins` Git
marketplace; the repository README covers that path.
