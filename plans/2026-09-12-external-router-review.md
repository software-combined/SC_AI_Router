# External router review (2026-09-12) and what we adopted

Read-only review of `github.com/duolahypercho/codex-router` (MIT, public,
~3.2k stars, 30 contributors, Node 22 plus a LiteLLM sidecar, ~103k source
lines, 8 loopback ports, Electron Control Center) against this router.
Method: five read-only audits (Claude Code surface and CLI surfaces; security;
discovery and provider config; distribution, CI and design), each re-deriving
claims from that tree and from ours at `origin/develop`, plus one read-only
client spike. No code was copied and no external installer was run.

## Verdict

Keep our architecture and trust boundary. Their breadth (many clients, many
providers, a desktop app) is real, but it costs a LiteLLM/FastAPI sidecar, an
eight-port surface, an internet-facing tunnel option, a git-tracking updater and
an Electron app - a different risk class for a staff fleet. Adopt the bounded
ideas below, reimplemented, with no new runtime dependency.

## Verified safety facts about their design (credit where due)

- The ChatGPT bearer and account headers are only attached on the native path to
  `chatgpt.com`; routed calls use an internal key; client credentials are stripped
  before any third-party upstream; an unknown provider-prefixed slug fails locally
  rather than leaking to OpenAI.
- No code path converts a Claude.ai subscription login into a reusable API
  credential, and their README says so explicitly.
- Dependencies are hash-pinned (`--require-hashes`), there is no `postinstall`,
  and no analytics SDK was found.

## Their weaknesses we must not copy

Eight loopback ports with an env-overridable bind host (warn-only in their
doctor); an unauthenticated `/health` that discloses version and activity; an
optional Cloudflare tunnel for the Cursor edge; a LiteLLM sidecar with a large
transitive Python tree; a branch-tracking `git clone`/`pull` updater with no
signature on the fetch; Keychain reads that spawn a process per resolve; a
128 MiB body and 24 h execution budgets; and sensitive session headers forwarded
by allowlist rather than rebuilt per request.

## Findings that became work

| Area | Their behaviour | Our gap | Plan |
|---|---|---|---|
| Model listing | `listed:false` rows stay routable but invisible; discovery never writes; a billed probe refuses without `--live --yes` | preview rows are visible immediately; no discover report; the probe runs one leg and records a fixed string | 145 |
| Ingress hardening | token strength, concurrency cap, layered redaction, transport guards, URL/SSRF kit | eight small gaps, listed in 146 | 146 |
| Operator surface | `doctor` (FAIL/WARN rows, `Fix:`, exit 1), read-only `update check`, no-argument `rollback`, redacted `support-bundle` | `--status` alone; `--check-update` applies; rollback needs an exact version | 147 |
| Claude Code | published-catalog snapshot plus drift; effort normalisation; per-process launcher | no recorded snapshot; no drift check | 148 |
| CI and docs | per-PR tests on three OSes, shell and PowerShell parse gates, docs shipped to hosts | CI ran the suite only at tag time; installed hosts had no docs | 134 (this review's first slice landed; the rest stays open) |

## Explicit rejections

- **Homebrew tap, npm and pip distribution.** Our bootstrap plus the public feed
  is one command on three OSes; a formula would need a Python 3.14 virtualenv
  build, duplicates service ownership, and cannot cover Windows.
- **Electron Control Center, macOS tray, widget, docs site.** Months of work across
  three toolchains for a feature set the plugin plus `--status`/`--doctor` covers.
  Their "docs site" is a landing page, not a documentation browser.
- **Per-provider key CLIs, curation UI, picker toggles.** They widen CLI secret
  handling; the loopback key window and IT provisioning already cover our two
  providers, and visibility is policy-driven by design.
- **Cursor, Gemini CLI, OpenClaw and DeepSeek Harness targets.** Outside the
  two-client scope; each needs a config manager, drift checks and doctor rows.
  The inbound-adapter pattern (a thin surface module that translates and re-enters
  our own `/v1/responses`) is recorded as the shape to use if demand appears.
- **A second external provider (Nous Research / Hermes).** Their checked-in Hermes
  rows are retired upstream: on 2026-09-12 the Nous portal catalogue itself had
  zero ids containing `hermes` or `nous`, and `nousresearch/hermes-4-70b` answered HTTP 404
  "This model has been retired". OpenRouter already serves
  `nousresearch/hermes-4-405b`, so Hermes needs no second provider.
- **LiteLLM or any protocol-translation sidecar, a git-based updater, Keychain
  reads, an env-overridable bind host, anonymous/keyless provider modes, and
  per-model endpoints.** Each trades a guarantee we already hold.
- **Their Claude Code launcher.** Recorded in plan 148: a router-only alias breaks
  a plain `claude` invocation, and its `ANTHROPIC_AUTH_TOKEN` conflicts with
  subscription passthrough.
- **Deferred, not rejected:** a chunked request-body reader, a subscription-sharing
  consent marker and caller-token rotation. Reopen only on demand.

## Licensing and provenance

Their repository is MIT; ours is Apache-2.0. Nothing from it was copied. Ideas
were reimplemented from observed behaviour. Any future verbatim reuse of that
code requires an attribution entry in `THIRD_PARTY_NOTICES.md`, which plan 142
owns; prefer reimplementation so the bundle carries no third-party code.

## Spike: does Codex re-read its catalogue?

Plan 135 stage 1, run 2026-09-12 against the installed `codex-cli 0.153.4` with
an isolated `CODEX_HOME` and a temporary catalogue: `model/list` returned the
starting catalogue, a rewritten file on disk did not change the running
process's answer (same ids, with and without a delay), and a fresh process read
the rewritten file correctly. Codex therefore reads `model_catalog_json` once at
startup and needs a restart for new rows - the premise of plan 135 holds, so its
stage 2 is warranted and is sequenced after 145.

## What landed immediately

Plan 134's first slice landed (bundled docs and docs index,
`docs/troubleshooting.md`, the per-PR offline unit suite and the shell/PowerShell
parse gates); its amendment records the exact landed and still-open items.
