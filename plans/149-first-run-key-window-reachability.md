# Plan 149: First-run key window reachability

> **Executor instructions**: implement the task exactly as specified here.
> When done, update this plan's status row in `plans/README.md`.

## Status

- **Priority**: P1; Effort: M; Risk: MED; Confidence: HIGH; category: dx/security-surface.
- **Depends on**: 139 (native popup), 141 (provider key walk). No owner gate: local only.
- **Serialise with**: any writer on `packaging/install.py`, `packaging/provider_keys.py`,
  `packaging/updater.py`, `tests/install_fixtures.py`.
- **Planned at**: branch `cyril/router-key-window-20260912`, based on `origin/develop`
  (145-148 in flight elsewhere on `origin/develop`; 149 confirmed free).

## Why this matters

The native key window is the intended first-run flow, but it is unreachable on the
documented bootstrap path: `bootstrap.sh`/`bootstrap.ps1` never pass `--setup`, and
`packaging/provider_keys.py:supplied()` treats a shell-exported `OPENROUTER_API_KEY`
as configured even though the installer passes only `ROUTER_HOME` to the service.
The result is a silent health failure and a manual key-file workaround
(Plan 107 section 3 documents this trap). A fresh install must open the key window
whenever the installed service has no service-visible key.

## Current state (verified on this branch before editing)

- `packaging/install.py:do_install` mints the setup nonce only under `args.setup`
  (`:320-330`) and spawns `ai_router.key_prompt` only when `setup_url` is set
  (`:362-373`); otherwise `ensure_credentials` stops the install with exit 3
  (`packaging/provider_keys.py:ensure`).
- `packaging/provider_keys.py:supplied()` counts a non-empty env var as handled;
  `key_state()` mirrors `credentials.key_for()` precedence (env wins).
- `packaging/diagnostics.py:_key_private` is the owner-only checker (POSIX mode
  bits; Windows via `ai_router/winacl.py` spec-load).
- `packaging/updater.py:do_check_update` spawns the installer child with no extra
  environment (`cmd`, `_svc.run(cmd, ...)`).
- Launchd (`packaging/launchd.py:render_plist`) and systemd
  (`packaging/systemd.py`) pin only `ROUTER_HOME`; the Windows task adds no
  environment block. None passes the installing shell's environment through,
  which is the trap; a persistent user-level variable can still reach a task.
- `docs/troubleshooting.md` exists on `origin/develop` (97 lines, shipped by
  `3f78fb6`); this worktree's base predates it, so it is restored from
  `origin/develop` and extended here.
- `plans/145-148` exist on `origin/develop`; this worktree's base predates them,
  so 149 is the next free number and this plan does not touch `plans/README.md`
  rows it cannot see (the integrator adds the row against `origin/develop`).

## Scope

- `packaging/provider_keys.py`: add `unhandled(home, state, private)` (the
  service-visible read: empty env, owner-only key file or valid `opencode_auth`;
  empty placeholder not handled) and refuse a non-blank widened key file with
  `SystemExit` naming the file and the required permission. `ensure()` creates
  the placeholder silently and returns (no exit 3) when `_setup_armed(state)`.
- `packaging/install.py:do_install`: before `ensure_credentials`, arm the setup
  nonce/state in the same shape and TTL as `--setup` when any external provider
  is unhandled; `--setup` stays as the explicit force and, on a current home,
  restarts the service with a fresh nonce without re-extracting the release.
  Print one non-secret notice naming `OPENROUTER_API_KEY` when the key is
  env-only. Spawn
  `ai_router.key_prompt` exactly as `--setup` does today, honoring
  `ROUTER_NO_KEY_WINDOW=1` (nonce still minted, no process spawned).
- `packaging/updater.py`: set `ROUTER_NO_KEY_WINDOW=1` on the installer child env.
- Tests: `tests/test_provider_keys.py` (service read), new
  `tests/test_install_key_window.py` (installer + updater window behaviour),
  `ROUTER_NO_KEY_WINDOW=1` in the shared installer harness
  (`tests/install_fixtures.py` env) so no existing test spawns a real dialog.
- `ai_router/key_dialog.py`: treat AppleScript error -128 and the
  "cancelled" spelling as a cancel, so cancelling the dialog never falls
  into the browser fallback.
- Docs and release: `docs/agent-install-prompt.md`, README quick start,
  `docs/operations.md`, `docs/troubleshooting.md`,
  `skills/manage-router/SKILL.md`, `CHANGELOG.md` entry, bump
  `packaging/VERSION` (and `pyproject.toml`, both plugin manifests) `0.6.32`
  to `0.6.34`; 0.6.33 was claimed by the tool-alias repair (PR 96) before
  this branch was integrated.

## Interfaces

- `--setup` keeps working and is now an explicit force rather than the only way
  to arm the window. Bootstrap scripts need no flag change.
- `ROUTER_NO_KEY_WINDOW=1` is the unattended opt-out for the dialog; no CLI flag
  is added.
- Runtime key resolution in `ai_router/credentials.py` is unchanged: the env var
  stays valid for foreground runs, it just never counts as installed-service
  configuration.
- No wire-protocol, catalogue, or state-schema change; the existing setup block
  is reused.

## Verification

- Focused: `python3.14 -m unittest tests.test_provider_keys
  tests.test_install_key_window tests.test_install_config tests.test_update_channel`.
- Full: `python3.14 -m unittest discover -s tests -t .`,
  `python3.14 -m compileall -q ai_router tools tests packaging`,
  `python3.14 tools/check_source_limits.py`,
  `python3.14 -m ruff check --select F401,F811 ai_router packaging tools tests`.
- Live: one fresh bootstrap install on macOS (owner machine) confirming the
  window opens with no key and no `--setup` flag.

## Out of scope

- Key rotation semantics (unchanged: delete the key file first, then re-run).
- Windows and Linux dialog acceptance (owner-gated machine acceptance).
- Any subscription-routing behaviour change.
- `plans/README.md` row: the integrator adds it against `origin/develop`,
  where 145-148 exist; this worktree's base predates them.
