# Plan 147: Operator surface - doctor, status, rollback, support bundle

> **Executor instructions**: Follow this plan step by step. If a STOP condition
> occurs, stop and report. When done, update this plan's status row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 3515c6a..HEAD -- packaging/diagnostics.py packaging/install.py packaging/updater.py packaging/update_launch.py packaging/systemd.py packaging/launchd.py packaging/platforms/windows.py docs/operations.md docs/troubleshooting.md README.md skills/manage-router/SKILL.md tests/`
> Reconcile every cited line before editing; 131 is moving the state-read
> contract, so rebase on it rather than duplicating a reader.

## Status and first proof

- Priority P2; effort M; confidence HIGH; category dx/operability.
- Depends on 131's state-read contract; serialize with 134's remaining CI work.
- Source: `plans/2026-09-12-external-router-review.md`, the findings row
  "Operator surface".
- First proof: one read-only `--doctor` explains an unhealthy host in FAIL/WARN
  rows with a `Fix:` line and exits 1; `--status` says whether an update is
  available and whether a version is parked; `--rollback` with no argument lists
  what can be restored.

## Why this matters

A recipient who hits a problem today gets `service: not serving` and has to know
where to look. The external router's doctor aggregates the same facts we already
collect into one diagnosable report, its `update check` is read-only, and its
rollback needs no version argument.

## Scope

**In scope**: the files in the drift check, plus a new `tools/support_bundle.py`
if the report does not fit `diagnostics.py` under its cap.
**Out of scope**: any `--fix` behaviour that mutates state (report only), a tray
or GUI, and per-provider key CLIs.

## Steps

1. **`--doctor`.** A read-only aggregator over `--preflight`, `--status` and
   `ai_router.catalogue --check`: one row per component with `OK`/`WARN`/`FAIL`,
   a `Fix:` line on WARN/FAIL, `--json` for machines, exit 1 when any row fails,
   exit 0 otherwise. It never mints, writes or restarts anything.
2. **`--status` extension.** Today the state records only per-version failure
   counts (`service.update_failures`), the updater prints its reason without storing
   it in state, and the only JSON line it appends to `logs/update.log` is the landed
   record (platform output redirection is separate). Extend the
   updater's existing state write with `last_check_at` and `last_error` (same
   document, same single writer that 131 owns) and report from state: last check,
   last applied version, parked versions with their counts and the last error. No
   network call; the only write is the updater's own, never the read path.
3. **Rollback ergonomics.** `--rollback` with no argument lists the installed
   releases and the one `current` points at; `--rollback [--to VERSION]` performs
   the switch that `--version VERSION` performs today, which stays as an alias.
4. **`--check-update` becomes read-only.** Add `--update` as the applying command,
   route it to the existing updater in the argparse dispatcher (today only
   `--check-update` reaches `do_check_update`, so a literal executor would otherwise
   leave `--update` falling through to `do_install`), and point
   `packaging/update_launch.py`, the launchd plist, the systemd unit and the Windows
   task at it. `--check-update` prints current and available versions (and `--json`)
   without installing and without writing the ETag. Because a host whose scheduler
   still names `--check-update` would otherwise poll forever without applying, this
   step also requires: a test asserting the rendered systemd unit and the home
   launchers carry `--update`, and a `--doctor` row that reads the systemd unit and
   the installed `<home>/update_launch.py` and fails when the old argument is still
   present. The plist and the Windows task only name the launcher, so the launcher is
   the carrier to inspect on every platform; the systemd unit embeds the flag.
5. **`--support`.** Write a 0600 JSON bundle on explicit request from an allowlist
   schema: booleans, enums, versions, counts and timestamps only. Do not embed the
   status document wholesale - it carries absolute `config_path` values and the feed
   URL - and include no key, token, URL, config body or log line. Print only the path
   it wrote, and cover the promise with a test that serializes a status document
   containing a `config_path` and a feed URL and asserts the bundle contains no
   absolute path, no `://` and no match for the project's key shapes
   (`sk-or-v1-[A-Za-z0-9]{20,}`, `Bearer [A-Za-z0-9._-]{30,}`). Map the stored
   `last_error` to a fixed code from a closed set before it reaches the bundle and
   never pass the updater's free text through.
6. **Docs.** Fold the new commands into `docs/operations.md`, the README Common
   commands block and the `skills/manage-router` skill; the troubleshooting page
   points at `--doctor` as the first step.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Focused | `python3.14 -B -m unittest tests.test_preflight tests.test_status tests.test_safe_diagnostics tests.test_install tests.test_update_channel` | pass |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | exit 0; install.py stays under 700 |

## Done criteria

- [ ] `--doctor` is read-only, exits 1 on FAIL, and names a fix per failing row.
- [ ] `--status` reports update recency and parked failures without network access.
- [ ] `--check-update` makes no change; `--update` applies; schedulers name `--update`.
- [ ] `--rollback` with no argument lists releases; `--version` still works.
- [ ] `--support` output passes the pattern test: no key, token, URL, absolute
      path, config body or log line.
- [ ] Full suite, compile and limit gates pass; docs and skill updated.

## STOP conditions

- An installed scheduler cannot be re-rendered on upgrade: stop; a fleet that
  silently stops updating is worse than an unchanged command name.
- `--doctor` cannot run without mutating state: stop and report which check needs it.

## Maintenance notes

- `--check-update` changing meaning is a user-visible contract change: it belongs
  in `CHANGELOG.md` under Unreleased with the `--update` replacement named.
