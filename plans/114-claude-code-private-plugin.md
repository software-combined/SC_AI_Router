# Plan 114: Deliver the private Claude Code router setup plugin

> Planning only. No marketplace publication, staff-machine changes, paid
> calls or release is authorised here. Plan 112 is unchanged.

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
6. **Publish privately when authorised.** Add one pinned GitHub/git source
   entry for the adapter root, matching the marketplace's current schema.
   Validate and test staff-user access without an admin proxy or tokens in
   source URLs. Verify install/upgrade from the cached package and executable
   paths after update. Runtime feed and plugin refresh remain independent.
7. **Accept on staff machines.** First supported release requires designated
   macOS, native Windows and Arch Claude CLI machines, recording OS/CPU and
   client versions. Reuse Arch contribution and Plan 112 service/bootstrap
   work. Verify desktop on the designated Mac separately; no new Windows/Linux
   desktop promise is implied. Run the approved Plan 115 pair on each promised
   surface. Missing hosts/access/billing evidence blocks supported publication,
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

Stop for missing installer contract, invalid schema/cache paths, managed-auth
conflicts, unknown writers or missing pilot evidence. Do not expand the plugin
into a model host or provider-registration system.
