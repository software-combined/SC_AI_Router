# Plan 051: Connect Claude CLI and desktop while preserving subscription auth

> Planning only. Client settings, login and running sessions are unchanged.
> Paid inference requires a separately approved Plan 052 run.

Priority P1; effort M; risk HIGH (authentication and client configuration).
Planned 2026-09-09 at `96a305abbd381a2f4fb336d65bcc5078a016bf25`.

## Outcome and dependency

First observable proof: a fresh CLI session lists gateway and native Claude
models, and a fresh desktop Code session reaches the same local router through
its separate configuration while retaining native sign-in. Billing and real
tool completion are Plan 052 gates. Require Plan 050's healthy service or
equivalent fresh evidence; the full Plan 049 installer is not a prerequisite
for a reversible local setup proof.

## Current state and canonical contracts

Repository: `software-combined/SC_OpenRouter_adapter`, local
`~/Documents/Github/SC_Codex_openRouter_adapter`; Python 3.14+, stdlib only.
Read `AGENTS.md`, `docs/claude-code.md`, `codex_router/claude.py`,
`codex_router/router.py`, `tests/test_claude_ingress.py` and
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
client-configuration helper if Plan 049 has landed one. Add a helper only for
a reproduced setup defect, reusing Plan 049's ownership receipt design. Source
work uses one owned worktree, current instructions, required review and
`develop` -> PR -> `main`. Check drift with
`git diff --stat 96a305a..HEAD -- codex_router packaging tools tests docs`.

## Steps and verification

1. **Preflight both clients.** Verify versions, native login source and effective
   route/override presence. Derive the private base locally without printing
   it. Confirm discovery and unauthenticated 403. Existing key/token/provider
   or managed overrides that prevent subscription auth are conflicts to report,
   not settings to erase silently.
2. **Prove CLI discovery.** Start a fresh environment with the private loopback
   base and `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=true`; leave
   `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` absent. Never give the client
   the router's OpenRouter key. Confirm `/status` retains native login, the
   cache refreshes and `/model` lists registry aliases plus subscription
   options. Cache existence alone is insufficient. Output only redacted
   discovery diagnostics; do not expose raw debug logs.
3. **Persist the proven CLI values.** Merge only those two owned `env` values
   into effective user settings (`CLAUDE_CONFIG_DIR` when set). Preserve a
   private before-image and exact ownership record, with atomic replacement
   and private permissions. Check the observed `[1m]` default against current
   model/client syntax. If still invalid, remove only that stale field to
   restore the native default, retaining its prior value privately; preserve
   any valid user preference. Verify again in a fresh CLI session. Detach
   restores only owned unchanged values and stops on conflicting hand-edits.
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
   service. Real model/tool and billing proof follows in Plan 052.

## Test plan and completion

If configuration logic changes, use temporary settings and fake boundaries to
test preserved fields, repeated attach, conflicting edits, custom config
directory and exact detach. Match `tests/test_install_config.py`; ingress
regressions belong in `tests/test_claude_ingress.py`.

```sh
python3.14 -m unittest tests.test_claude_ingress tests.test_install_config
python3.14 -m unittest discover -s tests -t .
python3.14 -m compileall -q codex_router tools tests
python3.14 tools/check_source_limits.py
```

- [ ] Fresh CLI and desktop discovery recorded independently; login retained.
- [ ] Exact restoration preserves other settings, Codex and the shared router.
- [ ] No credential override or paid call used to force setup success.
- [ ] Docs distinguish configured, restarted, discovered and probed states.
- [ ] Source changes pass review, commit/integration and integrated checks;
  owned merged worktrees/branches are cleaned; plan/index status updated.

Stop for managed-policy conflict, missing safe desktop auth mode, auth loss,
secret output or unexplained discovery drift. Do not patch client binaries.
Reusable plugin setup remains Plan 049/053's work.
