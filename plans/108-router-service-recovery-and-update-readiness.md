# Plan 108: Reconcile the live router and restore safe update readiness

> **Fresh readback 2026-09-09:** router health `ok`, version `0.6.9.22`; router
> LaunchAgent loaded/running through `router_launch.py`; updater loaded with
> interval 900 through `update_launch.py` (idle between runs). Both disk
> executables exist; neither loaded job names a release-specific installer.
> This supersedes the missing-updater snapshot below. Start by rechecking,
> not reinstalling. Busy deferral, scheduled activation and rollback acceptance
> still need their own evidence; these observations do not close those gates.

> Planning only. No live installer run, restart, updater activation, paid call
> or release is authorised by this document.

Priority P1; effort S; risk HIGH (service lifecycle).
Planned 2026-09-09 at `96a305abbd381a2f4fb336d65bcc5078a016bf25`.

## Outcome

First observable proof: the existing router stays healthy on the verified
release, both loaded jobs use valid stable paths, and an update safely defers
while requests are active. This is a recovery slice; Plan 112 remains unchanged
and owns the shared installer and three-OS distribution design.

## Current state and source

Canonical repository: `software-combined/SC_OpenRouter_adapter` (private), local
`~/Documents/Github/SC_Codex_openRouter_adapter`. Python 3.14+, stdlib only.
Read `AGENTS.md`, `docs/operations.md`, `packaging/install.py`,
`packaging/service.py`, `packaging/router_launch.py` and
`tests/test_install_lifecycle.py`. Match existing small functions and injected
service/fetch boundaries; tests use temporary homes and fake service commands.

The handover's failed-install state was superseded by this read-only snapshot
on 2026-09-09. Recheck it before acting:

| Check | Observed |
|---|---|
| Authenticated `/health` | HTTP 200, version `0.6.5.17`, inflight 2, draining false |
| Authenticated GET `/v1/models` and `?limit=1000` | Both HTTP 200, 22 entries |
| GET `/v1/models` without path authentication | HTTP 403 |
| `current` | Regular pointer file with `0.6.5.17`; no `current.tmp` |
| Main LaunchAgent | Loaded/running; absolute existing Python; stable `router_launch.py`; KeepAlive true; no WorkingDirectory |
| Updater LaunchAgent | Plist and Python exist; job not loaded |
| Codex config/catalogue | Base matches router; 27 catalogue entries |
| `feed` and `channel` files | Absent |

Discovery and Codex catalogue counts represent different populations; do not
demand equal counts. Release directories included `0.6.1.0`, `0.6.1.3`,
`0.6.2.4` and `0.6.5.17`; this is not permission to prune them. Published bundle
identity/checksum success was reported in the handover, not re-proven here.
Source VERSION is `0.6.5`; distinguish it from the runtime build identifier.

## Scope, ownership and drift

After a request to execute, repair only this verified current-user installation
and missing updater. Source fixes, if still needed, are limited to
`packaging/install.py`, `packaging/service.py`, existing stable launchers,
related install/service tests, `docs/operations.md`, CHANGELOG/VERSION and plan
status. No client-auth changes, plugin work, cloud publication, signature
enforcement, owner-seed handling or unrelated cleanup.

Inspect worktrees and owners first. Use one owned worktree, never the primary
checkout. The handover's `codex/claude-finish` and `fix/launchd-absolute-python`
streams may already own the repair; obtain a handoff before adopting either.
Run `git diff --stat 96a305a..HEAD -- packaging tests docs/operations.md`.
Reconcile changed contracts before editing; do not duplicate an integrated fix.
Source integration is `develop`, then a PR to `main`, without moving another
writer's ref or the primary checkout's branch pointer.

## Steps and verification

1. **Reconcile without restarting.** Derive URLs from local state in process
   memory; output only status, version, inflight, draining, counts and path
   validity. Inspect disk plists and loaded `launchctl print` definitions,
   filtering their output. Inspect logs only through an allowlist of lifecycle
   fields. Never print tokens, headers, keys, request bodies or private URLs.
   Stop on ambiguous health or an already-draining service.
2. **Verify acquisition separately.** Use authenticated `gh` for private release
   metadata/assets; an anonymous GitHub 404 is not release evidence. Recheck
   serial, SHA-256 and agreement between feed, manifest and bundled VERSION.
   Retain checksum/serial/`check_identity`; do not generate an owner seed.
   Local file feeds are isolated experiments: follow `docs/operations.md` with
   a temporary `--home`, never pin or install from a `file://` feed live.
3. **Choose the smallest repair.** If the intended release is already healthy,
   do not reinstall merely to replay the handover. Trace updater registration,
   including same-version early return and upgrade paths. Inspect
   `restart_service`: its fresh-install bootout path is unsuitable for a live
   router. Check the updater target survives release pruning and reuse an
   existing stable management launcher. Reproduce any remaining defect with
   a fake service runner before changing source.
4. **Qualify offline.** Cover existing live service + missing updater,
   already-loaded updater idempotence, busy deferral and failed activation
   preserving the prior pointer where changed behavior needs protection.
   Dry-run in an isolated home and prove no real service label/client settings
   change. Before loading the live updater, verify its executable and feed:
   loading may immediately run an update, so execution authority must cover
   that consequence. Never force-bootstrap a loaded job or bootout the router.
5. **Activate narrowly and read back.** Preserve the release if no update is
   needed. Any replacement observes `wait_idle` and uses the existing graceful
   drain/TERM plus KeepAlive path with coordinated rollback. Busy traffic
   defers mutation. Recheck health, both loaded jobs, pointer, discovery set,
   query variant, unauthenticated GET 403 and authenticated POST `/v1/models`
   404. No inference request is needed.

## Commands and done criteria

From the owned worktree, all must exit 0:

```sh
python3.14 -m unittest tests.test_install tests.test_install_lifecycle tests.test_claude_ingress tests.test_feed_verify tests.test_feed_serial
python3.14 -m unittest discover -s tests -t .
python3.14 -m compileall -q ai_router tools tests
python3.14 tools/check_source_limits.py
```

- [ ] Fresh redacted readback records intended healthy version and both jobs.
- [ ] Busy deferral and rollback stay protected; no live bootout occurred.
- [ ] Discovery/authentication checks pass; paid acceptance stays separate.
- [ ] Source fixes have CHANGELOG/VERSION, required pre-commit review, commit,
  integration and integrated checks; only owned merged worktrees are removed.
- [ ] This plan and `plans/README.md` distinguish source and live completion.

Stop for identity disagreement, unknown ownership, stale loaded paths, stuck
inflight/draining, lost rollback or an out-of-scope source fix. If another
stream already repaired the issue, verify it without rewriting it. Plan 113
consumes the healthy service; Plan 112 owns generalisation.
