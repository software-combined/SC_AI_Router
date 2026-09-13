# Automatic updates: required machine setup

Canonical source: `software-combined/SC_Agent_plugins`, branch `main`.
One native schedule refreshes this Git marketplace once and reinstalls every
installed, enabled SCG plugin. New skills inside those plugins follow the same
updates. Uninstalled or disabled plugins remain so.

## Agents: complete setup after a pull or installation

When cloning, pulling, installing or updating these skills for use, configure
and verify automatic updates on the current machine. This is part of installation,
not an optional follow-up. Respect explicit read-only/no-mutation scope.
Do not claim completion from a Git pull, downloaded plugin, registered timer or
successful unit test alone. Reuse a verified working schedule for ordinary tasks.

Each user needs the Codex CLI, Python and noninteractive Git read access to this
private marketplace. Install and enable the wanted SCG plugins first. Resolve
`<plugin-root>` from the installed skill path, or use `plugins/scg-review`
from the repository root after pulling `main`. Either plugin supplies the same
updater and configures the same shared schedule.

```sh
python3 <plugin-root>/scripts/updater.py install
python3 <plugin-root>/scripts/updater.py run
codex plugin list --marketplace scg-agent-plugins --json
```

On Windows use `python` if that is the installed command. Pass
`--codex <absolute-cli-path>` if Codex is not on PATH. Standard Windows Python
must include `pythonw.exe` beside its interpreter.

| Platform | Shared schedule | Verify |
| --- | --- | --- |
| macOS | `com.softwarecombined.agent-plugins.update`: login and every 24 hours | `launchctl print gui/$(id -u)/com.softwarecombined.agent-plugins.update` |
| Linux | `scg-agent-plugins-update.timer`: five minutes after user-manager startup, then every 24 hours after completion | `systemctl --user status scg-agent-plugins-update.timer` |
| Windows | `SCGReviewUpdate-<user-SID>`: logon and daily at 09:00 | Inspect that task's enabled state, action and last result in Task Scheduler |

The existing review scheduler names are retained for compatibility; they now
update the whole SCG marketplace. Linux requires a running systemd user manager.
Windows uses the signed-in user's interactive token and windowless Python,
without elevation or stored passwords. Sleeping/signed-out machines are not
guaranteed to check at the scheduled instant.

Verify one actual scheduled run as well as registration. On Linux:

```sh
systemctl --user start scg-agent-plugins-update.service
systemctl --user show scg-agent-plugins-update.service -p Result --value
journalctl --user -u scg-agent-plugins-update.service -n 10 --no-pager
```

On macOS, start the shared LaunchAgent with `launchctl kickstart` and inspect
its last exit code and `~/.local/share/scg-agent-plugins/update.log`. On Windows,
run the named task and inspect its last result and that same per-user log path.
Confirm the installed versions with the CLI after the run. Start a new Codex
task to load the refreshed skills.

## Existing installations and custom schedules

The stable runner is `~/.local/share/scg-agent-plugins/updater.py`, independent
of versioned plugin caches. A prior copied runner does not replace itself just
because a plugin or repository was pulled.

For released per-plugin schedulers, use the documented migration option:

```sh
python3 <plugin-root>/scripts/updater.py install --migrate
```

Migration verifies known runner content, stops its old schedules and preserves
the runner and definitions as `*.migrated` rollback copies before creating the
shared schedule. An explicitly migrated Linux timer may have custom timing;
its original definition is kept in that backup. Unknown runner code or a job
targeting another runner is preserved and reported for manual reconciliation.
Agents must inspect custom jobs before migration and verify a real run afterwards.

For an existing Linux installation, pull `main`, then follow this procedure
against that user's timer. A local Mac verification does not prove another
user's Linux machine has updated.

## Maintenance and scope

The shared updater and native scheduler are authored under
`plugins/scg-review/scripts/` and bundled unchanged in every SCG plugin; tests
enforce equality. Every new skill must link to these setup instructions, and
every new plugin must ship the same all-platform update support. Changes to a
copied runner's execution require an explicit migration.

The router's CloudFront feed distributes router bundles; plugin updates use
the approved Codex Git marketplace. CLI errors are logged without credential
helper output. Plugin refresh does not modify hooks, scanner pins, credentials
or global instructions. To disable updates, unload the named LaunchAgent,
disable the named user timer, or disable the named Windows task.
