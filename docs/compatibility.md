# Compatibility

## TypeSafe Jev decisions probe, 2026-09-18

`typesafe/jev-1.13` answers with typed decisions rather than chat text: the
OpenAI-compatible chat endpoint refuses it with `400 ... is a decisions
model and cannot be used with the chat/completions endpoint. Use the
/api/alpha/decisions endpoint instead.`, and routing is refused outright
until the account's allowed-providers setting includes TypeSafe (`404 ...
your account's allowed-providers setting permits only: ...`, with
`typesafe` missing from that list). With the provider allowed, one
synthetic call to `/api/alpha/decisions` (475-byte body, one question, no
retries, $0.0000156) returned the verified envelope:

    {"model": "typesafe/jev-1.13-20260917",
     "answers": {"drop_p2": {"type": "noul", "noul": 0.91}},
     "usage": {"input_tokens": 372, "output_tokens": 22, "cost": 0.000015624},
     "id": "gen-dec-1789702759-I7LRUvr28GHweRLN7Ih2",
     "provider": "TypeSafe"}

A `noul` answer carries a confidence between 0 and 1, the answer map is
keyed by the caller's own question id, and `model` echoes the served
snapshot rather than the requested alias. The request shape came from
validation errors, which bill nothing: `model`, `state` (string, record or
array) and `questions`, each question a `noul`, `choice` (record-valued
criteria) or `score` (array-valued criteria) carrying `instructions`. The
key-filtered `/api/v1/models/user` list still omits the row while routing
succeeds, so that list is not the availability gate for this endpoint.

## Oversized routed threads, 2026-09-17

Thread `01a0ab7c` (`meta/muse-spark-1.3-contributor`) died with the router's
`BODY_TOO_LARGE`: 2,690 released-tool search results from 9 distinct queries
carried 63.7 MB of repeated schemas inside a 67.3 MB decoded body - past the
64 MiB decode ceiling that exists so prepare can slim exactly that shape. The
handoff bundle records 12,197 session lines, one failed turn after 5.25 h, and
the work intact in its worktree.

The fix is verified offline, with no paid calls: `codex-cli 0.153.1` against
the in-process router and a fake upstream passes every scenario of
`tools/probe_context_budget.py` in both compaction modes, including the added
`carried_usage` leg - the provider reports 1,000 input tokens and the client
still compacts, because the router reported the weight of the history the
thread carries.

## Subscription picker gate withdrawn, 2026-09-17

Plan 178 shipped in 0.6.83 and was withdrawn in 0.6.89 after the live
trial it had been waiting for. On the owner's machine, with the ChatGPT
allowance exhausted, the gate fired exactly as designed: at 22:03:43 the
router read an `x-codex-primary/secondary-used-percent` header at 100%, logged
`subscription_gate_changed` with `source: headers` and `blocked: true`,
and rewrote `mixed-models.json`; the helper turn was then answered by
`openai/gpt-5.6-luna` and billed to OpenRouter.

That is what killed the design. The twin swap put an OpenRouter-billed row
in the subscription row's place, under the same model name, so the picker
kept offering "Luna" while the subscription could not run - and the client,
which reads its catalogue only at startup, showed the pre-swap list either
way until it was reopened. The picker now lists every subscription row and
its twin beside it, labelled `· OpenRouter`, and an exhausted row answers
the refusal message instead of moving. Evidence, state file and four-hourly
probe are all gone; the helper-turn fallback and the install-time
no-subscription default stay.

## Model-switch history boundary, 2026-09-13

The client's `<model_switch>` developer message (`core/src/session/mod.rs:4289`
at Codex `rust-v0.154.0-alpha.6.2`, recorded into history and replayed every
later turn; local rollouts show it mid-thread at 20 of 53 and 19 of 58 items)
is now a boundary, not a flag: items before the last marker get the portable
treatment, items after it replay natively, so the current model's own
reasoning survives. The `meta/muse-spark-1.3-contributor` row keeps
whole-history rewriting until plan 175 probes it with its own reasoning
replayed.

## OpenRouter refusals that arrive after the stream opens, 2026-09-13

Installed Codex CLI `0.154.0-alpha.6.2` against router 0.6.47. A thread on
`deepseek/deepseek-v4.1-flash` produced two different refusals, both as a
terminal `response.failed` after HTTP 200 and part of the stream.

1. `incomplete parallel tool-call group: tool call 'call_00_FQ1Z...' has no
   tool response` at `08:42:57Z` and `08:44:29Z`. The cause was local and is
   fixed. The thread switched models at `08:08:34Z`, and the client's
   `<model_switch>` developer message stays in the thread's history, so the
   portable history pass kept running on every later turn. It replaced the
   matched tool-search pair with a user note at the search call's position,
   which sat between a parallel group's calls and their outputs, so the
   converted chat history carried calls with no results. The note now waits
   for the tool run to close, and reasoning notes wait with it.
2. `204 request validation errors: Extra inputs are not permitted` naming
   `messages[12].tool_calls[0].tool_kind`, `responses_item_id` and
   `responses_item_status` at `08:11:50Z`. Those three field names appear
   nowhere in the Codex app bundle, the `codex` binary, `ai_router/`, or any
   release, so OpenRouter's own Responses-to-chat conversion annotates the tool
   calls it synthesizes and a strict serving backend refuses the extra keys.
   The repair belongs upstream with OpenRouter; the router now answers that
   terminal event with `UPSTREAM_INVALID_PROMPT` and one actionable sentence,
   and keeps OpenRouter's code in the service log.

No paid probe reproduced either refusal; the DeepSeek serving provider was
not identified.

The same thread then switched to `meta/muse-spark-1.3-contributor` at
`08:46:17Z` and Meta refused the same converted body synchronously: six
identical turns at `08:46:23Z`--`08:46:53Z` returned upstream HTTP 502 with no
code-shaped field, which the router answered as 409 `PROVIDER_REJECTED` with
the switch-back recovery sentence (269 prepared items: 59 messages, 68
`custom_tool_call`, 105 `function_call_output`, 37 `function_call`, 55 tool
definitions, ~456KB). Contributor itself was healthy: an identical-shape turn
completed 200 at `08:40:05Z` and standard Muse 1.3 served 200s throughout, so
the refusal names the carried history, not the model. The tool-run fix above
removes the poison: replaying the thread's exact history through the fixed
pass keeps the parallel group contiguous (calls at 184--185, outputs at
186--187) and defers the search note to position 190, after the run closes.

## Streamed context refusals, 2026-09-13

Candidate 0.6.42, macOS Codex CLI `0.154.0-alpha.6.2`:
`python3.14 tools/probe_context_budget.py` passed all four offline scenarios.
Synthetic upstream replies exercise threshold compaction, HTTP context errors,
HTTP 200 SSE numeric context refusals, and SSE metadata context codes. The two
new stream scenarios produce `contextWindowExceeded`, then explicit compaction
and continuation preserve the marker with one compaction and three inference
requests per scenario. No paid inference or installed-router mutation occurred.

The incident's Linux CLI `0.153.4` was source-inspected at `rust-v0.153.4`
(`3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`):
`codex-rs/codex-api/src/sse/responses.rs` recognizes the canonical error code;
`codex-rs/core/src/session/turn.rs` marks context full and returns an error.
This is not a Linux runtime replay or proof of automatic same-turn recovery.
The original provider accounting discrepancy remains unverified.

## Sonnet parent switches and retained subagents, 2026-09-12

Candidate 0.6.37, installed Codex CLI 0.153.4, same pinned source and desktop
version as the Lite entry below. Sonnet means OpenRouter
`anthropic/claude-sonnet-5` in Codex; this does not verify Claude Code.

The owner requested parent-model changes midway through the same task with
subagent tools on both sides. Disposable client homes and an isolated candidate
router were used; existing user tasks and the installed router were untouched.
Each sequence kept one DeepSeek V4.1 Flash child alive through all three parent
turns. The first parent spawned it, the second followed up with that same child,
and the final Sonnet parent sent a queued message then woke the child again.
The child and parent both returned all expected synthetic markers.

| Parent sequence | Calls (cap 24 per sequence) | Result |
|---|---:|---|
| Sonnet 5 -> DeepSeek V4.1 Flash -> Sonnet 5 | 13 | PASS |
| Sonnet 5 -> GPT-6 Astra -> Sonnet 5 | 16 | PASS |

All 29 candidate requests returned HTTP 200 and observed serving identities
matched requested models. The three handoff actions executed as native client
tools with explicit plaintext metadata. Astra used its actual Lite catalogue
row. There was no compaction, recreated child or final-step reminder in either
passing sequence; marker checks were scoped to parent/child and turn IDs.

Earlier expanded runs exposed Sonnet's rejection of a terminal assistant
prefill and the external handoff metadata gap. Readable peer messages now use
the existing matched-tool-result projection. An interim response-only steering
attempt completed Codex turns without executing a tool, confirmed in the pinned
client source; it was replaced before approval by executable plaintext calls.
Explicit opaque metadata remains rejected and subscription encryption is intact.

Final offline suite: 1,255 tests passed. Compile, lint, source limits, policy,
classic/Lite handoff probes and history-switch/400/transient-retry probes passed.
The isolated router and disposable clients were stopped after acceptance.

## Responses Lite agent handoffs, 2026-09-12

Candidate 0.6.37 on `cyril/cross-provider-history-fix`, base `ed55ced`
(after the unrelated loopback Host-header fix).
Clients: ChatGPT.app 26.903.71938 (8576), bundled Codex CLI 0.153.4.
Pinned source: `rust-v0.153.4`, `3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`.

- The running 0.6.36.53 router contains the earlier alias/steering fixes,
  but they inspect only top-level `tools`. The actual Astra row enables
  `use_responses_lite`, which inserts developer `additional_tools` items
  in `input` instead (`core/src/client.rs:929-977`). With no discovered
  aliases, the subscription response adapter also skips steering.
- Both failed DeepSeek review spawns carried an opaque message and omitted
  `encrypted_function_args`; the native executor requires an explicit
  empty list to select plaintext delivery (`core/src/tools/router.rs:44-62`).
  The external guard rejected the unreadable assignment before dispatch.
- A synthetic loopback capture with the installed binary and actual Astra
  row found zero top-level tools, one `additional_tools` item containing
  all six native collaboration functions, and zero aliases before the fix.
- The candidate discovers the existing namespace in either location,
  adds aliases in that same container, and derives a stable new `at_` ID
  for the changed Lite prefix. Original tool schemas, native encryption,
  client history and downstream opaque-input containment remain intact.
- Corrected offline installed-client probes passed for both `--wire-mode
  lite` and `--wire-mode classic`: all three assignment markers delivered,
  canonical native-name replay true, aliases emitted, encrypted native
  control preserved, and no probe errors. Neither run called a model.
- Earlier Plan 066 Astra live evidence used a parent copied from the external
  template with Lite disabled; it proves classic Responses only. The live
  probe now requires the installed native row and reports its wire mode.
- Bounded live candidate lifecycle passed with the actual Astra Lite row
  and DeepSeek/max child: 20 model calls under a cap of 24, all three
  plaintext markers received and returned, native encrypted Sol control
  returned, canonical replay true, router restart/resume true, compaction
  and two recall turns true, no probe errors. The recorded initial
  WebSocket 404 fallback was expected; subsequent HTTP delivery completed.

See `plans/2026-09-12-responses-lite-agent-handoffs.md` for the failure chain
and implementation scope. This source change does not deploy the router.

## Subscription history replay and validation retries, 2026-09-12

Candidate source: 0.6.37, initially based on `develop` at `4b9cdf4`,
refreshed to `c177f17`, then `ed55ced` before review. Clients:
ChatGPT.app 26.903.71938 (8576), bundled Codex CLI 0.153.4;
Claude Code 2.1.223 (version readback only, no Claude acceptance in this
Codex-only change). Upstream Codex source: `rust-v0.153.4`, commit
`3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`.

- A task switched from DeepSeek to Astra with 19 plaintext reasoning
  records and no compaction. OpenAI rejected `input[0].content` with
  `array_above_max_length`: maximum 0, received 1. A synthetic control
  without the reasoning item returned 200. Removing only its content
  caused an unknown-item 404, so the complete foreign item must be omitted.
  The working Beacon task had compacted immediately before its switch,
  leaving no foreign reasoning records to replay.
- The outgoing subscription projection omits plaintext-only reasoning,
  preserves native encrypted reasoning without plaintext content, and
  leaves client history, messages, and tool pairs intact. It applies to
  Responses turns and compaction; existing external portability policy
  is unchanged.
- The pinned client's `api_bridge.rs` maps HTTP 400 to non-retryable
  `InvalidRequest`; `protocol/src/error.rs` maps that to protocol `other`.
  HTTP 409 instead becomes retryable `UnexpectedStatus`. Validation
  refusals now retain 400, including cached refusals. Existing context
  error handling is preserved.
- `python3.14 tools/probe_history_switch.py` passed with the installed
  client and fake upstream: DeepSeek -> Astra -> DeepSeek, no compaction,
  preserved marker; permanent rejection exactly one attempt; transient
  rejection then success exactly two attempts. The fake upstream sees no
  foreign reasoning on the Astra leg, while the adapter's incoming history
  still contains it.
- `python3.14 tools/probe_context_budget.py` passed both threshold
  compaction and explicit context-error recovery, preserving the marker.
  Its fake connection gained the no-op `connect()` required by the current
  transport contract.
- Owner-authorized live candidate acceptance passed using
  `tools/probe_codex_runtime.py` with DeepSeek at max, `--switch --switch-to
  gpt-6-astra --switch-back`: a real reasoning item and dynamic-tool round
  trip preceded the switches, and both retained the tool result. A separate
  Astra dynamic-tool round trip passed. All candidate requests reported
  HTTP 200; DeepSeek served identity matched. The candidate used a separate
  loopback port and disposable client home and was stopped afterward.

No deployed router or existing task was changed. The source-size baseline
keeps the existing adapter/failure-policy owners (296/281 lines), both below
the 400-line hard cap; history normalization lives in its own small leaf.

## Subagent model list is capped by the client, 2026-09-12

Clients: bundled app-server codex-cli `0.153.4` (upstream tag
`rust-v0.153.4`); the same cap is present at `rust-v0.155.0-alpha.3.10`.
Router source base `48d5bae` (0.6.35), plan 151 on
`codex/subagent-model-visibility-20260912`, target `develop`; the
instruction fix ships in the `0.6.36` beta.

- `spawn_agent`'s "Available model overrides" text is built from the first
  five picker-visible models that support the active multi-agent backend,
  in catalogue order (`MAX_SPAWN_AGENT_MODEL_OVERRIDES = 5`,
  `codex-rs/core/src/tools/handlers/multi_agents_common.rs:33` and
  `multi_agents_spec.rs:763-772` in `rust-v0.153.4`).
- The router catalogue lists the subscription roster first, so those five
  rows are all OpenAI models and every router model is invisible in that
  list. The picker is unaffected: the same client's `model/list` returns
  all 26 visible rows of the 27-row catalogue.
- Validation is not capped: `find_spawn_agent_model_name` searches the full
  model list, so an explicitly passed router id reaches routing; a portco
  policy can still reject it and the 0.6.36 instructions require reporting
  that rejection. The 0.6.36 instructions tell routed sessions the roster
  and that rule; the starter profiles carry it for subscription-model
  sessions. The upstream cap is unchanged, so a future client can still
  hide the list; plan 151 stage 5 tracks the upstream report.
- Observed failure 2026-09-12 (task 01a09477): asked for Muse Contributor
  subagents, the agent spawned `gpt-6-astra` twice, `gpt-5.6-sol`,
  `gpt-5.6-terra` and `gpt-5.6-luna`; five of that day's 156
  `upstream_rate_limited` events (all `provider: openai`) are those
  children.

## Standalone delegation delivery, 2026-09-11

Clients: ChatGPT.app `26.903.71938`, Codex Framework `152.0.7977.83`,
bundled app-server codex-cli `0.153.4` (upstream tag `rust-v0.153.4`,
commit `3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`), feature gate
`turnToolOutput: 0.151.0-alpha.4` read from the app bundle. Router source
base `d440c3a` (0.6.24); fix commit `a300989` on
`codex/router-handoff-outputs-20260911`, prepared for the `0.6.26` beta
release, target `develop`. The `0.6.25` beta was tagged from `develop`
before this fix and its release run failed on the feed publisher role, so
this fix rides the next beta instead. `v0.6.26-beta` shipped the first
iteration (assistant-role plaintext, commit `a300989`); the tool-pair
shape below ships in the `0.6.27` beta from the
`codex/router-handoff-tool-pair-20260911` follow-up, so an installed
0.6.26 host does not yet carry the working shape.

- Codex Desktop injects cross-task messages (`create_thread`,
  `send_message_to_thread`) as a standalone `function_call_output` item
  with no `call_id`; upstream treats it as a legitimate instruction turn,
  but the router's scrub dropped it as an orphan, so tasks on OpenRouter
  models never received the delegated message while tasks on OpenAI
  models did.
- Live probes against OpenRouter (`deepseek/deepseek-v4.1-flash`): the raw
  standalone item returns HTTP 400 `invalid_prompt`; user-role text is
  rejected by policy as authority elevation. Assistant-role plaintext was
  first shipped (fix commit `a300989`) and returned 200, but live
  acceptance on a fresh task rejected it: the child replied exactly
  `NO-ASSIGNMENT`, and a router-level probe returned no output items at
  all, while a matched `function_call` + `function_call_output` pair made
  the model reason about the delegated assignment and emit the requested
  token. The shipped shape is therefore the tool-result pair: one
  synthesized complete `function_call` (deterministic `call_id`, no
  `namespace`) immediately followed by the `function_call_output`
  carrying the delegation text verbatim. A synthetic pair 400s when
  `namespace` is present on both members, so neither member sets it.
- Blast radius, read from the app's thread store: 164 delegated items
  across 24 tasks, 15 on OpenRouter models and 9 on OpenAI models; all 8
  OneDrive forensic tasks created 2026-09-11 12:10-12:11 were
  `deepseek/deepseek-v4.1-flash` and received nothing.
- Offline gates on the fix branch: full suite exit 0, compile exit 0,
  source limits `failures=0`, `tools/probe_standalone_outputs.py` prints
  `PASS`. Paid live acceptance was completed on 2026-09-11 with router
  `0.6.27.44`: a fresh projectless task on `deepseek/deepseek-v4.1-flash`
  received its `create_thread` delegation and replied exactly
  `ROUTER-HANDOFF-OK-7f3a`, where the assistant-role iteration had replied
  `NO-ASSIGNMENT`.

## Windows lifecycle acceptance, 2026-09-10 (Plan 116 first proof)

Machine: Windows 11 Pro 10.0.26200 x64 staff laptop (AzureAD account, no
elevation), Python 3.14.7 from python.org, Codex desktop `OpenAI.Codex`
26.903.8094.0 (Store package; the `codex` CLI is not on PATH), GitHub CLI
2.97.0. Bundles were built from the 0.6.12 source and served from local
`file://` feeds; no paid model request was made and no Codex session was
exercised, so this is lifecycle evidence only, not model or client
acceptance.

| step | result |
|---|---|
| `--preflight`, `--status`, `--dry-run` | read-only, no router home created |
| first install | stops at the key gate (exit 3); key and state files `icacls` owner-only, home grant inheritable, inherited `CodexSandboxUsers` read access removed |
| install with key present | `/health` reports the installed version in about four seconds; both tasks registered as Interactive-only, least privilege, `pythonw.exe`; Codex `config.toml` parses with a forward-slash catalogue path |
| scheduled update | `CodexMixedModelRouterUpdate` run by hand installed the next bundle; health moved versions with about fourteen seconds of refused connections; updater output captured in `logs\update.log` |
| rollback (`--version`) | previous release serving again in about two seconds |
| uninstall | both tasks ended and deleted, no router process, port free, config block removed, activation receipt dropped, home left in place |
| reinstall after uninstall | exit 0, Codex re-attached (fails with a stale receipt before this release) |
| sign-out and sign-in | pending: the machine must be signed out after this session ends; verify with `schtasks /query /tn CodexMixedModelRouter` and `/health` |

## Desktop client restart targets, 2026-09-11

Researched before wiring the update notice's "Quit and reopen" action, so
the restart targets the installed client rather than a guessed process
name. Sources are the evidence named in the table below; re-check them
before relying on the identities.

| platform | client identity | evidence |
|---|---|---|
| macOS | bundle `com.openai.codex` (ChatGPT.app hosts Codex) | installed desktop app, `mdls`/`osascript` on this machine |
| Windows | MSIX package `OpenAI.Codex` | Plan 116 acceptance machine reported this package identity (`docs/compatibility.md`, 2026-09-10) |
| Linux | preview app installed as package `chatgpt`, launched by running `chatgpt` | <https://learn.chatgpt.com/docs/linux/linux-app> (Ubuntu 24.04/26.04, Debian 13, Fedora 43/44; x64 and ARM64; graphical sessions only) |

The Codex CLI advertises the desktop app per platform in the same terms:
`codex-rs/tui/src/tooltips.rs` at `aff3e0db`, `LINUX_APP_TOOLTIP` ("install
it from .../linux/linux-app and run 'chatgpt'") gated on a graphical,
non-WSL session, and `MACOS_APP_TOOLTIP` for `codex app`. Windows Store
apps launch through their package identity, so the restart path resolves
the AUMID with `Get-AppxPackage`/`Get-AppxPackageManifest` and falls back
to `Get-StartApps`, the documented AUMID lookup
(<https://learn.microsoft.com/en-us/windows/configuration/store/find-aumid>).

The notice itself is best-effort: if a platform's dialog tool or client is
missing, the dialog still appears and the installer continues.

## Token-budget protocol check, 2026-09-09

`python3.14 tools/probe_context_budget.py` passed against Codex CLI 0.153.4
bundled with desktop 26.901.51231. It uses an isolated temporary Codex home,
the real router, synthetic usage, and a fake upstream; no model is called.
The unchanged 90% threshold triggers native compaction, and the following
request retains a marker from the earlier assistant response. A recognized
upstream context error becomes Codex's `contextWindowExceeded`; explicit
compaction and continuation preserve the marker afterward. Automatic
next-turn recovery after an error is not guaranteed by this check.
This is protocol evidence, not paid model or Claude compatibility acceptance.

Paid Codex tool round trips also passed on 2026-09-09 against the 0.6.10
candidate source on a separate loopback listener: `meta/muse-spark-1.3-contributor`
through OpenRouter and `gpt-5.6-luna` through the subscription route. The
OpenRouter response reported the requested Muse model. These probes do not
prove recovery of the original long task or installation of the candidate.
Claude Code 2.1.223 reported signed out, so its live compatibility probes
remain unverified.

## Paid probe, 0.6.20 candidate, 2026-09-11

Clients: Codex desktop 26.903.61454 (bundled CLI 0.153.4), Claude Code
2.1.223, OpenCode 1.18.25. Run against the fix branch source on two
separate loopback listeners while the installed router stayed on
0.6.19.34.

| leg | result |
|---|---|
| `meta/muse-spark-1.3-contributor` via OpenRouter | passed; `served_model` echoed the requested model, items `userMessage`, `reasoning`, `agentMessage`, `dynamicToolCall` |
| `gpt-5.6-luna` via the subscription route | blocked: `openai-subscription` answered 503 `upstream_rate_limited` on every attempt. The ChatGPT subscription has no remaining allowance, so this leg is an environment limit, not a router defect |
| Claude Code, OpenRouter and subscription | not run: Claude Code is not usable on this machine yet |

Upstream source review at these versions pins the contract this release
targets. Codex derives the compaction threshold as 90% of the context
window (`rust-v0.153.4`, `codex-rs/protocol/src/openai_models.rs`), counts
provider-reported usage rather than payload bytes, and maps a
`context_length_exceeded` stream failure to `contextWindowExceeded`. Its
own history estimator already discounts base64 image payloads — including
images inside `function_call_output` — to a flat ~1,844 tokens per
non-original-detail image (`codex-rs/core/src/context_manager/history.rs`).
From 0.6.86 the router reports that threshold's input in the terms the
client compacts on: a routed Codex turn carrying tools has its
`response.completed` usage raised, never lowered, to the weight of the history the thread actually
carries (`bytes / 5.8` for text plus the flat image allowance, clamped to the
row's window). Without that the slim the router performs is invisible
upstream, so a byte-heavy thread never crossed 90% of the window - the
2026-09-16 thread carried 67 MB while upstream was billed about 1 MB.
Subscription passthrough, tool-free responses (which keep their verbatim
forwarding contract) and the Claude Code Messages path keep the provider's
own usage.
OpenCode v1.18.25 treats the same code as recoverable: `SessionProcessor.halt`
sets `needsCompaction` and the run loop compacts
(`packages/opencode/src/session/processor.ts`). OpenCode is a credential
source for this router, not a routed client, so it is unaffected by the
pre-flight refusal.
Pending: an OpenAI-billed model on a subscription with remaining allowance,
and both Claude Code legs, once that client is usable again.

Tested Codex desktop versions:

| version | date | result |
|---|---|---|
| 0.153.4 | 2026-09-07 | probe baseline |
| 0.153.4 | 2026-09-08 | no-subscription spike: custom provider (`scg_router`, no login) runs `thread/start` + `turn/start` to `/responses` with bearer auth; `model/list` unanswered in all login shapes; see Plan 111 Step 1 report |
| 0.153.4 (desktop 26.901.51231, Arch `codex-desktop-git`) | 2026-09-08 | contributor reported chat creation working after the catalogue schema fix. Review reproduced unhandled old stubs and invalid Linux service instructions. Version 0.6.7 repairs existing rows and adds the Linux installer backend; staff-machine acceptance of the new lifecycle remains pending |

The contributor's follow-up machine report on 2026-09-09 explains the Linux
startup result: the running 0.6.2.0 bundle uses a `current` symlink and
`python3.14 -m ai_router`. It does not use the current branch's pointer
file and `router_launch.py`. The timer fires, but every reported update
failed on an unsigned local feed; no successful automatic update or
rollback was demonstrated. Version 0.6.7 addresses both the layout migration
and the missing systemd installer backend. Its regression harness runs real
bundled router processes through migration, an unsigned scheduled update,
rollback and uninstall, with only systemctl calls simulated. The contributor
must still verify the real user manager and client sessions using
[the Linux upgrade checklist](linux-upgrade.md).

Per-model quirks, generated from the registry:

| model | modalities | schema | max tools | excluded efforts | tier |
|---|---|---|---|---|---|
| anthropic/claude-fable-5.1 | text,image | native | None | - | verified |
| anthropic/claude-haiku-4.5 | text,image | native | None | - | verified |
| anthropic/claude-opus-5 | text,image | native | None | - | verified |
| anthropic/claude-sonnet-5 | text,image | native | None | - | verified |
| deepseek/deepseek-v4-pro-0813 | text | native | None | - | verified |
| deepseek/deepseek-v4.1-flash | text,image | native | None | - | verified |
| google/gemini-3.1-pro-preview | text,image,audio | native | None | - | verified |
| google/gemini-3.8-flash | text,image,audio | native | None | - | verified |
| meta/muse-spark-1.3-contributor | text,image,audio | json_text | None | max | verified |
| meta/muse-spark-1.3 | text,image,audio | json_text | None | - | verified |
| moonshotai/kimi-k3 | text,image | native | None | - | verified |
| openai/gpt-5.6-luna | text,image | native | None | - | verified |
| openai/gpt-5.6-sol | text,image | native | None | - | verified |
| openai/gpt-5.6-terra | text,image | native | None | - | verified |
| openai/gpt-6-astra | text,image | native | None | - | verified |
| qwen/qwen3.8-max-0902 | text,image | native | None | - | verified |
| x-ai/grok-4.6 | text,image | json_text_root | 350 | - | verified |
| z-ai/glm-5.3-flash | text,image | native | 128 | - | verified |
| z-ai/glm-5.3 | text | native | 128 | - | verified |

Both GLM rows (`z-ai/glm-5.3`, `z-ai/glm-5.3-flash`) carry
`max_tools: 128`, the Z.ai documented ceiling (router 0.6.57); sessions with
more declared tools degrade the way the Grok row does instead of failing
upstream.

Text-only rows (`deepseek/deepseek-v4-pro-0813`, `z-ai/glm-5.3`) and the
`drop_images` row (`x-ai/grok-4.6`) replace images on the wire with
`ERROR: Cannot read image (this model does not support image input). Inform the user.`
instead of refusing the thread (router 0.6.67). The model is expected to
say that in the conversation; the turn continues.

## Probe runs 2026-09-08

Base tool round trip (`probe_codex_runtime.py <slug> --router-state <state> --effort low`)
against the installed router, Codex desktop 0.153.4. All six passed with
`userMessage`, tool call, `agentMessage` (reasoning items where supported):

| model | result |
|---|---|
| z-ai/glm-5.3-flash | passed |
| z-ai/glm-5.3 | passed |
| moonshotai/kimi-k3 | passed |
| meta/muse-spark-1.3 | passed |
| meta/muse-spark-1.3-contributor | passed |
| ~x-ai/grok-latest | passed |

Capability probes (`--image` leg, Codex desktop 0.153.4, 2026-09-09,
paid runs against the live router):

| model | image result |
|---|---|
| z-ai/glm-5.3-flash | passed (named red) |
| meta/muse-spark-1.3 | failed (answered `unknown`) |
| moonshotai/kimi-k3 | failed (answered `Black`) |
| ~x-ai/grok-latest | text-only with note (ships in 0.6.7; 0.6.7.19 install still stalls upstream) |

Audio leg: `meta/muse-spark-1.3` rejected upstream (`invalid_prompt`).
Reasoning-summary, apply-patch, web-search, and experimental-tools legs are
built in the probe with offline harness coverage (pass/fail per leg, plus
contract assertions on the `-c` flags and temp catalogues); paid per-model
probes against the live router are still pending. Probe item shape fixed
this round: Codex 0.153.4 wants `{"type": "image", "url": ...}`, not
`image_url`.

Other preview models (base round trip only):

| model | tier | date | evidence |
|---|---|---|---|
| anthropic/claude-opus-5 | preview | 2026-09-07 | base round trip |
| anthropic/claude-fable-5.1 | preview | 2026-09-07 | base round trip |

## DeepSeek two-row cut, 2026-09-10

Isolated-router base round trip (`ai_router.candidate.verify`, Codex CLI
0.153.1), OpenRouter key via OpenCode auth. Both passed:

| model | tier | date | evidence |
|---|---|---|---|
| deepseek/deepseek-v4.1-flash | verified | 2026-09-10 | isolated base round trip PASS |
| deepseek/deepseek-v4-pro-0813 | verified | 2026-09-10 | isolated base round trip PASS |

Reasoning-replay follow-up, 2026-09-11 (Codex CLI 0.153.4; router
0.6.21.36-beta): the base round trips above never replayed a stored
`reasoning` item, so they missed the `encrypted_content: null` replay bug that
rejected DeepSeek thinking turns on 2026-09-11. With the 0.6.21 fix installed,
the Codex runtime probe's replaying switch leg (`tools/probe_codex_runtime.py
deepseek/deepseek-v4.1-flash --router-state <home>/mixed-router-state.json
--effort max --switch --switch-to deepseek/deepseek-v4.1-flash`) passed:
turn one produced a `reasoning` item and the
`desktop_runtime_tool_round_trip: passed` marker, and the switch turn replayed
that history and reported `history_preserved: true`.
Router log: `request_completed` 200s for the alias with `served_model` set
and no provider rejection.

## Claude desktop gateway discovery (Plan 120), 2026-09-10

Client: Claude.app `1.49585.0`, signed in; no `managed-settings.json` at
the user or system location. Router `GET /v1/models` = 20 rows.

- Before (in-dialog "Test model discovery" against the real router):
  **found 6 models**; the picker showed those 6, all `· OpenRouter`.
- After (worktree source on a temporary `127.0.0.1:18999` listener,
  fetched as `/v1/models?limit=1000`, kept by the client's own rule):
  **20 served, 20 kept**. Listener stopped, port closed.
- Root cause, read from the installed `app.asar` (evidence only, never
  patched): a row is kept only when its id passes the Anthropic-name
  check or declares a valid `anthropic_family_tier`
  (`sonnet`, `opus`, `haiku`, `fable`, `mythos`); `isFamilyDefault`
  breaks tier ties. Effort options come from a per-native-model table,
  so gateway rows show no effort picker on this version; `thinking`
  still travels byte-identical.
- Pending: fresh-session picker count of 20 and detach/reattach
  readback through `install.py --desktop`. Both wait on release plus
  deploy of this source to the live router and an app relaunch, then
  this entry gets the observed picker count.

## Context recovery and desktop upgrade, 2026-09-13

Desktop `26.908.40834` (build 8881), bundled Codex
`0.154.0-alpha.6.2`; matched source tag `rust-v0.154.0-alpha.6.2`,
annotated tag object `a1bc283c327568149d7a29d5fbd304cc471a981a`, commit
`b5bffd3ec4db487e7e3dec59663875b0ef7b72ca`. Claude Code `2.1.223`.

- `tools/probe_context_recovery.py` passed scripted native and external legs
  against the new installed binary. The real `new_context` tool removed the
  synthetic assignment; the next request carried the recovery note, and the
  exact previous-window history was retrieved before completing the same turn.
- Live recovery passed for `gpt-5.6-luna` on the subscription route and
  `deepseek/deepseek-v4.1-flash` on OpenRouter: one history retrieval and two
  live calls each, capped at four. Those legs used the candidate router and
  a local synthetic history tool, not another user's task history.
- `tools/probe_context_budget.py` passed both threshold compaction and
  explicit recovery after a context error, with the marker preserved.
- `tools/probe_codex_runtime.py` passed a real dynamic-tool round trip on
  both models through the installed `0.6.38.55` router after the client upgrade.
- Real Claude Code sessions through the installed router returned the exact
  synthetic marker on the subscription and OpenRouter paths. Requested
  native alias `haiku` was reported by the CLI as `claude-opus-4-6`;
  external usage reported `deepseek/deepseek-v4.1-flash`. No exact Haiku
  identity claim is made. Tools, hooks and persistence were disabled for
  these bounded routing checks; neither checks Claude desktop or MCP tools.

See [the root cause, plan and acceptance limits](context-recovery.md).
Recovery remains model-executed; the router does not change Codex's persisted
history or claim it can reconstruct history that is no longer accessible.

## Compaction stream recovery, 2026-09-13

Candidate source `0.6.43` passed the offline `tools/probe_context_budget.py`
against bundled Codex `0.154.0-alpha.6.2` and a fake loopback upstream: V1 and
V2 threshold and explicit context-error recovery, plus V2 truncated-summary
recovery. Each leg observed one compaction on the expected route with the
expected stream/trigger flags and preserved the marker; truncation used two
bounded summary attempts. This is source and offline evidence, not an
installed candidate compaction result.

The unchanged compatibility baseline remained on installed beta `0.6.40.56`:
Codex DeepSeek Flash and `gpt-5.6-luna`, plus Claude Code GLM 5.3 Flash and
Haiku legs, all passed their bounded routing round trips. Those legs do not
exercise candidate compaction.

After reconciling PR #107 (`c068368e...`), all nine combined probe legs passed:
both V1/V2 also recognize streamed numeric and metadata context refusals,
compact explicitly and resume. V2 truncation still uses two summary attempts.

## Pinned Claude rows, 2026-09-11

`models add <slug> --probe`, base tool round trip through the isolated
router (Codex CLI 0.153.1, OpenRouter key via OpenCode auth):

| model | tier | date | probes |
|---|---|---|---|
| anthropic/claude-fable-5.1 | verified | 2026-09-11 | base round trip |
| anthropic/claude-opus-5 | verified | 2026-09-11 | base round trip |
| anthropic/claude-haiku-4.5 | verified | 2026-09-11 | base round trip at `--effort none`; the harness default `low` is refused by the router's effort gate because `none` is the only supported effort |

The Haiku row was probed by hand with `--effort none` because
`models add --probe` carries no effort flag. Sonnet 5, both Gemini rows and
Grok 4.6 keep the `verified` tier their retired alias rows earned, since
each alias resolved to the pinned id at the rename (Grok's 2026-09-08 base
round trip is recorded above); no separate pinned-id probe is recorded for
the other three.

## Serving-endpoint attribution, 2026-09-14

OpenRouter reorders providers on every tool-calling request by default
(Auto Exacto) and may deprioritise a previously chosen provider mid-session.
Sending `X-OpenRouter-Metadata: enabled` (router 0.6.53) makes the response
and every error envelope carry an `openrouter_metadata` object naming the
selected endpoint (`endpoints.available[]` with a `selected` flag) and the
attempts (`attempts[]` with `provider`/`model`/`status`); the router logs the
serving endpoint as bounded `serving_endpoint` on `upstream_rejected`,
`upstream_unavailable`, `request_completed` and `request_failed`. Key names
pinned from the router-metadata guide and the OpenAPI `OpenRouterMetadata`,
`EndpointInfo` and `RouterAttempt` schemas, read 2026-09-14; the guide's
`selected.endpoint` path does not exist in the observed shapes, so the
extractor reads only the `available[]`/`attempts[]`/`provider_name` order.

## Probe matrix 2026-09-14 (plan 175, router 0.6.58-beta, legs A-H)

Legenda: A base round trip, B parallel pair, C same-slug switch replay,
D switch-in plus switch-back, E image, F plaintext handoff as child of a
DeepSeek parent (classic), G compact, H `require_parameters` pin. Effort
`low` unless noted. `serving_endpoint` is the bounded log field; `none`
means OpenRouter answered without endpoint metadata (edge validation).

| model | leg | effort | result | serving_endpoint |
|---|---|---|---|---|
| z-ai/glm-5.3-flash | A | low | passed | Cloudflare |
| z-ai/glm-5.3-flash | B | low | failed: calls serialized, leg asserts | Cloudflare |
| z-ai/glm-5.3-flash | C | low | passed, history preserved | Cloudflare |
| z-ai/glm-5.3-flash | D | low | passed both directions, history preserved | Together (DeepSeek), Cloudflare then Venice (GLM) |
| z-ai/glm-5.3-flash | E | low | failed: upstream `invalid_prompt`, no endpoint attributed | none |
| z-ai/glm-5.3-flash | F | max | partial: 1 of 3 markers replied, 404/409/other tool failures | unattributed (ephemeral handoff log) |
| z-ai/glm-5.3-flash | G | low | not run (row over call cap) | - |
| z-ai/glm-5.3-flash | H | low | not run (row over call cap) | - |

Row spend: ~40 calls against a 23-call cap (overrun on the misconfigured
subscription-parent F run and the 12-call DeepSeek-parent F run); the row
stops here per the plan. Notable: GLM Flash answered from Cloudflare and
Venice across turns (Auto Exacto rotation live); the parallel pair
serialized on Cloudflare; the image leg died upstream with `invalid_prompt`
before any endpoint was named.

| deepseek/deepseek-v4.1-flash | A | low | passed | Together |
| deepseek/deepseek-v4.1-flash | B | low | failed: calls serialized, leg asserts | Parasail then Together |
| deepseek/deepseek-v4.1-flash | C+D | low | passed, own reasoning replayed, history preserved | Together, Parasail, Modal |
| deepseek/deepseek-v4.1-flash | E | low | passed, red seen | Together |
| deepseek/deepseek-v4.1-flash | G | low | passed | Parasail then Fireworks |
| deepseek/deepseek-v4.1-flash | H | low | failed: upstream 404 with `require_parameters: true`, no endpoint attributed | none |
| deepseek/deepseek-v4.1-flash | F | max | not run (session cap: 2 rows fully covered plus row-1 F) | - |

Row spend: ~15 calls. Notable: four serving endpoints across legs
(Together, Parasail, Modal, Fireworks); `require_parameters: true` leg H
returned an upstream 404 with no endpoint attributed, so the flag's effect
on this row is unverified and must be re-run before any default change
(open question 1 input).

| google/gemini-3.8-flash | A | low | passed | Google |
| google/gemini-3.8-flash | B | low | failed: calls serialized, leg asserts | Google |
| google/gemini-3.8-flash | C+D | low | passed, history preserved | Google |
| google/gemini-3.8-flash | E | low | passed, red seen, no endpoint attributed | none |
| google/gemini-3.8-flash | F | max | not run (session cap) | - |
| google/gemini-3.8-flash | G | low | not run (session cap) | - |
| google/gemini-3.8-flash | H | low | not run (session cap) | - |

Row spend: ~8 calls. Notable: single endpoint (Google) across all legs,
unlike the multi-endpoint rotation on GLM/DeepSeek rows; image turns carry
no endpoint metadata while tool turns do.

Scope not run this session (all rows): leg A at each row's highest
listed effort level (only `low`, the default, was probed), leg F in Lite
wire mode (classic only), and the four recon open questions except the
partial leg-H input on Q1 noted above.

Row edits proposed from this session: none. The parallel serialization
appears on three unrelated upstreams (harness/client confound, not endpoint
evidence); the leg-H 404 argues against a `require_parameters` default
rather than for any pin; no endpoint-specific failure was attributed to a
pinnable endpoint. Pins and 173 steps 2-4 wait for per-endpoint evidence
from a later session.

Session cap reached (3 rows: GLM Flash, DeepSeek Flash, Gemini Flash).
Remaining rows (Kimi K3, Qwen, Muse rows, GLM 5.3, DeepSeek Pro after its
routing check, Gemini Pro, Grok, Anthropic rows, GPT twins), legs F/G/H
where skipped, and open questions 1-4 (Q1 partially informed by the leg H
result above) wait for the next approved session.

## Probe matrix 2026-09-15 (plan 175, router 0.6.63.65 isolated, legs A-G)

Session 2 of the paid matrix. Isolated candidate router plus a disposable
`--codex-home`; the live install and live Codex home were not used.
`qwen/qwen3.8-max-0902` was skipped: the OpenRouter key cannot use that
id (`/models/user` has other Qwen ids, not this one), so the live picker
already hides it. Budget remaining after this session is unused rather
than spent on a blocked row.

Legenda unchanged from the 2026-09-14 table. Isolated catalogues still
list the registry Qwen row because they do not apply the key filter;
that is candidate-router behaviour, not live picker visibility.

| model | leg | effort | result | serving_endpoint |
|---|---|---|---|---|
| moonshotai/kimi-k3 | A | low | passed | none |
| moonshotai/kimi-k3 | A | max | passed | Together |
| moonshotai/kimi-k3 | B | low | failed: calls serialized, leg asserts | none |
| moonshotai/kimi-k3 | C | low | passed, history preserved | Together |
| moonshotai/kimi-k3 | D | low | passed into DeepSeek, history preserved | Parasail (Kimi), Together (DeepSeek) |
| moonshotai/kimi-k3 | E | low | failed: answered `Black` | Parasail |
| moonshotai/kimi-k3 | F | - | not run (session cap) | - |
| moonshotai/kimi-k3 | G | low | passed | Together |
| moonshotai/kimi-k3 | H | - | not run (session cap) | - |

Row spend: 16 counted calls. Notable: same parallel-serialization
harness failure as 2026-09-14; image colour still wrong on Parasail
(`Black`, matching the 2026-09-09 live-router image note).

| meta/muse-spark-1.3 | A | low | passed | Meta |
| meta/muse-spark-1.3 | A | max | passed | Meta |
| meta/muse-spark-1.3 | B | low | failed: calls serialized, leg asserts | Meta |
| meta/muse-spark-1.3 | C | low | passed, history preserved | Meta |
| meta/muse-spark-1.3 | D | low | passed into DeepSeek, history preserved | Meta, Together |
| meta/muse-spark-1.3 | E | low | passed, red seen | Meta |
| meta/muse-spark-1.3 | F | - | not run (session cap) | - |
| meta/muse-spark-1.3 | G | low | passed | Meta |
| meta/muse-spark-1.3 | H | - | not run (session cap) | - |

Row spend: 16 counted calls. Notable: image colour now passes on Meta
(the 2026-09-09 live-router image leg on this row had answered
`unknown`). Parallel serialization still matches the other vendors.

| meta/muse-spark-1.3-contributor | A | low | passed | Meta |
| meta/muse-spark-1.3-contributor | A | xhigh | passed | Meta |
| meta/muse-spark-1.3-contributor | B | low | failed: calls serialized, leg asserts | Meta |
| meta/muse-spark-1.3-contributor | C | low | passed, own reasoning replayed, history preserved | Meta |
| meta/muse-spark-1.3-contributor | D | low | passed into DeepSeek, history preserved | Meta, Together |
| meta/muse-spark-1.3-contributor | E | low | failed: answered `unknown` | Meta |
| meta/muse-spark-1.3-contributor | F | - | not run (session cap) | - |
| meta/muse-spark-1.3-contributor | G | low | passed | Meta |
| meta/muse-spark-1.3-contributor | H | - | not run (session cap) | - |

Row spend: 16 counted calls. Open question 4 (does Contributor accept
its own reasoning item back): yes on leg C at `low` (`history_preserved`).
Image colour still fails on this row (`unknown`), unlike standard Muse
in this session.

Session cap reached (3 rows: Kimi K3, Muse Spark, Muse Contributor).
Remaining rows: GLM 5.3, DeepSeek Pro after its routing check, Gemini
Pro, Grok, Anthropic rows, GPT twins. Qwen stays skipped until the key
can use `qwen/qwen3.8-max-0902`. Legs F/H and open questions 1-3 still
wait. Row edits proposed: none (parallel serialization remains a
harness/client confound; image colour is vendor/endpoint behaviour, not
a roster pin).

## Probe matrix 2026-09-15 session 3 (plan 175, router 0.6.63.65 isolated, legs A-G)

Session 3 of the paid matrix. Isolated candidate router plus a disposable
`--codex-home`; the live install and live Codex home were not used.
Legenda unchanged from the 2026-09-14 table.

| model | leg | effort | result | serving_endpoint |
|---|---|---|---|---|
| z-ai/glm-5.3 | A | low | passed | Phala |
| z-ai/glm-5.3 | A | max | passed | Phala |
| z-ai/glm-5.3 | B | low | failed: calls serialized, leg asserts | Phala |
| z-ai/glm-5.3 | C | low | passed, history preserved | Phala |
| z-ai/glm-5.3 | D | low | passed into DeepSeek, history preserved | Phala (GLM), Together (DeepSeek) |
| z-ai/glm-5.3 | E | low | passed: turn completed, image noted on the wire, no refusal | Phala |
| z-ai/glm-5.3 | F | - | not run (session cap) | - |
| z-ai/glm-5.3 | G | low | passed | Phala |
| z-ai/glm-5.3 | H | - | not run (session cap) | - |

Row spend: ~25 counted calls, slightly over the 23-call cap on two
repeated leg-D attempts (the first leg-D invocation duplicated leg C
and was re-run correctly). The row stops here per the plan. Notable:
single endpoint (Phala) across all legs, unlike the multi-endpoint
rotation on GLM Flash. Leg E is the
plan 174 acceptance live: the image rode in the sent turn and the turn
completed with the visible note instead of refusing. A follow-up switch
turn on the same thread also completed, so the historical-image path
holds on this row.

| deepseek/deepseek-v4-pro-0813 | A | low | passed | CoreWeave |
| deepseek/deepseek-v4-pro-0813 | A | max | passed | CoreWeave |
| deepseek/deepseek-v4-pro-0813 | B | low | failed: calls serialized, leg asserts | CoreWeave |
| deepseek/deepseek-v4-pro-0813 | C | low | passed, own reasoning replayed, history preserved | CoreWeave |
| deepseek/deepseek-v4-pro-0813 | D | low | passed into DeepSeek Flash, history preserved | CoreWeave (Pro), Together (Flash) |
| deepseek/deepseek-v4-pro-0813 | E | low | passed: turn completed, image noted on the wire, no refusal | CoreWeave |
| deepseek/deepseek-v4-pro-0813 | F | - | not run (session cap) | - |
| deepseek/deepseek-v4-pro-0813 | G | low | passed | CoreWeave |
| deepseek/deepseek-v4-pro-0813 | H | - | not run (session cap) | - |

Row spend: ~17 counted calls. Notable: the plan 175 routing check
passes, `served_model` echoes `deepseek/deepseek-v4-pro-0813`
verbatim on CoreWeave, so this row is not a silent alias and stays
probed. Single endpoint (CoreWeave) across all legs. Leg E matches the
GLM 5.3 plan 174 note above.

| google/gemini-3.1-pro-preview | A | low | failed: tool called, final narrated, strict echo assert fails | Google |
| google/gemini-3.1-pro-preview | A | high | failed: same echo shape | Google |
| google/gemini-3.1-pro-preview | B | low | not reached: base echo assert fails first | Google |
| google/gemini-3.1-pro-preview | C | low | not reached: base echo assert fails first | Google |
| google/gemini-3.1-pro-preview | D | low | not reached: base echo assert fails first | Google |
| google/gemini-3.1-pro-preview | E | low | passed, red seen | Google |
| google/gemini-3.1-pro-preview | F | - | not run (session cap) | - |
| google/gemini-3.1-pro-preview | G | low | not reached: base echo assert fails first | Google |
| google/gemini-3.1-pro-preview | H | - | not run (session cap) | - |

Row spend: ~19 counted calls. Notable: the tool call itself succeeds on
Google every attempt and the marker content comes back, but the final
wraps it in prose (`The result is ...`), so the harness's exact-echo
assert fails on every attempt except leg E, which passed once with the
exact echo and `red seen`. This is vendor verbosity, not an upstream
rejection, so no plan stop condition fires. The row's top effort is `high`; a `max`
attempt is refused by the router's effort gate with `PROVIDER_REJECTED`
(a harness mistake, not row evidence). Single endpoint (Google) across
all legs.

Session cap reached (3 rows: GLM 5.3, DeepSeek Pro, Gemini Pro).
Remaining rows: Grok, Anthropic rows, GPT twins. Qwen stays skipped
until the key can use `qwen/qwen3.8-max-0902`. Legs F/H and open
questions 1-3 still wait. Row edits proposed: none (parallel
serialization remains a harness/client confound; image noting is the
plan 174 design; Gemini narration is vendor behaviour, not a roster
pin).

## Probe matrix 2026-09-15 sessions 4-6 (plan 175, router 0.6.63.65 isolated, legs A-G)

Sessions 4 to 6 of the paid matrix, three rows each per the plan's
per-session cap: Grok plus Haiku plus Sonnet (session 4), Opus plus Fable
plus Luna (session 5), Sol plus Terra plus Astra (session 6). Isolated
candidate router plus a disposable `--codex-home`; the live install and
live Codex home were not used. Legenda unchanged from the 2026-09-14
table. These nine rows close the A-G legs of the matrix.

| model | leg | effort | result | serving_endpoint |
|---|---|---|---|---|
| x-ai/grok-4.6 | A | low | passed | xAI |
| x-ai/grok-4.6 | A | xhigh | passed | xAI |
| x-ai/grok-4.6 | B | low | failed: calls serialized, leg asserts | xAI |
| x-ai/grok-4.6 | C | low | passed, history preserved | xAI |
| x-ai/grok-4.6 | D | low | passed into DeepSeek, history preserved | xAI (Grok), Together (DeepSeek) |
| x-ai/grok-4.6 | E | low | failed: answered `unknown` | xAI |
| x-ai/grok-4.6 | F | - | not run (session cap) | - |
| x-ai/grok-4.6 | G | low | passed | xAI |
| x-ai/grok-4.6 | H | - | not run (session cap) | - |

Row spend: ~12 counted calls. Notable: single endpoint (xAI) on Grok
turns; the DeepSeek side of leg D answered from Together. The image turn
answered `unknown` because this row pins `drop_images: true`: the router
notes the image on the wire instead of sending it, so the colour question
has no image to answer from. Contributor's same-looking answer has a
different cause (`drop_images: false` on that row).

| anthropic/claude-haiku-4.5 | A | none | passed | none |
| anthropic/claude-haiku-4.5 | B | none | failed: calls serialized, leg asserts | none |
| anthropic/claude-haiku-4.5 | C | - | not run: switch helper sends `low`, row allows `none` only | - |
| anthropic/claude-haiku-4.5 | D | - | not run: same effort-gate confound as C | - |
| anthropic/claude-haiku-4.5 | E | - | not run: image follow-up sends `low`, row allows `none` only | - |
| anthropic/claude-haiku-4.5 | F | - | not run (session cap) | - |
| anthropic/claude-haiku-4.5 | G | none | passed | none |
| anthropic/claude-haiku-4.5 | H | - | not run (session cap) | - |

Row spend: ~6 counted calls. Notable: the only `none`-default row in the
roster. Legs C, D and E are harness confounds, not row evidence: the
switch helper and the image follow-up both hard-code `low`, so the
router's effort gate refuses with `PROVIDER_REJECTED` before any upstream
call. Tool turns carry no endpoint metadata on this row. The three legs
need a rerun with an effort-aware helper before any row edit is proposed.

| anthropic/claude-sonnet-5 | A | low | passed | none |
| anthropic/claude-sonnet-5 | A | max | passed | none |
| anthropic/claude-sonnet-5 | B | low | failed: calls serialized, leg asserts | none |
| anthropic/claude-sonnet-5 | C | low | passed, history preserved | none |
| anthropic/claude-sonnet-5 | D | low | passed both directions, history preserved | none |
| anthropic/claude-sonnet-5 | E | low | failed: image reported not attached | none |
| anthropic/claude-sonnet-5 | F | - | not run (session cap) | - |
| anthropic/claude-sonnet-5 | G | low | passed | none |
| anthropic/claude-sonnet-5 | H | - | not run (session cap) | - |

Row spend: ~13 counted calls. Notable: tool turns on the Anthropic rows
carry no endpoint metadata in this session, unlike the named endpoints on
other vendors. Leg E is a conversion observation, not a colour miss: the
row says the image never arrived.

| anthropic/claude-opus-5 | A | low | passed | none |
| anthropic/claude-opus-5 | A | max | passed | none |
| anthropic/claude-opus-5 | B | low | failed: calls serialized, leg asserts | none |
| anthropic/claude-opus-5 | C | low | passed, history preserved | none |
| anthropic/claude-opus-5 | D | low | passed both directions, history preserved | none |
| anthropic/claude-opus-5 | E | low | passed, red seen | none |
| anthropic/claude-opus-5 | F | - | not run (session cap) | - |
| anthropic/claude-opus-5 | G | low | passed | none |
| anthropic/claude-opus-5 | H | - | not run (session cap) | - |

Row spend: ~12 counted calls. Notable: the only Anthropic row in this
session with a passing image leg; Sonnet on the same vendor and harness
reported no attachment.

| anthropic/claude-fable-5.1 | A | low | passed | none |
| anthropic/claude-fable-5.1 | A | max | passed | none |
| anthropic/claude-fable-5.1 | B | low | failed: calls serialized, leg asserts | none |
| anthropic/claude-fable-5.1 | C | low | passed, history preserved | none |
| anthropic/claude-fable-5.1 | D | low | passed both directions, history preserved | none |
| anthropic/claude-fable-5.1 | E | low | passed, red seen | none |
| anthropic/claude-fable-5.1 | F | - | not run (session cap) | - |
| anthropic/claude-fable-5.1 | G | low | passed | none |
| anthropic/claude-fable-5.1 | H | - | not run (session cap) | - |

Row spend: ~12 counted calls. Notable: matches Opus leg for leg,
including the passing image turn.

| openai/gpt-5.6-luna | A | low | passed | none |
| openai/gpt-5.6-luna | A | max | passed | none |
| openai/gpt-5.6-luna | B | low | failed: calls serialized, leg asserts | none |
| openai/gpt-5.6-luna | C | low | passed, history preserved | none |
| openai/gpt-5.6-luna | D | low | passed both directions, history preserved | none |
| openai/gpt-5.6-luna | E | low | passed, red seen | none |
| openai/gpt-5.6-luna | F | - | not run (session cap) | - |
| openai/gpt-5.6-luna | G | low | passed | none |
| openai/gpt-5.6-luna | H | - | not run (session cap) | - |

Row spend: ~12 counted calls. Notable: fully green except the shared
parallel-serialization confound; tool turns carry no endpoint metadata on
this row.

| openai/gpt-5.6-sol | A | low | passed | none |
| openai/gpt-5.6-sol | A | max | passed | none |
| openai/gpt-5.6-sol | B | low | failed: calls serialized, leg asserts | none |
| openai/gpt-5.6-sol | C | low | passed, history preserved | none |
| openai/gpt-5.6-sol | D | low | passed both directions, history preserved | none |
| openai/gpt-5.6-sol | E | low | failed: answered `Cyan` | none |
| openai/gpt-5.6-sol | F | - | not run (session cap) | - |
| openai/gpt-5.6-sol | G | low | passed | none |
| openai/gpt-5.6-sol | H | - | not run (session cap) | - |

Row spend: ~12 counted calls. Notable: the image turn completed but the
colour came back `Cyan`, vendor behaviour rather than a refusal; Luna on
the same harness answered `red`.

| openai/gpt-5.6-terra | A | low | passed | none |
| openai/gpt-5.6-terra | A | max | passed | none |
| openai/gpt-5.6-terra | B | low | failed: calls serialized, leg asserts | none |
| openai/gpt-5.6-terra | C | low | passed, history preserved | none |
| openai/gpt-5.6-terra | D | low | passed both directions, history preserved | none |
| openai/gpt-5.6-terra | E | low | passed, red seen | none |
| openai/gpt-5.6-terra | F | - | not run (session cap) | - |
| openai/gpt-5.6-terra | G | low | passed | none |
| openai/gpt-5.6-terra | H | - | not run (session cap) | - |

Row spend: ~12 counted calls. Notable: fully green except the shared
parallel-serialization confound.

| openai/gpt-6-astra | A | low | passed | none |
| openai/gpt-6-astra | A | max | passed | none |
| openai/gpt-6-astra | B | low | failed: calls serialized, leg asserts | none |
| openai/gpt-6-astra | C | low | passed, history preserved | none |
| openai/gpt-6-astra | D | low | passed both directions, history preserved | none |
| openai/gpt-6-astra | E | low | failed: answered `Pink` | none |
| openai/gpt-6-astra | F | - | not run (session cap) | - |
| openai/gpt-6-astra | G | low | passed | none |
| openai/gpt-6-astra | H | - | not run (session cap) | - |

Row spend: ~12 counted calls. Notable: the image turn completed but the
colour came back `Pink`; Terra on the same harness answered `red`.

Matrix close: legs A to D are recorded for every row probed in sessions
1 to 6 except Haiku C/D, which need the effort-aware rerun; leg E is recorded
except where the harness effort gate blocked it, and leg G wherever the row
and session caps allowed it. Still open: Haiku legs C/D/E (effort-aware
rerun), leg A at the top listed effort on GLM Flash, DeepSeek Flash and
Gemini Flash, leg G on GLM Flash and Gemini Flash, Gemini Pro legs B/C/D/G
(blocked behind its narrated base echo, not the caps), and Qwen, which stays
skipped until the key can use `qwen/qwen3.8-max-0902`. Legs F/H and open
questions 1-3 still wait for a later approved session. Row edits proposed:
none (parallel serialization is now an eight-vendor harness/client
confound; image colour variance is vendor behaviour, not a roster pin;
the Haiku gaps are harness confounds awaiting rerun).

## Probe matrix 2026-09-15 session 7 (plan 175, router 0.6.65 isolated, tail legs)

Session 7 of the paid matrix, on current develop (0.6.65 tree).
Legenda unchanged from the 2026-09-14 table. All tabled legs below run
on the isolated candidate router plus a disposable `--codex-home`; leg F
uses the handoff probe's isolated-children mode (in-process candidate
router, fresh token). One stopped attempt in plain `--live` mode did
route parent traffic through the installed router before it was stopped
(see below); no tabled leg uses the live install. This session works
through the deferred gaps from the matrix close, cheapest first.

| model | leg | effort | result | serving_endpoint |
|---|---|---|---|---|
| z-ai/glm-5.3-flash | A | max | passed | Together |
| deepseek/deepseek-v4.1-flash | A | max | passed | Parasail |
| google/gemini-3.8-flash | A | high | passed | Google |
| z-ai/glm-5.3-flash | G | low | passed | Phala |
| google/gemini-3.8-flash | G | low | passed | Google |
| anthropic/claude-haiku-4.5 | C | none | passed, history preserved | none |
| anthropic/claude-haiku-4.5 | D | - | not runnable: Haiku allows `none` only, DeepSeek allows `low` and up, one turn cannot satisfy both | - |
| anthropic/claude-haiku-4.5 | E | none | failed: image reported not attached | none |
| deepseek/deepseek-v4.1-flash | H | low | passed | Modal |
| z-ai/glm-5.3-flash | H | low | passed | Parasail |
| google/gemini-3.8-flash | H | low | passed | Google |
| moonshotai/kimi-k3 | H | low | passed | none |
| z-ai/glm-5.3-flash | F | max | passed: 3 of 3 markers replied through the isolated-children path | unattributed (ephemeral handoff log) |

Row spend: ~27 counted calls on isolated legs, plus a stopped 12-call
attempt in the wrong handoff mode. Notable: leg A at top effort passes on
all three session-1 rows, so every probed row now has the full leg-A pair
except Gemini Pro, whose base echo assert fails first. Haiku leg C passes
at `none` after the effort-aware harness fix (two hard-coded `low`
efforts in `tools/probe_codex_runtime.py` now follow `--effort`); leg D
is untestable in one run across the effort boundary (one `--effort` value
drives every turn, Haiku allows `none` only, DeepSeek allows `low` and
up), which is a harness limitation, not row evidence. Haiku leg E at
`none` reports no attachment, matching Sonnet's conversion observation on
the same vendor. Leg H passes on all four rows attempted and narrows the
endpoint set to one each (Modal, Parasail, Google); Kimi tool turns carry
no endpoint metadata. Leg F passes on the GLM Flash child (DeepSeek
parent, 3 of 3 markers, canonical replay true) through the isolated
`--live-children` path without `--installed`; a prior attempt in plain
`--live` mode was stopped after 12 calls because that mode points the
parent at the installed router, which plan 175 STOPs on, and this client
(`codex-cli 0.154.0-alpha.6.2`) never emits the collaboration aliases
there. Open question 3 (a model calling `openrouter_web_search`) is not
reproduced: the `--web-search` leg fails at app-server startup on this
client build before any billed call, on retries as well as first attempt.
Still open after this session: Haiku leg D (harness limitation), Gemini
Pro legs B/C/D/G (narrated base echo), Qwen (key-blocked), remaining leg
F rows and leg H rows, and open questions 1-3 (Q3 blocked at
app-server startup on this client build).

Harness change in this session: `run_switch_leg` and the image
follow-up now take their effort from `--effort` instead of hard-coding
`low`. Offline harness suite passes unchanged (34 tests). The change is
required for any `none`-default row; every switch shape and the image
follow-up now follow an explicit `--effort`, with `low` as the fallback.

Row edits proposed: none (top-effort A legs pass; Haiku D is a harness
limitation; Haiku E matches the known Sonnet conversion observation;
leg-H narrowing is per-attempt evidence, not a pin yet; the GLM Flash F
pass confirms the isolated handoff path but proposes no roster change).

## Subagent visibility on the installed router, 2026-09-16 (plan 151)

Real-machine check, no probe harness: the installed router's own log
(`~/.codex/mixed-model-router/logs/router.jsonl`, router 0.6.70.74) recorded
**1287 completed requests to `meta/muse-spark-1.3-contributor`**, every one
attributed to **Meta**, between 10:41 and 14:25 UTC on 2026-09-16, alongside
`deepseek/deepseek-v4.1-flash` traffic. Those are routed turns, so the client
sent that OpenRouter row as a model id and the router served it.

Limitation: the log carries no client version, so the delegating session's
build is not recoverable from this evidence; the count is comparable across
upgrades only as "an installed router served this row".

Stage 3 decision, default taken under the plan's owner gate: the five override
slots keep the roster first and no ordering change lands, so the picker and the
existing pins are untouched.

Row edits proposed: none. Still open: plan 151 stage 4, the no-billing capture
that asserts the override set against a local sink.

## Leg F re-runs, 2026-09-16 (plan 175)

Client: `codex-cli 0.154.0-alpha.6.2`; router 0.6.78 working tree. Same
in-process candidate recipe as the first F run, now with
`--max-live-calls 20 --parent deepseek/deepseek-v4.1-flash --wire-mode
classic`.

| child | result | facts |
|---|---|---|
| z-ai/glm-5.3 | passed | 3 of 3 markers, canonical replay, alias emitted; the earlier 12-call run was cut by the cap, not by a defect |
| google/gemini-3.8-flash | inconclusive | 3 of 3 markers, canonical replay, alias emitted, but six upstream 503s on the parent plus five cap errors ended the run |

Reading: the markers replayed on both children, with a full pass on GLM 5.3
once the cap left room for the parent's extra turns. Gemini Flash stays
unproven: the parent's DeepSeek turns hit transient 503s, which the probe
counts as errors and which pushed the run into the cap, so it needs a
quiet-upstream re-run.

Correction, 2026-09-17: the GLM 5.3 pass above rested on the printed facts,
not on the harness's exit code. The live-children gate also demanded the
native control marker (`SYNTH_NATIVE_CONTROL`), which a non-native parent never
produces, so every run of this shape exited 1 whatever its facts. The gate now
requires that marker only for a `gpt-` parent; the re-runs below carry real
exit codes.

## Haiku legs C and D, 2026-09-16 (plan 175)

Client: `codex-cli 0.154.0-alpha.6.2`; router 0.6.78 working tree in an
isolated home on its own port and token, with a disposable Codex home. These
two legs carried the plan's last harness limitation: Haiku accepts `none` only
while its partners accept `low` and up, so one `--effort` could not serve both
turns. The probe now takes `--switch-effort` for the switched turn alone and
accepts `--switch-back` after `--switch-in`.

| leg | turns | result | serving_endpoint |
|---|---|---|---|
| C, same-slug replay | base `none`, out and back | passed: both switch turns recalled the marker | not reported |
| D, into DeepSeek and back | base `none`, out at `low`, back at `none` | passed: both switch turns recalled the marker | DeepSeek on Together; Haiku unnamed |

Eight completions across the row's eight turns plus two expected 426 websocket
fallbacks, inside the plan's 23-call cap. Haiku reports no `serving_endpoint`,
so its own upstream stays unattributed; the DeepSeek turn lands on Together as
in the other sessions.

## Claude CLI tool round trip on an OpenRouter-routed Claude row, 2026-09-17 (plan 115)

Client: the installed Claude Code CLI (`2.1.223 (Claude Code)`) against an isolated
router (0.6.78 working tree, own home, port and token), model
`anthropic/claude-haiku-4.5`, with `ANTHROPIC_AUTH_TOKEN` unset so the CLI's
own bearer is used. The session
was asked to read a synthetic marker file with the Read tool.

| step | result |
|---|---|
| first Messages request | completed, 200 |
| follow-up carrying the tool result | upstream 400 `invalid_request`; the router answers a final 409 `PROVIDER_REJECTED` |
| attempts | 11, then the CLI stopped with "Do not retry the unchanged request" |

Result: the tool round trip does not complete on this route, so plan 115's
first proof is not met. The failure sits on the follow-up body - the first
request of the same session was served - and the provider names only
`invalid_request`, so the next step is to capture which part of that body the
OpenRouter-backed Anthropic endpoint refuses, not to re-run the leg.

Offline narrowing, 2026-09-17: `ExternalMessagesProvider.prepare` forwards the
client's Messages body verbatim for this row - a synthetic
text/tool_use/tool_result body comes back byte-identical, with only the model
id rewritten when a row carries a different upstream id - and posts it to
`openrouter.ai/api/v1/messages`. So the router adds no translation here, and
the refusal is in the body Claude Code sends on the follow-up or in that
endpoint's view of it. The next step is to capture both request bodies the CLI
sends, which needs no paid call.

Second narrowing, 2026-09-17: the CLI was pointed at a local Messages sink and
both of its request bodies were captured - the opening turn and the follow-up
carrying `tool_use` and `tool_result` - with identical headers apart from
content-length. The router sends both verbatim (checked against the captured
bytes), and both are accepted (200) when replayed straight to
`openrouter.ai/api/v1/messages`, with and without the client's `anthropic-beta`
list and the `?beta=true` query. So neither the client's body nor the router's
forwarding explains the live refusal. What the sink capture cannot show is the
one thing that makes the live follow-up different: it echoes the assistant
content the router returned, thinking blocks included. Next step: take one
live turn through the router, keep the response it returns, and post that
response back as the assistant turn; a refusal there would put the trigger in
the router's stream adaptation rather than in the request.

Resolution, 2026-09-17: the refusal is the connector tool volume, not the
router and not the shape of the client's body. Four observations, cheapest
first:

- The captured live follow-up body (168,406 bytes at the sink) replays
  through the isolated router at 200, streamed and not streamed, on the
  0.6.78 working tree.
- Recapturing the live follow-up at the router's own upstream socket (an
  in-process recorder wrapped around the relay connection) shows the live
  follow-up is 1,465,284 bytes, of which 1,456,470 is the `tools` array:
  **702 tools, up from 29 in the opening turn**. The first turn is where
  Claude Code finishes loading the user's claude.ai connector MCP tools
  (Apollo, Attio, Clay, Granola, Heyreach, Instantly, Microsoft 365, Xero,
  Airwallex, monday.com, n8n and others), so every later turn carries them.
- Posted straight to `openrouter.ai/api/v1/messages`, that body answers 400
  with the reason the router's bounded log line drops: "This endpoint's
  maximum context length is 200000 tokens. However, you requested about
  398263 tokens (14845 of text input, 351418 of tool input, 32000 in the
  output)." The same body with only its 33 non-MCP tools answers 200.
- So the follow-up is a genuine over-context request - 351K tokens of tool
  definitions alone against a 200K window - that any route would refuse.
  The router forwards the body verbatim and, per plan 169, answers the
  upstream refusal with a final 409 `PROVIDER_REJECTED`.

Plan 115's first proof is met by re-running the leg with the connector servers
excluded (`--strict-mcp-config --mcp-config '{"mcpServers": {}}'`): the same
CLI, model and isolated-router shape completed the tool round trip - Read
executed, the marker came back verbatim, two Messages requests, both 200
(164,784 and 166,071 bytes). Operator note: `docs/claude-code.md` carries the
caveat that a routed row inherits whatever the client loads from its
connectors, and a tool list that large cannot fit any 200K row.

## Leg F re-runs with the corrected exit gate, 2026-09-17 (plan 175)

Client: `codex-cli 0.154.0-alpha.6.2`; router 0.6.78 working tree.
`tools/probe_agent_handoffs.py --live --live-children --max-live-calls 20
--parent deepseek/deepseek-v4.1-flash --wire-mode classic`.

| child | exit | facts |
|---|---|---|
| z-ai/glm-5.3 | 0, passed | 3 of 3 markers, all three replied, no errors, canonical replay, alias emitted, 20 calls inside the cap |
| google/gemini-3.8-flash | 1, inconclusive | nine upstream 503s on the parent and five cap errors; markers never arrived this time |

Reading: leg F passes on GLM 5.3 under the harness's own exit gate. Gemini
Flash stays unproven and has now failed twice for upstream reasons (six 503s
on 2026-09-16, nine on 2026-09-17) rather than for anything the router did;
it needs a quiet upstream window, and the run is cheap to repeat when one
opens.

Third attempt, later on 2026-09-17: same shape, nine upstream 503s on the parent,
no markers, exit 1. Three attempts have now failed, the last two without markers, so the leg
should not be retried blind; next retry needs a different parent than
DeepSeek V4.1 Flash or a parent-upstream quiet window.

Delivery note (plan 119): the GLM 5.3 leg above is the live half (3 of 3
markers replied, canonical replay, alias emitted, no errors, inside the
cap). The containment half stays offline in `tests/test_agent_containment.py`,
where `prepare` rejects encrypted agent briefs and plaintext still prepares.

## Leg H `require_parameters` pin on the GLM 5.3 Flash row, 2026-09-16 (plan 175)

Client: `codex-cli 0.154.0-alpha.6.2`, effort `low`; router 0.6.78 working
tree in an isolated home on its own port and token. The row carried
`provider_prefs: {"require_parameters": true}` in `ai_router/models.json` for
the duration of the run only, and the file was restored afterwards; the offline
tests in `tests/test_providers.py` already prove that object reaches the
upstream request body.

| step | result |
|---|---|
| base tool round trip with the pin | failed: upstream 404, router answers a final 400 `PROVIDER_REJECTED`, the client turn raises |
| completions | none |

Reading: no endpoint on this row accepts every parameter the client sends, so
OpenRouter answers 404 in both attempts and the pin turns a working row into a
refused turn; the unpinned baseline on the same row passes leg A. This is the
concrete counter-example the pin question needed: `provider_prefs` stays an
available field, and no row should set `require_parameters` without evidence
that its endpoints accept every parameter in the request.

## Leg F on the GLM 5.3 child, 2026-09-16 (plan 175)

Client: `codex-cli 0.154.0-alpha.6.2`; router 0.6.78 working tree.
`tools/probe_agent_handoffs.py --live --live-children --max-live-calls 12
--parent deepseek/deepseek-v4.1-flash --child z-ai/glm-5.3 --wire-mode
classic`.

| fact | value |
|---|---|
| markers delivered to the child | 3 of 3 |
| canonical replay | true |
| alias emitted | true |
| encrypted child | false (plaintext shape) |
| end state | not reached: parent kept calling collaboration tools to the 12-call cap |

Reading: 3 of 3 markers reached the child with canonical replay and alias
emission, but the leg did not finish inside the cap. Inconclusive at the cap,
not a handoff failure; re-run with higher `--max-live-calls` inside the
plan's 23-call budget.

## Gemini Pro base echo re-run, 2026-09-16 (plan 175 leg A)

Client: `codex-cli 0.154.0-alpha.6.2`, effort `low`; router 0.6.78 working
tree in an isolated home on its own port and token, with a disposable Codex
home. `tools/probe_codex_runtime.py google/gemini-3.1-pro-preview` on the
current client: two completed requests served by Google, plus the expected
426 websocket fallback.

Result unchanged from 2026-09-15. The row calls `echo_probe` correctly
(`calls=1`) and then narrates the answer (`The tool result is
CODEX_OPENROUTER_OK_719.`), so the base leg's strict echo assert fails on the
model's final text, not on a router gap. The base leg gates the rest of a
session, so Gemini Pro legs B/C/D/G stay unrun.

## Muse Contributor carried-history probe, 2026-09-16 (plan 150)

Client: `codex-cli 0.154.0-alpha.6.2`, the app-server build, effort `low`.
Router: 0.6.78 working tree in an isolated home on its own port and token.

Plan 150's last open item, re-run because the desktop has upgraded since the
2026-09-12 refusal. `tools/probe_codex_runtime.py deepseek/deepseek-v4.1-flash
--switch-in meta/muse-spark-1.3-contributor` with an isolated `--router-state`
and a disposable `--codex-home`:

| step | result | serving_endpoint |
|---|---|---|
| base tool round trip on DeepSeek V4.1 Flash | passed | Together |
| switch into Muse Spark 1.3 Contributor, prompted without tools | passed, marker recalled; tool-call absence is not asserted by this leg | Meta |

Three completed requests (two DeepSeek, one Muse) plus the expected 426
websocket fallback. The switch turn recalling the marker is the contract the
2026-09-12 incident broke twelve times on carried reasoning, so the
`history_mode: portable` row now has live evidence on this client build.
Slices 2c/2d stay unproven by their own rule: reopen only on a new refusal
shape.

## Isolated candidate round trip, 2026-09-16 (plan 175 row re-check)

Client: `codex-cli 0.154.0-alpha.6.2` (the app-server build), effort `low`.
Router: 0.6.77 working tree. Billed: yes, one row, four legs.

The paid path was re-validated before the remaining matrix legs run, because
the history-switch probe tool had gone stale and no paid leg had run since
2026-09-15. `ai_router.candidate` booted a throwaway router from the working
tree with its own home, port, token and catalogue, and ran the row's implied
legs through `tools/probe_codex_runtime.py` with a disposable Codex home.

| model | legs, by plan 175 letter | result |
|---|---|---|
| z-ai/glm-5.3-flash | tool and stream (A), image (E), compact (G) | passed |

No row edit is proposed; this re-establishes leg A on 0.6.77 and repeats E and
G. Provenance limit: the candidate captures the probe's own output rather than
printing it, so this entry carries no per-leg `serving_endpoint` and no exact
call count. Endpoint drift on this row (Together, Venice and Parasail across
sessions) stays visible only in sessions that run `probe_codex_runtime.py`
directly with `--router-state`, as the 2026-09-15 sections do, until the
candidate surfaces the probe detail.

## History switch and refusal classes, 2026-09-16

Client: `codex-cli 0.154.0-alpha.6.2`, the app-server inside
`/Applications/ChatGPT.app/Contents/Resources/codex`; router 0.6.77 working
tree. Fake upstream, no model calls billed; `tools/probe_history_switch.py`.

| Scenario | Result | Upstream attempts | Models |
|---|---|---|---|
| switch, carried history out and back | passed | 3 | DeepSeek V4.1 Flash, GPT-6 Astra, DeepSeek V4.1 Flash |
| deterministic refusal | passed | 1 | GPT-6 Astra |
| transient upstream failure, then success | passed | 2 | GPT-6 Astra |

The switch leg asserts that the router replays the foreign provider's
reasoning on the way back, which is plan 150's contract; the other two pin
plan 169's final-versus-retryable split (one attempt for a final refusal, a
second attempt for a transient one). The probe tool itself could not start:
it still called `probe_context_budget.Client` without the `mode` argument
that signature gained, so the run died before the client booted. That is
fixed in this change and the run above is the evidence.

## Leg F on the Gemini Flash child with a GLM parent, 2026-09-17 (plan 175)

Client: `codex-cli 0.154.0-alpha.6.2`; router 0.6.78 working tree.
`tools/probe_agent_handoffs.py --live --live-children --max-live-calls 18
--parent z-ai/glm-5.3-flash --child google/gemini-3.8-flash --wire-mode classic`.

| fact | value |
|---|---|
| calls | 17, inside the 18-call run cap and the row's 23-call cap |
| markers replied | 3 of 3 (`SYNTH_066_INITIAL`, `SYNTH_066_FOLLOWUP`, `SYNTH_066_MESSAGE`) |
| canonical replay | true |
| alias emitted | true |
| encrypted child | false |
| errors | none; one stray `responseStreamDisconnected` (404) appears in the per-turn tool failures |

Reading: leg F passes on the Gemini Flash child in this shape - one classic
wire-mode run with a GLM Flash parent, on one quiet-upstream window. The
three earlier attempts all used DeepSeek V4.1 Flash as the parent, which is
the pairing the plan names, and died behind that parent's transient 503s;
swapping the parent closes the leg, so the failure sat in the parent's
upstream window rather than in this child. Two shapes stay open for this
child: the DeepSeek parent the plan names, and Lite wire mode. The rest of
the matrix is unchanged - the F and H rows the 2026-09-14 to 2026-09-15
tables mark `not run (session cap)` for other children are still open, and
Qwen stays key-blocked.

## Open questions 1 to 3, 2026-09-17 (plan 175)

Instruments: direct `POST https://openrouter.ai/api/v1/responses` turns on
`deepseek/deepseek-v4.1-flash` at the row's default effort, with
`X-OpenRouter-Metadata: enabled` and no router in the path; five billed
turns total, all inside the row's call cap: three for question 2 (one per
item type), and two endpoint-pinned turns for question 1. The unpinned
question 1 configuration is the question 2 `custom_tool_call` turn, which
carries the same shape.

| question | result |
|---|---|
| 1. Does OpenRouter annotate converted tool calls with `tool_kind` / `responses_item_id` / `responses_item_status`, and which DeepSeek endpoint refuses them? | not reproduced: a `custom_tool_call` + its output returned 200 both unpinned and pinned to Together and to Parasail with `allow_fallbacks: false`, so the 2026-09-13 "Extra inputs are not permitted" refusal was not measured on either endpoint in this configuration |
| 2. Do `compaction`, `additional_tools` and `custom_tool_call` items survive the conversion for a non-OpenAI vendor when sent unconverted? | all three survive: one turn each returned 200 and the model answered the marker, so DeepSeek V4.1 Flash accepts them as sent |
| 3. Does a model ever call `openrouter_web_search` when the client's `web_search` tool rides along? | not reproduced (unchanged from 2026-09-15): the `--web-search` runtime leg still fails at app-server startup on this client build before any billed call |

Open question 4 was answered on 2026-09-15 (the Contributor row accepts its
own reasoning item back, leg C), so the plan's four open questions now each
carry a recorded answer or a recorded non-reproduction.

## Leg F across the roster, 2026-09-17 (plan 175)

Client: `codex-cli 0.154.0-alpha.6.2`; router 0.6.79 working tree; parent
`z-ai/glm-5.3-flash` (the pairing that passed on 2026-09-17), wire mode
classic, `--max-live-calls 18`. Each child ran once; `calls` is that run's own
live call count.

| child | result | calls | markers |
|---|---|---|---|
| moonshotai/kimi-k3 | passed, exit 0 | 15 | 3 of 3 |
| deepseek/deepseek-v4-pro-0813 | passed, exit 0 | 15 | 3 of 3 |
| openai/gpt-5.6-terra | passed, exit 0 | 14 | 3 of 3 |
| openai/gpt-5.6-luna | passed, exit 0 | 16 | 3 of 3 |
| deepseek/deepseek-v4.1-flash | three markers, five upstream 503s on the parent forced exit 1 | 18 | 3 of 3 |
| meta/muse-spark-1.3-contributor | three markers, stopped at the cap | 18 | 3 of 3 |
| anthropic/claude-sonnet-5 | one marker behind five 503s, then the cap | 18 | 1 of 3 |
| meta/muse-spark-1.3 | stopped at the cap, no reply | 18 | 0 |
| google/gemini-3.1-pro-preview | stopped at the cap, no reply | 18 | 0 |
| x-ai/grok-4.6 | stopped at the cap, no reply | 18 | 0 |
| anthropic/claude-haiku-4.5 | stopped at the cap, no reply | 18 | 0 |
| anthropic/claude-opus-5 | stopped at the cap, no reply | 18 | 0 |
| anthropic/claude-fable-5.1 | stopped at the cap, no reply | 18 | 0 |
| openai/gpt-5.6-sol | stopped at the cap, no reply | 18 | 0 |
| openai/gpt-6-astra | stopped at the cap, no reply | 18 | 0 |

Reading: four children pass the harness's own exit gate and two more replay
all three markers. Eight reach the 18-call cap without a reply; that is a
budget outcome, not a handoff verdict, and those rows need a higher cap
(still inside the plan's 23-call ceiling) or a quieter parent before anyone
reads them as failures. With the earlier passes (GLM Flash, GLM 5.3, Gemini
Flash) every routed row now has a recorded leg-F attempt except Qwen, which
stays key-blocked.

## Leg H `require_parameters` across the roster, 2026-09-17 (plan 175)

One base tool round trip per row with `provider_prefs: {"require_parameters":
true}` carried in `ai_router/models.json` for that run only and restored
afterwards, through an isolated candidate router with a disposable Codex
home. Effort `low`, except `anthropic/claude-haiku-4.5` at `none` (its row
allows nothing else).

| rows probed here | result |
|---|---|
| both Muse rows, DeepSeek Pro, Gemini Pro, Grok, all four Anthropic rows, all four GPT twins | upstream 404 with the pin, no endpoint attributed, final `PROVIDER_REJECTED` |
| plus the earlier runs (GLM Flash, DeepSeek Flash, Gemini Flash, Kimi K3, GLM 5.3) | same 404 on every one |

Reading: the pin fails closed on all 18 routed rows; there is no row where
`require_parameters: true` narrows the endpoint set instead of refusing the
turn. `provider_prefs` stays an available field and no row sets it, which is
the decision plan 170 recorded.

## Capability legs across the roster, 2026-09-17 (plan 118)

Client `codex-cli 0.154.0-alpha.6.2`, router 0.6.79 working tree, one isolated
candidate router and a disposable Codex home per leg; effort `low` except
Haiku at `none`. Each leg uses the plan's own pass definition.

| capability | passed | failed | not reached |
|---|---|---|---|
| freeform `apply_patch` | 15 rows: the four Anthropic rows, both DeepSeek rows, both Gemini rows, Kimi, the four GPT twins, both GLM rows (`fileChange items=1`, `note.txt='beta'`) | x-ai/grok-4.6: the model never called the tool (`fileChange items=0`, file unchanged) | both Muse rows: the Meta upstream dropped the turn twice (`responseStreamDisconnected`, "Upstream request failed") |
| reasoning summaries | none | every row probed streamed no reasoning summary | google/gemini-3.1-pro-preview: the base leg's echo assert fails first (its 2026-09-15 note) |
| experimental `clock` tool | none | every row probed never called `clock` | google/gemini-3.1-pro-preview, as above |
| audio input | transport check only, not a model capability pass: the client attached a 4,844-byte silent WAV and the turn completed 200 on all four rows that advertise `audio` (both Muse rows, both Gemini rows) | none | the model's own reading of the clip is not asserted by this leg |
| web search | not run | - | the `--web-search` leg still dies at app-server startup before any billed call on this client build |

Row edits landed with this record (plan 118 step 4): `apply_patch:
"freeform"` on the 15 rows whose patch leg passed. `reasoning_summary` stays
`none` everywhere, no row gains `clock`, and `audio` stays advertised because
the upstream refusal that made it unproven on 2026-09-09 did not reproduce.

## Spawn override capture, 2026-09-17 (plan 151 stage 4)

`python3.14 tools/probe_spawn_list.py` starts a real app-server thread against
a local sink that answers 426 to the websocket upgrade, records the
`/responses` body (zstd), reads `spawn_agent`'s "Available model overrides"
text and asserts it against the first five picker rows of the catalogue the
installed router serves. No model is called, so the run is free.

| fact | value |
|---|---|
| client build | bundled app-server `0.154.0-alpha.6.2` |
| advertised overrides | `gpt-6-astra`, `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`, `gpt-5.5` |
| catalogue head | identical, in catalogue order |
| result | exit 0 |

Reading: the five-slot cap holds on this build and every routed row stays out
of that list, which is the behaviour plan 151 stage 3 decided to keep. Stages
1-3 and the real-machine check were recorded earlier.

Stage 5 filed the upstream report on 2026-09-17:
<https://github.com/openai/codex/issues/46087> - the override list is capped at
five rows and reads as if five were all there is, with the capture above as the
evidence and "list every eligible model, raise the cap, or say `and N more`" as
the suggestions.

## Leg F at the plan's full cap, 2026-09-17 (plan 175)

The eight children that had stopped at the 18-call cap re-ran with
`--max-live-calls 23`, the plan's per-row ceiling, same parent
`z-ai/glm-5.3-flash` and classic wire mode.

| child | exit | calls | markers |
|---|---|---|---|
| x-ai/grok-4.6 | 0, passed | 15 | 3 of 3 |
| anthropic/claude-haiku-4.5 | 0, passed | 18 | 3 of 3 |
| anthropic/claude-fable-5.1 | 0, passed | 14 | 3 of 3 |
| openai/gpt-6-astra | 0, passed | 14 | 3 of 3 |
| anthropic/claude-opus-5 | 1 | 17 | 3 of 3, canonical replay, alias emitted, three parent 503s |
| openai/gpt-5.6-sol | 1 | 23 | 3 of 3, canonical replay, alias emitted, parent 503s |
| meta/muse-spark-1.3 | 1 | 23 | 2 of 3, parent 503s |
| google/gemini-3.1-pro-preview | 1 | 23 | 0 of 3 |

Reading: four of the eight pass the harness's own exit gate, and two more
replay every marker but trip the gate on parent-side 503s - upstream noise,
not a row verdict. Leg F now has a recorded run on every routed row except
the key-blocked Qwen; these four join GLM Flash, GLM 5.3, Gemini Flash, Kimi,
DeepSeek Pro, Luna and Terra.

## Web-search leg unblocked, 2026-09-17 (plan 118, plan 175 open question 3)

The `--web-search` leg had failed at app-server startup on every attempt since
2026-09-15. The cause is client-side, not the router: `codex-cli
0.154.0-alpha.6.2` derives the `web_search` enum as `disabled`, `cached`,
`indexed`, `live`, and the probe was still sending `enabled`, so the
app-server exited before any request:

```
Error: error loading default config after config error: unknown variant
`enabled`, expected one of `disabled`, `cached`, `indexed`, `live`
```

`tools/probe_codex_runtime.py` now sends `live`, and the leg completes. Five
rows were probed with it (one search turn each, effort `low`):

| model | exit | result | serving endpoint |
|---|---|---|---|
| z-ai/glm-5.3-flash | 0 | failed: no webSearch item | DeepInfra |
| openai/gpt-5.6-luna | 0 | failed: no webSearch item | OpenAI |
| anthropic/claude-sonnet-5 | 0 | failed: no webSearch item | none reported |
| moonshotai/kimi-k3 | 0 | failed: no webSearch item | InferenceNet |
| google/gemini-3.8-flash | 0 | failed: no webSearch item | Google |

Reading: the leg runs cleanly on all five rows and every turn completed 200,
so the transport is fine; no model chose to call the search tool when asked
for a date. That closes plan 175's open question 3 as not reproduced, and it
is a model-behaviour observation rather than a roster defect - no row edit
follows. The leg keeps its own `passed`/`failed` contract for future runs.
