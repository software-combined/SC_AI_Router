# Plan 148: Claude Code drift check and attachment contract

> **Executor instructions**: Follow this plan step by step. If a STOP condition
> occurs, stop and report. When done, update this plan's status row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 3515c6a..HEAD -- packaging/claude_config.py ai_router/claude.py ai_router/ingress.py packaging/diagnostics.py docs/claude-code.md docs/compatibility.md tests/`
> Coordinate with 113 (the CLI/desktop contract) and 120/121; do not run two
> writers against the Claude config path at once.

## Status and first proof

- Priority P3; effort S-M; confidence HIGH; category dx/operability.
- Depends on 146's shared transport guards for the 415 path and on 147 for the
  `--doctor` row it reports through (add the row through 147's registry rather than
  a second registration path).
- Source: `plans/2026-09-12-external-router-review.md`, the findings row
  "Claude Code" and the "Explicit rejections" entry for the launcher.
- First proof: after attaching Claude Code, `--doctor` (147) reports whether the
  models the router serves still match the snapshot taken at attach, and the docs
  state why `ANTHROPIC_AUTH_TOKEN` must stay unset.

## Why this matters

The external router keeps a published-catalog snapshot for Claude Code and reports
drift; we attach by merging two owned keys into `~/.claude/settings.json` and
never record what the client was told. When a registry row changes or a client
upgrade rewrites settings, nothing notices until a user does.

The external launcher is deliberately **not** adopted: an alias that only routes
when the user types `claude-router` breaks a plain `claude` invocation, and its
`ANTHROPIC_AUTH_TOKEN=<router secret>` conflicts with our subscription
passthrough, which requires the client's own credential to reach the router
untouched. Our merge already writes only owned keys and restores prior values on
detach. Record that reasoning here so a later reader does not "harmonise" the two.

## Scope

**In scope**: `packaging/claude_config.py`, `ai_router/claude.py`,
`packaging/diagnostics.py`, `packaging/install.py` (the doctor row registration
147 owns), `docs/claude-code.md`, `docs/compatibility.md`,
`tests/test_claude_config.py`, `tests/test_claude_ingress.py`, `tests/test_status.py`.
**Out of scope**: replacing the settings merge with a launcher; effort
normalisation (recorded as a later, demand-driven item); new client targets.

## Steps

1. **Snapshot on attach.** When the installer attaches Claude Code, write a small
   snapshot beside the existing receipt: the served listing ids, their display
   names and tiers, and the timestamp. It is state, not a release artefact.
2. **Drift read.** A read-only check compares the snapshot with the live
   `GET /v1/models` listing and reports `match`, `drift` (with the added and
   removed ids) or `unknown` (router down); `--doctor` surfaces it as a row.
3. **Contract note.** Document in `docs/claude-code.md`: only `ANTHROPIC_BASE_URL`
   belongs in client settings; `ANTHROPIC_AUTH_TOKEN` and `ANTHROPIC_API_KEY`
   must stay unset or passthrough breaks; the launcher alternative was considered
   and rejected, with the two reasons above.
4. **Hardening flags, verified only.** Evaluate
   `CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT`, `ATTRIBUTION_HEADER=0`,
   `ENABLE_TOOL_SEARCH=false` and unsetting the Bedrock/Vertex/Foundry variables
   against the installed Claude Code version, one at a time, and add only those
   that a real session proves necessary. The default is no change.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Focused | `python3.14 -B -m unittest tests.test_claude_config tests.test_claude_ingress tests.test_status tests.test_safe_diagnostics` | pass |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | exit 0 |

## Done criteria

- [ ] Attach writes the snapshot; detach removes it with the other owned state.
- [ ] Drift reports added and removed ids, and `unknown` when the router is down.
- [ ] The contract note and the rejected launcher reasoning are in `docs/claude-code.md`.
- [ ] Any adopted hardening flag is justified by an observed session, not a guess.
- [ ] Full suite, compile and limit gates pass; `plans/README.md` row updated.

## STOP conditions

- A live-session check turns out to need client or account mutation: stop; that
  is an owner gate, not this plan.
- Snapshot writing overlaps the activation receipt's writer: stop and extend the
  existing receipt rather than adding a second writer.

## Maintenance notes

- Live proof for the CLI and desktop surfaces stays with 113/115/120; this plan is
  source and offline tests only.
- Effort normalisation (mapping `output_config.effort` or `thinking.type` onto
  `reasoning.effort` for non-Anthropic rows) is recorded, not implemented: a
  later, demand-driven option, with byte-identical passthrough as the default.
- Tilde-aliased rows restore their alias on read; the snapshot records the id the
  client was actually served.
