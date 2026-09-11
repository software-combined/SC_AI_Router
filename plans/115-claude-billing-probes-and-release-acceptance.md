# Plan 115: Prove Claude tool execution, billing separation and release readiness

> Planning only. Paid runs need explicit model/surface and spend approval.
> No probe, tag, release or rollout is authorised by this document.

> **Amended 2026-09-11** (`1440645`) after review
> `2026-09-11-claude-router-development-branch-review.md` (F8, F9, and the
> per-surface acceptance rule). Adds: Messages-ingress compatibility
> contract with its tests and one probe leg; route-policy errors and bounded
> provenance; a real MCP invocation whose returned marker is used, not only
> the built-in Read probe; and per-surface route requirements replacing a
> universal desktop pair where the client cannot offer both routes. Spend
> approval and correlated billing evidence are unchanged.

Priority P1; effort M; risk HIGH (paid inference, auth and release).
Planned 2026-09-09 at `96a305abbd381a2f4fb336d65bcc5078a016bf25`.

## Outcome

First observable proof: two fresh Claude CLI sessions read a synthetic marker
through the allowed Read tool, one with an OpenRouter model charged to the
intended key, one with a native Claude model using subscription auth. Repeat
both in desktop Code before claiming app acceptance. **Amended 2026-09-11:**
desktop acceptance requires the routes that surface actually offers (see the
per-surface table below), not an unconditional pair; and a built-in Read
result alone is not tool acceptance. Router health and `served_models` are
not billing proof.

## Source, scope and prerequisites

Repository: `software-combined/SC_OpenRouter_adapter` (private), local
`~/Documents/Github/SC_Codex_openRouter_adapter`; Python 3.14+, stdlib only.
Read `AGENTS.md`, `docs/claude-code.md`, `docs/compatibility.md`,
`docs/operations.md`, `ai_router/claude.py`, `ai_router/credentials.py`,
`tests/test_claude_ingress.py`, `tools/probe_codex_runtime.py`,
`tests/test_probe_harness.py` and `.github/workflows/release.yml`. Reuse the
existing synthetic-tool proof pattern, not Codex's wire protocol for Claude.

Plan 108 provides service/update evidence; Plan 113 provides separate CLI/app
configuration evidence. If desktop cannot retain subscription auth, CLI proof
can be recorded but overall acceptance stays open. Snapshot 2026-09-09:
router `0.6.5.17`, CLI `2.1.223`, desktop `1.46388.4`; recheck immediately
before probing. Source VERSION `0.6.5` and runtime build are distinct. Unit
tests and the handover do not establish real Claude client acceptance.

Scope: a small `tools/probe_claude_runtime.py` only if repeatability needs it,
adjacent offline tests, and compatibility/Claude docs. Fix only a demonstrated
ingress blocker in the existing module and tests. No roster expansion,
unproven model-tier promotion, content logging, fleet rollout or retry loop.
Use one owned worktree and reconcile `codex/claude-finish` ownership first.
Check drift with
`git diff --stat 96a305a..HEAD -- ai_router tools tests docs .github packaging`.

## Steps

1. **Freeze the contract before approval.** Name one current OpenRouter
   registry slug and one valid native subscription model ID, with CLI and
   desktop as distinct surfaces. Use a new temporary workspace with a synthetic
   marker, no project data, narrow Read permission and a task that must read
   the file and return its value. Bound turns, timeout, output and retries.
   Verify current flags through `claude --help`; never bypass permissions.
   Present exact scope/spend for approval and stop at its limit. Previous
   paid approval is not an unlimited budget.
2. **Prove the harness offline.** Mock subprocess/provider boundaries only.
   Require completed Read tool result and exact final marker, not a plausible
   answer. Protect missing tool, wrong marker, timeout/nonzero exit and malformed
   output. Redact URLs, credentials and raw request/tool content in errors.
   Match unittest/tempfile patterns; tests never contact providers or real state.
3. **Run the approved CLI pair.** Use fresh sessions with private base and
   discovery setting, native login and no key/token overrides. Use a known
   OpenRouter alias/slug, then a native no-slash Claude ID for subscription.
   Bare `anthropic/...` is OpenRouter billing. Inspect each leg before starting
   the next. Record requested model and returned identity separately; absent
   served identity remains unverified.
4. **Correlate routing and billing.** Inspect only non-content metadata for
   upstream/status. Verify OpenRouter usage on the intended user's account/key
   through authenticated dashboard/API evidence, correlated by generation or
   request where available. Concurrent activity makes a balance delta alone
   insufficient. The subscription leg requires native-auth status and successful
   Anthropic upstream routing without substituted API credentials; verify no
   corresponding OpenRouter generation. Do not record credential values. Delayed
   or unattributable accounting stays pending, never inferred from a model label.
5. **Run the approved desktop leg(s).** Repeat in fresh local Code sessions with
   the same synthetic task and independent evidence. Launching a successful CLI
   subprocess from the app does not prove its Code session. Stop on auth/billing
   mismatch and restore only owned client settings. Do not restart the shared
   router for a client-only issue or repeat a chargeable call automatically.
   **Superseded in part 2026-09-11:** the universal desktop pair; run the
   routes that surface offers per the per-surface table in the amendment
   section. A route the client cannot offer is recorded as a limitation for
   the promised surface, not silently skipped or faked through another profile.
6. **Record and integrate.** Compatibility rows record date, OS/architecture,
   source commit, router release, client versions, model IDs, tool outcome,
   upstream, billing evidence status and limits. Keep tokens, private URLs,
   receipts, raw logs and sensitive dashboard payloads outside Git. Plan/index
   status distinguishes source, CLI, desktop, billing, merge, release and runtime.
7. **Release after acceptance.** Complete checks and current pre-commit review;
   integrate the owned branch into `develop`, then a PR to `main`, preserving
   other work. Re-run checks at each merged tree. Any client upgrade triggers
   the repo compatibility rule: one OpenRouter and one OpenAI model through
   `probe_codex_runtime.py`, plus both Claude routes in real Claude Code. Obtain
   approval for extra paid calls. Verify current workflow tag/VERSION comparison;
   source semver and runtime build identifiers must meet that actual contract.
   Tag only when requested. Verify published bundle/feed identity, then approved
   installation health and fresh client tool round trips before rollout acceptance.

## Commands and done criteria

All commands must exit 0; run new harness tests directly if added:

```sh
python3.14 -m unittest discover -s tests -t .
python3.14 -m compileall -q ai_router tools tests
python3.14 tools/check_source_limits.py
```

- [ ] Both CLI routes complete the tool task with correlated auth/billing proof.
- [ ] Each promised surface independently passes the routes that surface
  offers, or its acceptance stays open (per-surface table in the amendment).
- [ ] One real MCP tool call returns an unpredictable marker that appears in
  the answer; a denied call and an unavailable-connector recovery are recorded.
- [ ] The ingress compatibility contract passes offline and through one live
  OpenRouter Messages leg before any dependent client feature is enabled.
- [ ] Compatibility evidence records exact installed versions and limitations.
- [ ] Source changes include required CHANGELOG/VERSION, reviews, integration
  and checks; release/rollout gates are separately recorded.
- [ ] Remove only owned integrated worktrees/branches after proving no unique,
  dirty, untracked or needed ignored artifacts remain.

Stop for missing paid authority, unclear account attribution, unexpected auth,
missing real tool completion, client drift or writer conflicts. Plan 114
consumes this evidence; packaging alone does not promote a Preview route.

## Amendment (2026-09-11)

Review findings F8 and F9, and the per-surface acceptance rule, in
`2026-09-11-claude-router-development-branch-review.md`.

### Per-surface route requirements

Replace the unconditional desktop pair with the routes each promised surface
actually offers. Codex's verification never closes a Claude surface.

| Surface | Routes required for that surface's acceptance |
|---|---|
| Claude Code CLI | One OpenRouter route and one native-subscription route, each with a completed tool result and correlated billing evidence |
| Desktop Code, gateway profile | Every route the profile lists and the client actually offers; the coexistence limit means the picker carries gateway rows only, so record which route each leg proves and keep the surface's acceptance open if the native-subscription route is not offered |
| Desktop Cowork / Chat | Only when promised; qualify separately, and do not infer from desktop Code |

Route eligibility is per surface. Discovery must apply the same allowlist as
routing (`ai_router/claude.py::models_listing()` currently receives none), and
an unknown gateway-namespace id must fail as an error rather than silently
selecting the subscription route. Preserve intentionally supported native
model ids.

### Messages ingress compatibility contract (F8)

Separate credential isolation from protocol forwarding:

- Never forward subscription authorization, cookies, account headers or the
  client's credentials to OpenRouter; keep the router key off every
  subscription request. Plan 138 separately drops `Cookie` from the
  subscription passthrough; this contract forbids the same headers on the
  OpenRouter route.
- Forward the Anthropic protocol version and the feature/version headers each
  upstream actually supports, so client features that depend on them are not
  silently downgraded. Do not freeze a list of individual beta values that
  breaks on a client upgrade.
- Direct registry slugs travel unmodified; alias requests are re-serialized
  after the model rewrite, so the documentation claim is "byte-identical for
  direct slugs", not blanket. Correct `docs/claude-code.md` accordingly.
- Error/retry metadata, tool ids, caching fields and streaming behaviour keep
  their existing shared semantics; a 401/403/429 leg is part of the offline
  matrix.

Offline tests cover the header/feature matrix per upstream with fake
boundaries. One approved live leg exercises feature negotiation against the
real OpenRouter Messages endpoint before any dependent client feature is
enabled. This is a forwarding gap, not proof that ordinary function calling
fails today.

### Bounded provenance (F9)

Record only non-content request metadata: requested identity, reported served
identity when available, route, timing, usage and error category. A missing
served identity stays unknown; never infer it from the requested model. The
Claude passthrough path gains the same bounded tracking discipline the other
path already has, without content capture.

### Tool acceptance

Replace the built-in Read-only proof with a real MCP tool invocation whose
unpredictable returned marker must appear in the answer, plus a denied call
and recovery from an unavailable connector. Deferred tool search, if used, is
qualified as its own client-build/route/model capability and is never enabled
globally (see Plan 121's amendment).
