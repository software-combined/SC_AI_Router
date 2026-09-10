# Plan 073: Claude desktop gateway discovery, tier projection and installer attach

> Planning only. Amends 051 (client setup) and 064 (client projections).
> The desktop configuration described under "What already happened" is
> already applied on Cyril's Mac and is reversible; nothing further is
> authorised here. No source change, release, paid probe, billing
> acceptance, managed-policy change or org change is authorised by this
> document. Each is a separate owner gate listed below.

> Drift check: `git diff --stat e043920..HEAD -- codex_router/claude.py packaging/install.py packaging/claude_config.py tests/test_claude_ingress.py tests/test_install_config.py docs/claude-code.md docs/compatibility.md`
> Compare the "Verified current state" excerpts against live code and the
> installed client first; on a mismatch, STOP.

## Status and outcome

- Priority P1; effort M; risk MED (desktop client configuration is reversible
  and profile-isolated; the source change is a discovery-metadata projection).
- Planned 2026-09-10 at `e043920`, worktree
  `~/Documents/Github/.worktrees/claude-desktop-discovery-20260910`, branch
  `codex/claude-desktop-discovery-20260910`, target `develop`.
- Outcome: the Claude desktop third-party profile lists every OpenRouter
  registry row in its picker, and `install.py` can attach and detach that
  desktop configuration with the same ownership receipt discipline as the
  existing Claude Code CLI attach.
- First proof already held: a fresh desktop session's picker showed router
  rows and native sign-in survived (see "What already happened").
- Remaining proof: 20 of 20 rows in the desktop picker from the real
  router, then the same result reproduced by `install.py` rather than by hand.

## What already happened (2026-09-10, this machine)

Reversible desktop configuration, applied through the app's own dialog:

- `~/Library/Application Support/Claude/developer_settings.json` created with
  `allowDevTools: true`, mode 600, which revealed the Developer menu.
- The app's third-party dialog (`app://localhost/setup-desktop-3p`) saved
  four owned values into the third-party profile's applied configuration
  entry: `inferenceProvider` (gateway), `inferenceCredentialKind` (static),
  `inferenceGatewayBaseUrl` (private loopback router base with path token),
  `inferenceGatewayApiKey` (placeholder; the router authorises on the path
  token, not this value). `modelDiscoveryEnabled` was left on and is not
  persisted as an explicit key. Applying set the third-party profile's
  `deploymentMode` to `3p` and relaunched the app.

Evidence recorded, redacted:

- Router `0.6.11.27`, `GET /v1/models` = 20 rows, reachable from the app.
- In-dialog "Test model discovery" against the real router: **found 6 models**.
- Fresh session picker after relaunch: the same 6 rows, all suffixed
  `· OpenRouter`, default `Anthropic: Claude Sonnet Latest · OpenRouter`.
- Native sign-in retained: account menu shows the signed-in user, and the
  first-party profile's OAuth token caches are byte-intact.
- Before images: `~/.codex/private/claude-desktop-before-20260910-135930`
  (first-party) and `~/.codex/private/claude-3p-before-20260910-143245`
  (third-party profile config, applied entry, `_meta.json`, plus a
  first-party `config.json` copy), directories mode 700, files 600.

## Verified current state (2026-09-10, read-only)

Client: Claude.app `1.49585.0`, signed in as the work account. No
`managed-settings.json` at the user or system location, and no managed
preference domain for Claude; the settings observed are locally owned.

**Two profiles, not one.** The desktop keeps first-party and third-party mode
in separate Electron user-data directories: `~/Library/Application Support/Claude`
and `.../Claude-3p`. `deploymentMode` (`1p`/`3p`) lives in each profile's
`claude_desktop_config.json`, and third-party inference settings live in
`.../Claude-3p/configLibrary/<uuid>.json` selected by `_meta.json.appliedId`.
This isolation is why native sign-in survived: gateway mode never touched the
first-party profile's credentials. That isolation also causes the coexistence limit below.

**The discovery filter is a vendor denylist with a documented override.**
The app fetches `<base>/v1/models?limit=1000` and keeps a row only when the
id passes an Anthropic-name check *or* the row declares a valid
`anthropic_family_tier`. The denylist matches `glm`, `gpt`, `grok`, `qwen`,
`deepseek`, `kimi`, `gemini`, `moonshot`, `llama` and many more, so today's
`claude/<vendor>/<name>` aliases are rejected for exactly those vendors.
Accepted tier words are `sonnet`, `opus`, `haiku`, `fable`, `mythos`;
`isFamilyDefault` breaks ties, and a bare tier alias in a Code session
resolves through that field.

`codex_router/claude.py:models_listing()` currently emits `{id, display_name}`
only, which is why 14 of 20 rows are dropped. This was proved, not inferred:
a temporary local listener on `127.0.0.1:18999` served the router's own 20
rows with `anthropic_family_tier` added, and the same dialog reported
**found 20 models**. The probe URL was discarded without saving, the listener
was stopped, and the port is closed.

## Decision: project the tier, keep one listing

Add `anthropic_family_tier` to each discovery row in `models_listing()`.
Anthropic aliases keep their own tier word; every other row stands in for
`sonnet`, the everyday tier, so a bare `sonnet` alias resolves to a working
model instead of nothing. This is a client projection in the sense of Plan
064: the registry stays the fact owner and no row gains a new stored field.

Rejected alternatives: a hand-maintained `inferenceModels` list in the client
(drifts from the registry, and the AGENTS.md section 8 naming rule already owns
labels); renaming aliases to hide vendor words from the denylist (dishonest
ids, and it would break `unalias`); a second listing endpoint for the desktop
(a third code path for one metadata field).

`display_name` needs no change: the picker showed the fully qualified
`· OpenRouter` labels correctly, so the AGENTS.md section 8 naming rule already holds
on this surface.

## The coexistence limit (answer to "same as Codex")

Codex keeps subscription and OpenRouter models in one picker because the
Codex router is a *provider* alongside the native one. Claude desktop
1.49585.0 does not work that way: `inferenceProvider` "activates third-party
mode" for the whole app, and mode is a per-profile launch decision, not a
per-request one. Consequences, all observed rather than assumed:

- The third-party picker offers only discovered gateway rows. The native
  subscription models are not in it. Subscription Claude is still reachable
  *through the router* (the ingress passes non-registry models through with
  the client's own credentials), but only for ids the gateway lists.
- The third-party profile starts empty of first-party state: preferences,
  trusted folders and tool toggles do not carry over (29 preferences and 13
  trusted folders on this machine). Connectors are the important case and are
  covered in the next section.
- The app does have `hybrid*` machinery, including a hybrid model-selector
  overlay, but every hybrid path observed is driven by a bootstrap config
  server and org identity (`bootstrapUrl`, hybrid memberships, hybrid
  pointer), not by local settings. Reaching it would mean standing up a
  bootstrap server and touching org configuration, which is out of scope
  and out of authority here.

So "all subscription models plus all MCP and connectors in one picker" is
**not available** on this client version by local configuration. What is
available: all 20 router rows in the third-party profile after the tier fix,
with native sign-in intact and a one-value revert to first-party mode. The
gap is a client limitation to record in `docs/claude-code.md`, not a router
defect to work around.

## Connectors: what can and cannot be copied

Asked directly: can the existing MCP servers and connectors be copied from the
subscription profile into gateway mode? Partly, and "copy" is the wrong verb
for most of them.

**Where they actually live.** Neither profile has a local `mcpServers` block;
both are empty. The first-party profile's
`mcp-user-tool-toggles.json` holds 270 tool toggles keyed
`<server-uuid>:<tool-name>` across 13 server UUIDs plus a `local` owner, all
under one account-scoped owner id. Those are *preferences about* connectors,
not connector definitions. The definitions are served from the Claude.ai
organisation, which is why the app also tracks a per-org extension blocklist
fetched from the org's `dxt/blocklist` endpoint. There is no local file to
copy, so a file-level sync would produce toggles pointing at servers the
third-party profile cannot resolve.

**What the third-party surface accepts.** The dialog's Connectors tab exposes
`managedMcpServers` ("Org-pushed MCP servers: remote HTTP/SSE or local stdio
command. May embed bearer tokens"), an `Add server` menu offering Blank, two
remote templates (Microsoft 365, Box) and three built-in servers (Microsoft
365, Web search, GitHub), plus `Allow user-added MCP servers` (on) for local
stdio servers added through Developer settings, `mcpPersistentAlwaysAllowEnabled`,
`mcpToolTimeoutSec`, and `Allow desktop extensions` for `.dxt`/`.mcpb`
(currently off, and local install additionally requires an org policy
backend in third-party mode).

**Therefore, three buckets:**

1. **Local stdio servers: fully reproducible.** These are declarations the
   installer can own in the third-party config entry, deterministically and
   with a receipt. Same treatment as the four inference values.
2. **Remote HTTP/SSE servers: reproducible as declarations, but each needs its
   own sign-in.** They are listed with a URL and OAuth mode, so the entry can
   be written, but tokens are per-profile; the third-party profile's hosted
   MCP OAuth store starts empty and the user authorises each one once. That is
   a one-time cost, not a blocker.
3. **Org-served connectors and the account's 270 tool toggles: not copyable
   here.** They come from the Claude.ai organisation against the signed-in
   identity. Reproducing them means an org or bootstrap change, which is
   outside this plan's authority. Sign-in itself is retained, so if the org
   serves connectors to the third-party profile they will appear on their own;
   that is an observation to make, not something to force locally.

**Consequence for "smoothest install".** The installer can carry buckets 1 and
2 and should, since those are exactly the deterministic, owned-value cases the
existing helper design already handles. Bucket 3 must be reported honestly at
install time rather than silently half-copied. A migration that wrote 270
toggles for servers the profile cannot resolve would look like a successful
sync and behave like a broken one.

**Open question to settle before building this.** On this machine both
profiles have zero locally configured MCP servers, so there is currently
nothing in buckets 1 or 2 to migrate. Enumerate the real connector inventory
in a fresh third-party session first (after sign-in has had a chance to
populate org-served connectors) and only then decide whether the installer
needs connector support at all. Do not build a migration for an empty set.

## Scope and authority

In scope: the `models_listing()` tier projection with tests; a desktop attach
and detach helper mirroring `packaging/claude_config.py`; `install.py` wiring;
docs. Out of scope and separately gated: paid inference, billing acceptance,
release, any org or managed-policy change, any bootstrap server, and copying
first-party MCP or connector state into the third-party profile.

Source work uses the worktree above, `develop` -> PR, required review and the
repo gates. Never push to `main`.

## Steps and verification

1. **Tier projection.** Add the tier field to `models_listing()`. Keep the
   existing ordering and labels untouched. Cover in
   `tests/test_claude_ingress.py`: every row carries a valid tier word, the
   Anthropic aliases keep their own word, non-Anthropic rows read `sonnet`,
   and the row key set is exactly the three expected keys.
2. **Desktop helper.** Add a desktop counterpart to `claude_config.py` owning
   exactly the four values above in the applied `configLibrary` entry, plus
   the third-party profile's `deploymentMode`. Same discipline as the CLI
   helper: private before image, atomic replacement with mode 600, owned
   values only, receipt entry recording the pre-attach snapshot, refusal when
   an owned value was hand-edited to something else, and a detach that
   restores exactly the prior values and drops the claim. Never write
   `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN`. Never invent an OIDC
   credential. Honour `CLAUDE_USER_DATA_DIR` as the app does.
3. **Installer wiring.** Extend the client selection so the desktop surface
   can be attached and detached alongside the existing CLI attach, refusing
   to attach when `claude_mode` is `none`, and detaching on service-only
   install and uninstall exactly as the CLI attach does today.
4. **Connector inventory and optional carry.** In a fresh third-party session,
   enumerate which connectors appear on their own from the org and which are
   genuinely absent. If and only if real local stdio or remote entries exist,
   extend the desktop helper to own `managedMcpServers` entries with the same
   receipt and conflict rules, never writing bearer tokens and never copying
   the account-scoped tool toggles. Report bucket 3 as a stated limitation.
5. **Tests and gates.** Mirror `tests/test_install_config.py` with temporary
   directories and fake boundaries: preserved unrelated fields, repeated
   attach idempotence, conflicting hand-edit refusal, custom data directory,
   exact detach. Then the repo gates: full unittest discovery,
   `compileall`, `check_source_limits.py`, then `pre-commit-review`.
6. **Live readback.** Detach, confirm the app returns to first-party mode
   with native models and sign-in intact, then reattach through `install.py`
   and confirm a fresh session's picker lists 20 rows. Record the client
   version and both discovery counts in `docs/compatibility.md`, and record
   the coexistence limit in `docs/claude-code.md`.
7. **Release hygiene.** `CHANGELOG.md` plus `packaging/VERSION` for the
   user-visible discovery change.

## Completion

- [ ] 20 of 20 rows discovered from the real router in a fresh desktop session.
- [ ] Native sign-in and first-party profile state intact after attach,
  detach and reattach.
- [ ] Attach and detach performed by `install.py`, not by hand, with receipt
  and conflict refusal covered by tests.
- [ ] Connector inventory recorded, with any carried entries proven in a fresh
  session and the org-served limitation stated rather than worked around.
- [ ] Docs distinguish configured, restarted, discovered and probed states,
  and state the coexistence limit plainly.
- [ ] Repo gates and review pass; worktree cleaned after verified integration.

Stop for a managed-policy conflict, loss of native sign-in, any prompt for a
real gateway credential, secret output, or a discovery count that changes
without a configuration change. Paid tool round trips and billing remain
Plan 052. Do not patch client binaries; the asar was read as evidence only.
