# Plan 065: Establish Kiro IDE and CLI integration contracts before implementation

> Planning/research only. This plan grants no installation, credential access,
> client mutation, paid request, interception, binary patching, or publication
> authority. A later implementation plan requires a supported inference hook.
>
> Drift check: `git diff --stat 6840312..HEAD -- codex_router/router.py codex_router/claude.py codex_router/providers.py docs/claude-code.md docs/compatibility.md docs/kiro-compatibility.md plans/049-agent-plugin-and-three-os-installation.md plans/051-claude-cli-and-desktop-gateway-setup.md plans/053-claude-code-private-plugin.md plans/README.md`
> Reconcile 062's moved source paths and recheck the official Kiro sources below.

## Status and outcome

- Priority P2; effort S for the bounded spike; risk LOW; category direction.
- Planned at `6840312`, 2026-09-09. Independent of implementation plans.
- Scope assumption: inspect both Kiro IDE and CLI separately. No reply selecting
  only one had arrived when drafted; do not infer they share inference settings.
- First proof: a dated compatibility decision for each client that identifies
  a documented extension mechanism and what remains unproven, or records that
  no supported custom inference hook was established. A supported negative
  result completes the spike without creating an adapter.

## Current evidence

The repository has no Kiro client adapter or settings contract. Current ingress
is Responses plus Codex native services (`router.py:154-169`) and Anthropic
Messages/count-tokens (`claude.py:25-26`). A client's MCP support does not imply
that it can route its own inference through either ingress.

Official sources inspected on 2026-09-09:

- [Kiro model overview](https://kiro.dev/docs/models/): describes supplied model
  selection and inference geographies.
- [Agent model field](https://kiro.dev/docs/custom-agents/configuration-reference/#model-field):
  the model ID must come from Kiro's model service; unavailable IDs fall back
  with a warning. This is not evidence of arbitrary endpoint registration.
- [Settings reference](https://kiro.dev/docs/reference/settings/): the inspected
  page did not establish a custom inference endpoint setting.

These observations do not prove that no mechanism can exist in a newer build
or another officially supported surface. They do require checking before a
Kiro adapter or compatibility claim is designed. Treat IDE and CLI versions,
custom tools, custom agents and inference routing as distinct facts.

## Scope

Read source and current official documentation. If installed, query only Kiro's
non-secret version/help surfaces after checking the command exists. Do not read
authentication storage or print full settings. Write only
`docs/kiro-compatibility.md` and plan/index status under an authorised execution
of this research plan. In the present audit, only the plan itself is written.

Out: source adapters, provider emulation, Kiro subscription gateway, credential
reuse, proxy interception, private endpoint reverse engineering, model picker
patches, client permission changes or claiming MCP tools replace inference.

## Steps and decision gates

### 1. Identify the exact products and versions

Read the current Kiro IDE/CLI documentation and release notes. Check
`command -v kiro-cli` before `kiro-cli --version`/`kiro-cli --help`; if absent,
record not installed rather than installing it. For IDE, use a documented
version surface if available; otherwise record version unverified. Read only
the help/schema relevant to inference configuration and profile isolation.

**Verify:** the report has separate IDE and CLI rows with dated official URLs,
version observed or literal `unverified`, and the exact non-secret check used.
Each positive capability claim has a source or local help excerpt.

### 2. Determine whether the desired integration is supported

For each client, establish: custom inference base URL/provider support, supported
wire protocol, auth mechanism, model discovery/alias constraints, tool and
streaming format, configuration ownership/restore, and an isolated test profile.
Distinguish these from custom-agent model selection and MCP tooling.

**If no official hook is established:** record `NO VERIFIED INFERENCE HOOK`,
the inspected versions/pages and the precise evidence that would reopen it.
Complete this research result; do not implement an unofficial bridge or keep
searching indefinitely. A bounded pass is enough.

**If a hook is established:** record `SUPPORTED HOOK; RUNTIME UNVERIFIED`.
Map it to Responses or Messages only if the documented contract matches. A new
wire protocol requires its own plan and fixtures, not a branch guessing at the
existing request shape.

**Verify:** each row has one outcome above, endpoint-setting evidence if
positive, a protocol classification, and an explicit unresolved list. A model
appearing in a picker cannot be used as endpoint/routing evidence.

### 3. Specify one thin slice only after a positive result

Write a separate implementation handoff for one chosen client and protocol,
following 061's domain rules, 062's protocol seam and 063's activation boundary.
The first future runtime proof is one isolated client turn with a tool call and
result, correct upstream identity, and preserved native credential separation.
List exact fixture cases for discovery, auth, JSON/SSE, tool result, cancellation
and restoration; add compaction only if the client exposes that behavior.

Any paid run must be separately approved with model/account and spend bounds.
Any real client change must name the isolated profile and rollback. If those
are not available, stop at the complete reviewable handoff rather than mutating
the user's default profile. A negative result needs no implementation handoff.

**Verify:** the report records either a linked bounded handoff or the negative
outcome; there is no claim of working Kiro inference without a real client proof.

## Report format and done criteria

Use a small Markdown table with columns: client, version, source checked, hook,
protocol, auth/config ownership, offline evidence, runtime evidence, outcome,
next gate. Do not store raw settings, token-bearing URLs or credentials.

- [ ] IDE and CLI each have a dated, evidence-backed decision.
- [ ] Custom tooling and model-service selection are distinct from inference hooks.
- [ ] No unsupported protocol/provider identity is inferred.
- [ ] Positive result has a scoped future slice; negative result states reopening evidence.
- [ ] `git diff --check` exits 0 and only report/plan files changed.
- [ ] Source, real-client, billing and publication status remain separate.

This spike adds no code tests. If committing its report, repository-required
checks still apply: `python3.14 -m unittest discover -s tests -t .`,
`python3.14 -m compileall -q codex_router tools tests packaging`,
`python3.14 tools/check_source_limits.py`, then current pre-commit-review.

## STOP conditions and maintenance

Stop the dependent action if it requires credentials, private traffic capture,
an undocumented bypass, paid inference, installation, default-profile mutation,
or an out-of-scope source change. Report the established result and exact next
gate; no repeated permission requests for already authorised read-only research.
Recheck this decision after relevant Kiro releases; version it as evidence,
not a permanent assumption about what Kiro can do.

Git: reuse one owned `codex/` worktree based on `develop`; conventional `docs:`
commit under current review policy; target `develop`, verify integration, then
clean up. This report does not itself authorise a Kiro rollout.
