# Plan 113: Connect Claude CLI and desktop while preserving subscription auth

> Planning only. Client settings, login and running sessions are unchanged.
> Paid inference requires a separately approved Plan 115 run.

> **Amended 2026-09-11** (`1440645`) after review
> `2026-09-11-claude-router-development-branch-review.md` (F2, F3, F5, F8, F9).
> Superseded in place below: Step 2's credential precondition and Step 3's
> `[1m]` suspicion; Plan 121 Step 1 owns the corrected wording. The
> amendment section at the end adds the per-surface setup invocation, the
> single canonical Anthropic billing policy, and the first-run key-window
> requirement. Client attach/repair/detach mechanics are Plans 112/114's; paid
> acceptance stays Plan 115's.

Priority P1; effort M; risk HIGH (authentication and client configuration).
Planned 2026-09-09 at `96a305abbd381a2f4fb336d65bcc5078a016bf25`.

## Outcome and dependency

First observable proof: a fresh CLI session lists gateway and native Claude
models, and a fresh desktop Code session reaches the same local router through
its separate configuration while retaining native sign-in. Billing and real
tool completion are Plan 115 gates. Require Plan 108's healthy service or
equivalent fresh evidence; the full Plan 112 installer is not a prerequisite
for a reversible local setup proof.

## Current state and canonical contracts

Repository: `software-combined/SC_OpenRouter_adapter`, local
`~/Documents/Github/SC_Codex_openRouter_adapter`; Python 3.14+, stdlib only.
Read `AGENTS.md`, `docs/claude-code.md`, `ai_router/claude.py`,
`ai_router/router.py`, `tests/test_claude_ingress.py` and
`docs/compatibility.md`. Reuse existing alias resolution/provider selection
and fake-upstream tests; do not add another provider path.

Observed 2026-09-09: CLI `2.1.223`, desktop `1.46388.4`, router `0.6.5.17`
with 22 discovery entries. User `~/.claude/settings.json` lacked the matching
base/discovery flag, contained a model value with `[1m]`, and had no key/token
overrides in its `env` object. A gateway cache existed. Shell/project/managed
settings and desktop authentication were not established by those checks.

Known `claude/<vendor>/<name>` aliases resolve to registry OpenRouter slugs;
bare `anthropic/...` discovery IDs also bill OpenRouter. Native Anthropic model
IDs have no slash and retain subscription routing. Unknown `claude/` IDs are
not automatically OpenRouter models. Direct registry slugs remain unchanged;
only known alias bodies are rewritten.

Official sources checked 2026-09-09; recheck against installed versions:

- [Gateway setup](https://code.claude.com/docs/en/llm-gateway-connect): CLI
  discovery uses `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY`; credential
  variables override saved login. Desktop reads separate third-party inference
  configuration, not CLI base-URL settings.
- [Desktop](https://code.claude.com/docs/en/desktop): inspect the installed Code
  surface and session environment independently.
- [Gateway support](https://code.claude.com/docs/en/llm-gateway): Anthropic does
  not support Claude Code routing to non-Claude models. Report SCG's tested
  compatibility without claiming vendor endorsement.

## Scope and authority

After execution is requested, configure this designated Mac's CLI and desktop
Code surface. No general chat/Cowork gateway promise, remote/cloud routing,
dummy credentials, managed-policy bypass or logout. Inspect effective settings
and credential-source names/presence without their values; preserve policies
and unrelated fields.

Source scope: Claude/compatibility docs, relevant ingress tests and the existing
client-configuration helper if Plan 112 has landed one. Add a helper only for
a reproduced setup defect, reusing Plan 112's ownership receipt design. Source
work uses one owned worktree, current instructions, required review and
`develop` -> PR -> `main`. Check drift with
`git diff --stat 96a305a..HEAD -- ai_router packaging tools tests docs`.

## Steps and verification

1. **Preflight both clients.** Verify versions, native login source and effective
   route/override presence. Derive the private base locally without printing
   it. Confirm discovery and unauthenticated 403. Existing key/token/provider
   or managed overrides that prevent subscription auth are conflicts to report,
   not settings to erase silently.
2. **Prove CLI discovery.** Start a fresh environment with the private loopback
   base and `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=true`; leave
   `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` absent. **Superseded
   2026-09-11:** this credential precondition was documented backwards (the
   discovery fetch needs a credential present, and `ANTHROPIC_AUTH_TOKEN`
   changes which credential the listing sends); the verified statement is
   Plan 121 Step 1's. The rule that survives: never give the client the
   router's OpenRouter key. Confirm `/status` retains native login, the
   cache refreshes and `/model` lists registry aliases plus subscription
   options. Cache existence alone is insufficient. Output only redacted
   discovery diagnostics; do not expose raw debug logs.
3. **Persist the proven CLI values.** Merge only those two owned `env` values
   into effective user settings (`CLAUDE_CONFIG_DIR` when set). Preserve a
   private before-image and exact ownership record, with atomic replacement
   and private permissions. **Superseded 2026-09-11:** the `[1m]` suspicion was
   wrong; it is valid client shorthand, stripped client-side, and the router
   never sees it. Do not remove that field; Plan 121 Step 1 corrects the
   record. Verify again in a fresh CLI session. Detach restores only owned
   unchanged values and stops on conflicting hand-edits; the three-way
   ownership rule in Plan 114's amendment section strengthens this.
4. **Qualify desktop separately.** Inspect Help -> Troubleshooting -> Enable
   Developer Mode, then Developer -> Configure Third-Party Inference where
   available, or the administrator-supplied configuration. Record supported
   fields and rollback before saving; coordinate restart with active sessions.
   Configure the private base only if native subscription credentials remain
   available for passthrough. Never invent a credential for a required field
   or override managed policy. If this mode replaces auth or cannot preserve
   subscription access, stop the desktop leg and record the exact limitation.
   CLI success cannot close the desktop objective.
5. **Verify desktop discovery and restore.** Start a fresh local Code session
   and inspect the current model list/endpoint without paid inference. Verify
   the session is local, not a host where loopback means another machine.
   Restore the exact owned config in a controlled check and prove native
   routing returns, then reattach if authorised. Preserve Codex and the shared
   service. Real model/tool and billing proof follows in Plan 115.

## Test plan and completion

If configuration logic changes, use temporary settings and fake boundaries to
test preserved fields, repeated attach, conflicting edits, custom config
directory and exact detach. Match `tests/test_install_config.py`; ingress
regressions belong in `tests/test_claude_ingress.py`.

```sh
python3.14 -m unittest tests.test_claude_ingress tests.test_install_config
python3.14 -m unittest discover -s tests -t .
python3.14 -m compileall -q ai_router tools tests
python3.14 tools/check_source_limits.py
```

- [ ] Fresh CLI and desktop discovery recorded independently; login retained.
- [ ] Exact restoration preserves other settings, Codex and the shared router.
- [ ] No credential override or paid call used to force setup success.
- [ ] Docs distinguish configured, restarted, discovered and probed states.
- [ ] Source changes pass review, commit/integration and integrated checks;
  owned merged worktrees/branches are cleaned; plan/index status updated.
- [ ] Each promised surface has one literal setup invocation that configures
  only that surface (amendment below).
- [ ] One canonical Anthropic billing policy is in force and reported by
  `--status` (amendment below).

Stop for managed-policy conflict, missing safe desktop auth mode, auth loss,
secret output or unexplained discovery drift. Do not patch client binaries.
Reusable plugin setup remains Plan 112/114's work.

## Amendment (2026-09-11)

Review findings F2, F3, F5, F8 and F9 in
`2026-09-11-claude-router-development-branch-review.md`. These add scope to
this plan; the superseded marks above remove scope.

1. **Per-surface setup invocation.** Today the shared
   `skills/manage-router/SKILL.md` setup example (`install.py --setup`) omits
   `--clients` and therefore attaches Codex; `packaging/diagnostics.py:109`
   preflights `(args.client or 'codex')` rather than the selected clients; and
   the installer resolves `--clients` after the same-version early return at
   `packaging/install.py:326`. Claude-only and Claude-desktop setup must be
   reachable from a clean machine with no Codex installed, through literal
   commands recorded in the skill and exercised in tests. F1's lifecycle
   mechanics (same-version attach and repair) are Plans 112/114's; this plan owns
   the qualification evidence that the shipped command string configures the
   named surface and no other.
2. **One canonical Anthropic billing policy.** `claude_mode` is stored and
   checked by the installer, while the Messages policy passes only
   `anthropic_mode` (`ai_router/protocols/messages.py:15`), so runtime routing
   follows the OpenAI mode when the Anthropic override is absent. Keep
   attachment presence, subscription-passthrough permission and desktop
   profile selection as separate concepts, define one canonical owner for the
   billing policy, migrate legacy state explicitly, and show the effective
   policy in `--status`. `claude_mode=none` must not silently block attachment
   where the supported client can run OpenRouter-only; that path is enabled
   only once client authentication requirements are qualified.
3. **First-run requirements.** The `clients == 'claude'` branch returns before
   the `--setup` key window is printed or opened
   (`packaging/install.py:481-507`), so the first-run promise and the Claude
   attach cannot both be met today. Credential onboarding completes before any
   client-specific return; the post-failure key-recovery path is validated
   separately and is not evidence of first-run success.
4. **Protocol and discovery contract (F8, F9).** Feature and version headers
   are not forwarded to OpenRouter, so the "byte-identical" claim holds only
   for direct registry slugs, and discovery does not apply the routing
   allowlist. The implementable contract, its tests and the live probe leg are
   Plan 115's (ingress compatibility) and Plan 121 Step 5 (listing policy);
   this plan records which client features were verified against each upstream
   and must not enable a dependent client feature before that proof.
