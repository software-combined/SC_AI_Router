# Plan 114: Deliver the private Claude Code router setup plugin

> Planning only. No marketplace publication, staff-machine changes, paid
> calls or release is authorised here. Plan 112 is unchanged.

> **Amended 2026-09-11** (`1440645`) after review
> `2026-09-11-claude-router-development-branch-review.md` (F1, F2, F3, F4,
> W4).
> Plan 112's installer contract already specifies same-version
> configure/repair and prior/installed receipt values; `develop` does not
> implement them yet, so this plan's setup workflow blocks on the contract
> whatever the execution order. The amendment section adds binding
> acceptance for selection-aware preflight, the first-run key window,
> conflict-safe restoration, and desktop distribution proof separate from
> CLI. "Plan 112 is unchanged" still holds: no 112 text is rewritten.

Priority P1; effort M; risk HIGH (installer and client-config authority).
Planned 2026-09-09 at `96a305abbd381a2f4fb336d65bcc5078a016bf25`.

## Outcome and dependencies

First observable proof: a signed-in user installs private `scg-openrouter` in
Claude Code, invokes setup, gets the shared router configured for Claude and
sees gateway models in a fresh session. Plan 115 separately proves tool use
and billing before acceptance.

This is Plan 112's Claude-plugin execution slice, not a second package or
installer. Plan 112 owns shared bootstrap, three-OS installation, receipts,
Windows ACLs, service lifecycle and AWS downloads. Plan 113 owns local CLI/app
qualification; Plan 115 owns paid acceptance. Metadata can be developed when
requested, but setup must use an implemented canonical installer contract.

## Canonical source

Adapter code, shared skill, installers and both manifests belong in private
`software-combined/SC_OpenRouter_adapter`, local
`~/Documents/Github/SC_Codex_openRouter_adapter`. Private
`software-combined/SC_Agent_plugins` is the discovery catalogue. Neither repo
nor plugin becomes public. Plan 106 supersedes the older public-download
proposal: runtime downloads are private and token-gated, while unattended
updates no longer need recipient GitHub access after that cutover.

Read `AGENTS.md`, Plan 112's installer contract, `docs/claude-code.md`,
`packaging/install.py`, `tools/disable.py` and `tests/test_install_config.py`.
Before catalogue changes, read that repo's instructions and current
`.claude-plugin/marketplace.json`. Recheck schemas, versions and cache behavior.

Official references checked 2026-09-09:

- [Plugin reference](https://code.claude.com/docs/en/plugins-reference):
  `.claude-plugin/plugin.json` identifies the plugin; root-level skills gain
  its namespace. Use the installed client's validator and local testing mode.
- [Marketplaces](https://code.claude.com/docs/en/plugin-marketplaces): test
  private source access with the designated staff identity.
- [Gateway setup](https://code.claude.com/docs/en/llm-gateway-connect): desktop
  inference configuration is separate from CLI environment settings.

Observed clients were CLI `2.1.223`, desktop `1.46388.4`; recheck before tests.
A plugin provides workflows/scripts, not provider registration. No MCP server,
agent, hooks or automatic startup mutation is needed. Runtime stays outside
the plugin cache. Python runtime remains 3.14+ with stdlib only.

## Scope and ownership

Adapter scope: `.claude-plugin/plugin.json`, shared
`skills/manage-router/SKILL.md` and short references, validation tests,
Claude docs, CHANGELOG/VERSION and plan/index. Coordinate any matching
`.codex-plugin/plugin.json` version/schema adjustment with its writer.
Marketplace scope is one Claude catalogue entry and relevant docs; it needs
its own worktree, review and commit. Never edit either primary checkout.

Inspect owners and reuse one writable worktree per repository. Check drift:
`git diff --stat 96a305a..HEAD -- .claude-plugin .codex-plugin skills packaging tools docs tests`.
No competing installer, public directory submission, bundled secrets/state,
new runtime models or overlapping Linux implementation. PR #3 by Brent Maxwell,
`codex/linux-service-support` -> `develop`, was open during planning and covers
catalogue compatibility, test isolation and Arch docs. Verify current scope
and ownership before relying on it; do not assume all installer work is included.

## Steps and verification

1. **Verify the reusable interface.** The implemented shared installer must
   provide status, `--clients claude`, attach/update/detach, preserved Codex
   attachment, same-version repair, private key entry and rollback. These are
   Plan 112 dependencies, not existing capabilities on the planning baseline.
   Complete that thin slice before activating the plugin setup workflow.
   **Amendment 2026-09-11:** verified absent on `develop`: `install.py:326`
   returns `up to date` before the client selection is resolved at `install.py:371`,
   preflight tests `args.client or 'codex'` (`diagnostics.py:109`), and the
   `claude` branch returns before the `--setup` window opens. See the
   amendment section for the required behaviour and acceptance.
2. **Add the Claude manifest.** Name `scg-openrouter`, use product strict
   semver and expose shared `skills/` through the supported schema. The whole
   adapter repository is the root so scripts reach `packaging/` without cache
   escapes or duplicated code. Validate relative paths and referenced files.
   Use the client's supported plugin-root mechanism, never a hardcoded cache.
3. **Provide one shared journey.** Use
   `/scg-openrouter:manage-router <action>` for setup, status, update and remove.
   Default to Claude; both clients only when requested. Quote native paths and
   call canonical bootstrap/installer commands. Status is read-only and redacted.
   Mutations follow the user's request and host policy; installing/enabling the
   plugin changes no service, settings, key or session. No bypass flags.
4. **Preserve credentials and auth.** Use Plan 107's central provisioning and
   private shared writer so recipients never paste their issued key. The
   local window remains its specified missing/revoked-key recovery path, never
   chat, skill arguments, credential overrides or marketplace settings.
   Preserve native login. CLI setup uses the
   receipt-owned two env settings; desktop uses Plan 113's separately qualified
   surface. Distinguish restart, discovery and paid acceptance. Missing desktop
   auth support is reported, never bypassed with a dummy token.
5. **Test installed lifecycle.** Run `claude plugin validate .`; inspect
   `claude --help` for local plugin flags. Load in a fresh test session and
   verify namespaced skill discovery before setup. Test repeated attach/update,
   Claude-only detach and both-client state with synthetic settings. Plugin
   removal alone leaves the external router usable. Claude detach preserves
   Codex and shared service; last-client removal follows explicit canonical
   uninstall, never a plugin hook.
   **Amendment 2026-09-11:** add a refused-detach case (post-attach hand edit
   of an owned value must stop the detach with the file unchanged) and an
   interruption case at each write boundary; detach must restore only values
   this router still owns.
6. **Publish privately when authorised.** Add one pinned GitHub/git source
   entry for the adapter root, matching the marketplace's current schema.
   Validate and test staff-user access without an admin proxy or tokens in
   source URLs. Verify install/upgrade from the cached package and executable
   paths after update. Runtime feed and plugin refresh remain independent.
7. **Accept on staff machines.** First supported release requires designated
   macOS, native Windows and Arch Claude CLI machines, recording OS/CPU and
   client versions. Reuse Arch contribution and Plan 112 service/bootstrap
   work. Verify desktop on the designated Mac separately; no new Windows/Linux
   desktop promise is implied. Run the approved Plan 115 leg(s) on each promised
   surface (per-surface table in Plan 115's amendment). Missing hosts/access/billing evidence blocks supported publication,
   not local manifest development.

## Tests, integration and completion

Adapter commands must exit 0:

```sh
claude plugin validate .
python3.14 -m unittest discover -s tests -t .
python3.14 -m compileall -q ai_router tools tests
python3.14 tools/check_source_limits.py
```

Add offline manifest/path tests only for actual package-execution contracts;
reuse existing installer tests for shared-client removal. No network in unit
tests. Run the marketplace's documented validator/checks in its worktree.
Both repositories require current pre-commit reviews and verified integration.
User-visible plugin behavior updates product version/changelog. Adapter work
lands on `develop`, then PR to `main`; tags/releases need separate authority.

- [ ] Private cached package loads the skill and invokes canonical scripts.
- [ ] Setup, discovery and auth/billing pass on every promised staff surface.
- [ ] Plugin removal, client detach and service uninstall stay distinct.
- [ ] No secrets/state or automatic mutation hooks shipped.
- [ ] Plans/index and compatibility docs record remaining gates precisely.
- [ ] Both repository changes are integrated/verified; only owned worktrees
  and branches are cleaned after proving no unique work or needed artifacts.
- [ ] Same-version Claude attach and repair run without a newer runtime and
  without touching the Codex attachment.
- [ ] A Claude-only host with no Codex passes the literal skill commands.
- [ ] The first-run key window completes before any client-specific return.
- [ ] Desktop distribution is proven separately from CLI distribution.

Stop for missing installer contract, invalid schema/cache paths, managed-auth
conflicts, unknown writers or missing pilot evidence. Do not expand the plugin
into a model host or provider-registration system.

## Amendment (2026-09-11)

Review findings F1-F4 and W4 in
`2026-09-11-claude-router-development-branch-review.md`. Plan 112 Stage 3 and
its installer-interface contract own the shared fix; this plan owns the
client-facing acceptance and must not work around a missing contract by
editing client settings from the skill. If 112's slice is not scheduled when
114 executes, 114 lands the minimal installer fix itself under its own
worktree rather than duplicating 112's design.

1. **Same-version attach and repair.** Adding Claude, repairing its
   attachment, opening the key window and detaching must all work against the
   already-installed runtime; only a genuinely newer release justifies a
   download, and a healthy service is never restarted just to add a client.
   Acceptance: start from the current runtime with an existing Codex
   attachment; add Claude; repeat; detach Claude; repair its attachment.
   Codex stays byte-unchanged and the runtime version is not fabricated.
2. **Selection-aware preflight and literal commands.** Resolve the client
   selection once and use that one resolution in preflight, installation,
   status and removal, so a Claude-only request never reports a missing Codex
   CLI. The skill ships one literal invocation per surface (Claude CLI,
   Claude desktop, Codex, both); tests execute those exact strings.
   Acceptance: on a clean machine with Claude but no Codex, preflight and
   setup neither require nor modify Codex.
3. **First-run key window.** With `--setup`, credential onboarding completes
   before the `clients == 'claude'` return. The existing recovery page for a
   missing or revoked key is validated separately and never recorded as
   first-run success. Keys stay out of chat, arguments, ordinary diagnostics
   and model conversations.
4. **Conflict-safe restoration and partial-write recovery.** Extend the
   receipt's prior/installed pair to a three-way record: original presence and
   value, installed value, and current value. Refuse a conflicting hand edit
   before mutating anything; a post-attach edit survives a refused detach;
   unrelated fields survive every operation; the original pre-attach snapshot
   survives partial repairs. Multi-file desktop attachment needs recoverable
   transaction handling across its writes and the receipt, so a failure
   between them is recoverable rather than half-owned. Reuse the existing
   receipt and atomic-write primitives; do not add a second ownership
   framework.
5. **Desktop distribution proof (W4).** Desktop's documented git marketplace
   flow does not fetch plugin sources located in another repository, and a
   catalogue entry can appear without the plugin installing. Prove desktop
   distribution separately from CLI: a built deployment package or an
   authenticated, digest-pinned archive, canonical source unchanged, ordinary
   staff never cloning private repositories. Never repurpose OpenRouter keys
   or loopback path tokens as download credentials.
