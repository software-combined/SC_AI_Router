# Compatibility

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
name. Sources are the official documentation and the open-source clients
listed in `AGENTS.md` section 9; re-check them before relying on the
identities below.

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
| meta/muse-spark-1.3 | text,image,audio | json_text | None | - | verified |
| meta/muse-spark-1.3-contributor | text,image,audio | json_text | None | max | verified |
| z-ai/glm-5.3-flash | text,image | native | None | - | verified |
| z-ai/glm-5.3 | text | native | None | - | verified |
| moonshotai/kimi-k3 | text,image | native | None | - | verified |
| ~x-ai/grok-latest | text,image | json_text_root | 350 | - | verified |
| qwen/qwen3.8-max-0902 | text,image | native | None | - | verified |
| ~google/gemini-flash-latest | text,image,audio | native | None | - | verified |
| ~google/gemini-pro-latest | text,image,audio | native | None | - | verified |
| openai/gpt-6-astra | text,image | native | None | - | verified |
| openai/gpt-5.6-sol | text,image | native | None | - | verified |
| openai/gpt-5.6-luna | text,image | native | None | - | verified |
| openai/gpt-5.6-terra | text,image | native | None | - | verified |
| ~anthropic/claude-sonnet-latest | text,image | native | None | - | verified |
| anthropic/claude-opus-5 | text,image | native | None | - | preview |
| anthropic/claude-fable-5.1 | text,image | native | None | - | preview |

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
