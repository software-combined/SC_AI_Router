# Plan 121: Claude desktop models, effort readout, and connector strategy

> Planning only. No source change, release, paid probe, billing acceptance,
> managed-policy change, org change, bootstrap server, or live desktop
> mutation is authorised by this document. Each is a separate owner gate
> listed below. Nothing here executes until Cyril approves it.

> Planned 2026-09-11 at `1565057`, target `develop`.
> Amends 113 (client setup), 120 (desktop gateway discovery and attach),
> and 064 (client projections). Supersedes the stale parts of 120 noted
> below; it does not rewrite that plan's history.

## Status and outcome

- Priority P1; effort M; risk LOW (docs plus small projections with
  tests; the one live leg is read-only observation).
- Outcome: the desktop third-party picker shows every registry row with a
  truthful short description, the bare-tier alias resolves deterministically,
  users get a straight answer on effort control and connectors, and the
  remaining live proof (fresh-session picker, installer
  detach/reattach) is sequenced behind release plus deploy.
- First proof already held: 20 of 20 rows served with valid tiers through
  the client's own keep-rule, verified three independent ways (plan probe,
  GLM audit, Qwen asar re-derivation with the full 56-alternative denylist).

## Where things stand (verified 2026-09-11, read-only)

- Router `develop` serves 19 registry rows with
  `{id, display_name, anthropic_family_tier}` (16 sonnet, 1 opus, 1 haiku,
  1 fable). The live installed router (0.6.13.28) still serves 20 rows from
  the older registry; repo `VERSION` reads 0.6.14. No release has shipped
  the 120 work yet.
- Claude.app is `1.49585.0`. The third-party profile is currently DETACHED:
  applied `configLibrary` entry is `{}`, no `deploymentMode`, no
  `managedMcpServers`/`mcpServers` in either profile. First-party sign-in
  is intact. No `claude-desktop` claim in the activation receipt.
- Connector inventory, exact: first-party 270 tool toggles (13 server UUIDs
  plus `local`), third-party exactly 2 (`local:mcp-registry` discovery
  helpers, i.e. self-serve, not org connectors). Zero local server
  definitions anywhere.
- The 120 source is merged (PR 56): tier projection, desktop helper,
  `install.py --desktop`, claim guards, 16 helper tests plus ingress tests,
  green CI. The worktree is cleaned up.

## What the audits settled

Two independent auditors (GLM 5.3 max, Qwen Max xhigh) plus three Muse
contributor verifiers (correctness, installer, docs/adversarial) re-derived
the findings from the installed client and live state. Unanimous:

- Tier projection is the right mechanism; the community single-native-alias
  trick stays a diagnostic fallback, never the default (it mislabels
  capability and mostly fails against the full denylist anyway).
- "Build nothing" for connectors stands: no portable file-level migration
  exists for org-served connectors, and the inventory gate ("only if needed")
  is untriggered.
- Effort picker absence on gateway rows is a client-side table lookup keyed
  off native model names. Nothing for the router to do except keep passing
  `thinking`/`output_config` through untouched, which it does.
- Corrections accepted into this plan: bare `sonnet` does NOT resolve
  server-side (it falls to subscription passthrough; the tier field only
  guides client-side defaulting); error forwarding is conditional (429
  becomes synthetic 503, some 4xx become 409); the CLI discovery credential
  precondition was documented backwards (the fetch needs *some*
  credential); Plan 113's `[1m]` suspicion was wrong (valid client
  shorthand, stripped client-side, router never sees it); "20 of 20" is now
  "19 of 19" on current `develop`.

## Terminology, pinned for this plan

Cyril asked whether "plugins" is the word. Five different things share
confusing names, and this plan uses them exactly:

- **Claude Code plugin**: a distributable bundle (skills, agents, hooks, MCP
  servers) installed via `/plugin` from a marketplace. This is the correct
  word for "create a plugin".
- **Managed `managedMcpServers` (Claude Code managed-settings)**: an OBJECT
  keyed by server name, http/sse only, delivered by admin policy. Different
  shape, different surface.
- **Desktop `managedMcpServers` (Claude Desktop dialog)**: an ARRAY of
  entries using `transport` (http/sse/stdio, or `server` for the three
  built-ins). The client itself states the desktop array form "is not
  accepted here" on the Code side. Never copy one form into the other.
- **claude.ai connector**: an org-served integration delivered in-process to
  desktop sessions, governed by org policy. Not a file, not portable.
- **Provider MCP / self-hosted MCP**: an MCP server WE run (ourselves or via
  the provider's own endpoint) that a client reaches over the network. This
  is the answer to "host the MCP ourselves or can the plugin reach the
  provider MCP": both are possible and they compose — see step 4.

## Steps and verification

1. **Doc corrections (no source).** Fix the verified overclaims: wire
   `is_family_default` vs internal `isFamilyDefault` naming; CLI discovery
   credential precondition; desktop subscription-passthrough sentence (fix
   the PLAN's line 117-118, user docs already avoid it); toggle counts
   270 vs exactly 2. Correct the "bare sonnet resolves" line the same way.
   Verify by `git diff --check` and a second pair of eyes on each claim.
2. **`description` projection.** Emit a short (<=100 char, client-truncated)
   `description` per discovery row derived from the registry row, next to
   the tier projection. CLI rows stop reading "From gateway". Cover in
   `tests/test_claude_ingress.py` (key set becomes four keys, truncation
   bound). Then the repo gates: full unittest discovery, `compileall`,
   `check_source_limits.py`, then `pre-commit-review`.
3. **`is_family_default` on the four Anthropic alias rows.** Bare-tier alias
   resolution becomes explicit instead of first-listed-wins. Registry stays
   the fact owner; projection only. Update the exact row-key test. Verify in
   the live readback that the alias resolves to the flagged row.
4. **Connector strategy: plugin first, self-host second, copy never.**
   - (a) Publish the MCP servers users need as a **Claude Code plugin**
     through a managed marketplace: plugin-bundled servers load like
     user-configured ones, install/uninstall is one `/plugin` action, and
     `strictPluginOnlyCustomization` keeps them loading under lock-down.
     A plugin entry may carry an empty-URL placeholder for a connector the
     user configures later.
   - (b) Where the provider offers its own MCP endpoint (e.g. directory
     remotes addable with `claude mcp add`), prefer the **provider-hosted**
     server: no infrastructure to operate, per-user OAuth stays with the
     user. Where no provider endpoint exists or policy needs central
     control, **self-host** the server (stdio wrapped as remote http, or a
     first-party remote) and distribute it via (a) or via managed
     `managedMcpServers` object form on the CLI surface.
   - (c) For the DESKTOP third-party surface, neither (a) in Code-tab form
     nor managed-settings objects are read ("not read in the Code tab on a
     third-party deployment"); what works is the desktop dialog's own
     array form for local stdio plus the built-ins, and the in-destination
     `local:mcp-registry` self-serve already present. So: carry local stdio
     declarations the installer can own (same receipt discipline as the
     four inference values, only when the inventory shows need), document
     remote/admin paths as org-gated, and never copy toggles.
   - Verify: plugin installs and its servers list in `/mcp`; managed object
     form loads on CLI and records a notice (not a load) if pasted into
     desktop form; desktop array form validates in a synthetic profile;
     the "never copy toggles" rule has a test or an explicit checklist
     entry wherever installer connector support lands.
5. **Pass the portco allowlist to `models_listing()`.** One argument at the
   `/v1/models` call site mirroring the two protocol sites, so the desktop
   picker agrees with routing and the Codex catalogue. Latent today (no
   policy provisioned); covered by a fake-policy test. Then the repo gates
   plus `pre-commit-review`.
6. **Make `--status` attachment readback real.** Report owned values present
   (desktop: `inferenceProvider`, base-URL shape, `deploymentMode == 3p`;
   CLI: the two owned env keys), not file existence. Prove with synthetic
   empty-entry-plus-claim (must read detached) and full-attach (must read
   attached) tests. Then the repo gates plus `pre-commit-review`.
7. **Live readback (owner-gated, needs Cyril's session).** Release, deploy,
   reattach through `install.py --desktop`, relaunch, fresh-session picker
   count (19 of 19 on current registry, not a pinned literal), installer
   detach proving first-party return, reattach again. Record client version
   and both counts in `docs/compatibility.md`. Paid probes and billing stay
   Plan 115.

## Completion

- [ ] Doc corrections landed.
- [ ] `description` rows served, tested, reviewed.
- [ ] `is_family_default` on four alias rows, tested, reviewed.
- [ ] Plugin route proven for at least one server; managed/desktop forms
  documented with shapes; no toggle copying anywhere.
- [ ] Allowlist reaches the listing; status readback is value-based.
- [ ] Fresh-session picker count plus installer detach/reattach recorded
  with client version; sign-in intact.
- [ ] Repo gates and review pass; no worktree left behind.

Stop for a managed-policy conflict, loss of native sign-in, any prompt for a
real gateway credential, secret output, a discovery count that changes
without a configuration change, or a client upgrade that invalidates the
filter findings. Do not patch client binaries; the asar is evidence only.
Paid tool round trips and billing remain Plan 115.
