# Compatibility

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
| z-ai/glm-5.3-flash | text,image | native | None | - | verified |
| z-ai/glm-5.3 | text | native | None | - | verified |

Text-only rows (`deepseek/deepseek-v4-pro-0813`, `z-ai/glm-5.3`) and the
`drop_images` row (`x-ai/grok-4.6`) note historical images on the wire as
`[image omitted: this model runs text-only]` instead of refusing the thread
(router 0.6.56); only an image in the message being sent is still refused.

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
