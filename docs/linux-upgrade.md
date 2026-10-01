# Linux upgrade and verification

## Read the desktop identity

From the checkout root, run the read-only check for the installed desktop app:

```sh
python3.14 packaging/desktop_linux.py --app codex
python3.14 packaging/desktop_linux.py --app claude
```

The command reports the selected desktop entry, executable path, app root and
package version stored in the app's Electron `package.json`. This is the app's
internal package version, not its distribution package-manager release. The
check refuses unrecognized wrappers and wrappers with relative targets. It
does not start or stop the app or change its settings. It confirms local
identity discovery only; Linux switching remains unavailable until lifecycle
support and native acceptance are complete.

Use the merged `develop` source for the first upgrade from the old 0.6.2.0
symlink installation. Its updater cannot bootstrap this transition: it
rejects the unsigned local feed and has no systemd lifecycle backend.

The machine's agent should:

1. Record the clean checkout's branch/commit and preserve any local work.
   Fetch and fast-forward `develop` only when safe. If fixes are needed, use
   one owned worktree and open a PR back to `develop`; do not edit the primary
   checkout or leave machine-only patches behind.
2. Inspect the existing unit definitions, pointer, installed version and
   release channel. No token, no GitHub account and no repository access
   are needed: the updater reads the public feed at
   `https://dist.softwarecombined.com/<channel>/latest.json`. Keep keys,
   state tokens and private health URLs out of reports.
   Disable the old update timer while preparing the upgrade. Check
   for a `feed` override file in the router home: preserve intentional pins;
   if it is the obsolete local development feed, retain a backup and remove
   that override so subsequent checks use the normal release channel.
3. Build the pulled source into a local feed with `packaging/release.py`.
   `--build` is free to choose: a `--feed` install neither checks nor records
   the anti-replay serial, so a local build can no longer block later
   published releases. Pass the output directory as a `file://` URL with
   `--url-base`, so the local feed resolves its local tarball.
4. At an idle boundary, run the new source's `packaging/install.py` with
   `--python /usr/bin/python3.14`, the existing `--home`, and the local
   `--feed file:///absolute/build-directory/latest.json`. This one-shot feed
   is not persisted into the new timer. Do not run the old installed updater
   to perform the migration.
5. Verify that `current` is now a regular pointer file, `router_launch.py`
   exists, and the service's ExecStart invokes that launcher without a
   WorkingDirectory pointing at `current`. Confirm the service and timer
   are enabled and the updater points at an installed release, with no
   hardcoded local feed argument. Confirm private `/health` reports the
   expected bundle version and both client routing paths still work.
6. Trigger `systemctl --user start codex-mixed-model-router-update.service`
   and inspect its exit status/log. A successful check with no newer release
   proves checking only. To prove installation, use a disposable Linux user
   session or systemd-enabled VM and a controlled newer unsigned bundle,
   then verify the changed health version. A different `--home` alone does
   not isolate the user service names or Codex configuration. Do not claim
   timer activity alone proves an update succeeded.
7. Verify rollback through the new installer's `--version` at an idle
   boundary, then restore the intended version. Keep the previous release
   and validate client access after restoring. Do not uninstall the live
   router merely to test removal; exercise uninstall in the isolated setup.

Report the source commit, installed version, unit status, channel and
update/rollback results. If any machine-specific issue remains, make the
smallest fix in the owned worktree, add its regression test, complete the
repository review gates and open a PR with the exact reproduction and
verification evidence. Keep the working installation intact while that PR
is reviewed.
