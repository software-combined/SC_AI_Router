# Express updates

Owner: current task, branch `cyril/express-updates-20260913`, worktree
`/Users/cyrilallart/Documents/Github/.worktrees/router-express-updates-20260913`.
Base: `origin/develop` at `02749ac` (refreshed from `d0786da`);
integration target: `develop`.
Authority: plan, implement, review, commit, merge, clean up and release beta.
Stable Express support is included; this task publishes beta only.

## Success proof

A beta or stable Express feed reaches the existing applying installer on the
next minute check, while a normal release remains on its four-hour schedule.
Feed publication, native scheduling and fleet installation are distinct proofs.

## Implementation

1. Parse immutable `v<VERSION>-express` and `v<VERSION>-beta-express` tags in
   the release builder. Keep numeric bundle versions, stable/beta channel
   selection, tag identity, maintainer restrictions and release checks.
2. Add an independent minute Express job on macOS, Linux and Windows. Reuse
   the installed update launcher and applying path; keep the regular job.
   Changing the existing macOS interval cannot safely reload its own job.
3. Express-only checks ignore ordinary feeds without saving their ETag or
   serial. Origin, checksum, serial, newer-version, installer locking,
   graceful drain and health rollback remain on the shared applying path.
   A failed Express attempt waits for the regular retry schedule.
4. The Express launcher resolves the current release and exits harmlessly
   when an older installer does not support Express. Install and uninstall
   own the new native job on every OS.
5. Verify both tag channels, packaged imports, normal/urgent update behavior,
   failures, rollback compatibility, native job definitions and cleanup.
   Run the full suite, compile check, source limits and required review.
6. Merge the reviewed commit into develop, verify integration, publish an
   Express beta tag, read back its release/feed, then remove the task worktree.

## Scope and acceptance limits

Existing machines need this capability through their current update schedule
or a manual update first. Offline/sleeping machines check when available.
Express cannot repair a missing interpreter or a broken updater. It does not
force client applications to quit or change a machine's configured channel.
Native Windows/Linux execution and fleet adoption must not be claimed from
mocked cross-platform lifecycle tests.

Planning advisor: Sol Max recommended the separate job to avoid the macOS
self-reload defect and remove custom cadence/cache state. Accepted.
Also accepted: quiet no-op paths never cache an in-progress pointer, short
Express jitter, legacy-launcher guard and normal-cadence retries.

The advisor's proposed blanket ban on changing existing soft-limit baseline
counts was not adopted: three established installer files grow by 2, 3 and
15 lines for this feature, remain within their hard limits, and retain the
source-limit check. Extracting unrelated code solely to offset those lines
would widen this bounded delivery.

Version 0.6.46 leaves room for the concurrent 0.6.44/0.6.45 maintenance work.
Client versions match the recorded September 13 compatibility baseline:
Codex desktop 26.908.40834, bundled CLI 0.154.0-alpha.6.2 and Claude Code 2.1.223.
No client upgrade occurred in this task.

Validation before final review: stable/beta workflow shell execution and
Express behavior checks passed. Native macOS isolated scheduling fired after
60.1 seconds with Express-only arguments; its temporary job was removed.
Windows/Linux registration and removal passed against recorded OS commands.
The initial full suite found three fixture failures: the fake launchd domain
assumed a never-installed Express job was already loaded. The fixture now
models that job as absent; the valid no-bootout assertions remain unchanged.
Production router plist fingerprints were unchanged by these checks.
