# Changelog

## Unreleased

- The installer now sets `approvals_reviewer = "user"` in the managed
  Codex block in both subscription and no-subscription mode, so a fresh
  or updated install never falls back to the background reviewer. An
  owner copy of the line outside the block is removed on attach and its
  exact text is recorded in the activation receipt, so detach puts it
  back; `approval_policy` stays untouched.

## 0.6.140

- Repair and stream handling now use captured request and response facts.
  Clearing or replacing diagnostic fields cannot disable an eligible repair,
  change stream classification, or suppress the final error sent to a client.

## 0.6.139

- Align the Python package version and runtime inventory with the release.
  Their existing checks now run in the core suite so release-record drift is
  caught before beta publication.

## 0.6.138

- New model promotion now requires offline conformance and successful Codex
  and Claude Code route checks against the same source and capabilities.
  Structured evidence replaces the old scalar probe result, and a newer failed
  run supersedes an older pass. Isolated probes cap upstream attempts and
  tokens, including retries, while incomplete checks leave the model hidden.
- Wire diagnostics use the request's measured model profile. Extra input shapes
  observed on DeepSeek V4.1 Flash no longer count as verified for its whole
  model family. Image timeout advice now applies to any request carrying an
  image. Offline conformance covers every registered model and supported route,
  including hidden rows, native preservation and recovery boundaries.
- Request diagnostics retain each attempt's reported model, identity source,
  effort and transport timing, including evidence received before a failure.
  An installed read-only command shows recent request chains and filters missing,
  mismatched or contradictory model reports without making a model call.
  Client disconnects are identified from the failed response write even when
  a shortened traceback omits the socket frame.
- Agent handoff validation now retains the request's model list. A model
  refresh during a response cannot change whether an encrypted assignment
  needs a plaintext handoff. Spawn, follow-up and message delivery use the
  same captured list on both Codex tool layouts.
- External Claude requests can recover once from a temporary stream failure
  before any content or tool action. Thinking, signatures and unknown events
  prohibit replay, including empty thinking removed by compatibility repair.
  Upstream HTTP errors now use Claude's native envelope and distinguish outages,
  rate limits and credit problems. Subscription requests remain single-send.
- Claude Messages outcomes now distinguish successful completion, truncation,
  refusal and context exhaustion using the final stop reason. Missing or
  unreadable endings stay unknown. Request preparation also leaves the original
  client payload unchanged when applying external billing and tool repairs.
  Native bytes are preserved.
- Native Responses streams now retain their terminal outcome when the upstream
  omits an SSE content type. Opaque or encoded data no longer counts as answer
  text or becomes a successful model outcome at EOF. Forwarded bytes,
  subscription headers and retry permissions are unchanged.
- A completed Responses turn with `error: null` now remains successful. This
  standard no-error field previously caused a false stream failure on external
  routes and a false failure record on subscription routes. Actual error
  objects and failed completion statuses still fail.
- Native agent handoff diagnostics now distinguish the upstream tool namespace
  and encryption marker from the router's restoration and rejection decisions.
  Bounded, content-free records join the request and attempt logs, helping
  identify why an external helper did not receive its assignment.
- Opaque, malformed, or mixed encrypted native compaction history is no longer
  rewritten during an `invalid_encrypted_content` repair. The retry now only
  replaces a non-empty, structurally valid router-owned `ocx1:` summary;
  unknown native blobs are preserved and the request is left unrepaired rather
  than sent with invented readable text.
- The router records one shared outcome and bounded attempt ledger per request.
  Existing repair, replay and opt-in fallback limits are unchanged; unknown
  stream failures remain unknown and are not replayed.
- Raw upstream streams are now forwarded byte for byte, including compressed
  and incomplete final frames. Terminal observation is best effort and cannot
  delay or rewrite the client's stream; readable raw failures still record
  `failure_class` and the terminal writer.
- External Claude Messages streams now give every `tool_use` a unique
  client-visible ID. DeepSeek V4.1 Flash reused `call_0` on every tool turn,
  so Claude Code collapsed the history and the model could not see earlier
  `tool_result` content. JSON without top-level tool calls remains
  byte-identical; top-level JSON `tool_use` IDs receive the same repair.
- A missing pinned compaction-summary registry row no longer silently switches
  vendors: if another eligible row remains, summary fails closed before any
  request. No eligible summary row, or a missing or stale key/region
  availability snapshot, fails closed before Jev or any summary request, so
  flattened history cannot reach a vendor before its permitted set is known.
  Allowlist and availability filtering still decide which pinned rows are
  eligible. Jev remains global only; regional compaction uses the region-bound
  summary path instead.
- The Claude Code multi-read probe now labels served identity and rejects a
  known requested-versus-served model mismatch and requires `probe-1.txt`
  before `probe-2.txt`; it also requires exactly one matching `tool_result`
  for each rewritten `tool_use` id, rejecting stale or duplicate result ids.
  Hashed listing aliases resolve to their upstream id before comparison, and
  absent identity stays `unverified`.

## 0.6.127

- External compaction summaries now use Xiaomi MiMo V2.6 Flash first and
  DeepSeek V4.1 Flash after an unsent timeout or incomplete output. A timeout
  after dispatch fails closed to avoid duplicate side effects. The summary can
  therefore come from a different upstream vendor than the active model. Each
  attempt has a 45-second limit and the whole summary stops within 75 seconds.
  Aggregate timing logs record model, size, attempt and outcome without
  conversation text. Summary responses must echo the pinned model, and a
  registry row whose provider, upstream id or provider preferences change
  fails closed instead of silently switching vendors.

## 0.6.126

- External compaction summaries now include native tool-search calls and the
  released tool definitions they return, alongside native file edits.

## 0.6.125

- An OpenRouter Responses stream that fails transiently before any byte reaches
  the client can now be retried once, even when `response.created` or
  `response.in_progress` echoes a large request. The rule is shared across
  models. Requests that offer provider-run tools, such as web search, keep the
  provider's verdict and are not replayed.
- A model-list refresh no longer changes a request that is already in flight.
  Each request keeps the model settings it started with, including a helper
  turn's fallback to OpenRouter, and the next request uses the new list. The
  router log's start and completion records for one request share a request
  ID.
- Preparing a request no longer changes the client's own copy of it. When a
  ChatGPT helper turn such as thread titling falls back to OpenRouter, the
  fallback now starts from the original request, not one the ChatGPT attempt
  had already rewritten, so a turn offering agent tools is no longer refused
  with a plaintext collaboration namespace error. When an oversized turn has to shorten old tool outputs or drop old
  images to fit the size limit, only the request sent upstream is shortened.
- A request can now be up to 96 MiB, sent or decompressed, on every route,
  instead of being refused at 16 MiB. This is a resource limit on this
  machine, not a promise that ChatGPT, Claude or OpenRouter accepts a request
  that size. Long native threads with images are forwarded whole. One request
  over 16 MiB is served at a time, to the end of its answer; another arriving
  meanwhile is asked to retry shortly, and smaller requests carry on. A
  compressed request to an external Claude-format model is now sent
  decompressed, so its headers match its body.

## 0.6.124

- Model-switch and context-reset markers are found even if the client moves
  them to another text block or the system role.
- Responses requests the router prepares are now checked against the
  upstream rules learnt from earlier refusals, and a broken rule leaves one
  `wire_contract` log line of rule names and counts. The check only observes:
  it never changes or blocks a request. Provider refusal lines carry the same
  rule counts and whether the thread switched model, a compressed
  subscription request now gets its refusal shape logged too, an item type
  that is not a plain name is logged as `unknown` so free text cannot reach
  the log, and an item with a role but no type counts as a `message`.
- MiMo V2.6 Pro threads now compact at about 400,000 tokens, before Xiaomi's
  endpoint starts failing long requests. With Jev compaction on, a row's
  compaction limit also caps the retained history, so a Jev result does not
  trigger a second compaction straight away.

## 0.6.123

- The update dialog now lists each new model once. Models a dialog has shown
  are marked seen, so later updates no longer repeat them, and an update or
  check with no new model stays silent instead of showing a restart dialog.

## 0.6.122

- A subscription turn whose history replays the router's own compaction
  summary now sends it as readable text on the first attempt, instead of
  failing once and retrying. A turn that also carried a native encrypted child
  reply no longer fails.
- External compaction summaries now keep native `apply_patch` file edits
  instead of dropping them.
- Provider refusal log lines now also record the request's top-level field
  names, reasoning item shapes and any broken tool call/output pairing, as
  names and counts only, never content.

## 0.6.121

- Keep custom-tool history paired when a thread changes model. Declared custom
  and function tools now convert to matched function-call items, while an
  undeclared custom pair stays as matched custom items instead of producing a
  mixed call/output shape that strict providers reject.
- Normalize subscription replay for threads that switched model. Reasoning
  from before the switch is dropped, or replays as a visible note when it has
  a readable summary; fully readable agent messages from external peers become
  matched tool results; and V2 compaction triggers continue to the
  subscription provider. Turns without a model switch, native encrypted
  replies and app-delivered outputs are forwarded unchanged.

## 0.6.120

- Update and new-model notices now show only the native restart dialog. The
  updater no longer opens an approval page in the browser or sends a second
  desktop notification; an unavailable dialog stays pending for a later run.
- A subscription Responses request rejected with `invalid_encrypted_content`
  whose history replays the router's own compaction summary item now gets one
  bounded retry after that item is rewritten as readable text. The replayed
  reasoning-blob repair is unchanged, and a payload carrying an encrypted
  field outside those two shapes is left alone rather than retried.

## 0.6.119

- Fix combined Codex model discovery rejecting valid OpenAI visibility and
  upgrade metadata. Subscription models still come from the server and appear
  alongside approved third-party models; no static catalogue override is needed.

## 0.6.118

- The Anthropic picker now uses `anthropic/claude-opus-5.5` in place of
  `anthropic/claude-opus-5`. The superseded id is retired so stale
  catalogues cannot restore it. Opus 5.5 keeps the existing freeform patch
  capability and passed the bounded tool, stream, image, compaction and patch
  probes.

## 0.6.117

- ChatGPT subscription models are now discovered from Codex's native
  `/models` catalogue and appear without a repository roster edit. Codex
  drives refreshes; `--static-catalogue` remains the rollback path.
- A successful live refresh is authoritative for subscription availability:
  new server models appear, omitted models disappear and saved choices keep
  their relative order. Native metadata is validated before caching, and the
  stale fallback is scoped to the same account, workspace and client version.
  Request routing uses that same identity scope, and an authentication
  rejection never serves stale model data.
- The ChatGPT picker now offers `GPT-6-Sol` and `GPT-6-Luna` in place of
  their 5.6 versions. An update replaces the old ids inside existing custom
  rosters without adding or reordering unrelated choices.
- Codex helper-title turns still using `gpt-5.6-luna` route through the new
  Luna 6 OpenRouter twin when the helper fallback is enabled.
- Both OpenRouter twins are enabled. Sol 6 passed its tool, stream and
  compaction legs; its image-quality assertion is deferred by owner approval
  after it returned `Teal` for the red test image.

## 0.6.116

- An `invalid_encrypted_content` retry that finds no removable reasoning blob
  now logs structural repair diagnostics, making `outcome=unchanged`
  distinguishable without recording request content or encrypted values.
- Release tags now use the full semantic form `v<VERSION>`, matching
  `packaging/VERSION` exactly. Optional `-beta` and `-express` suffixes remain.

## 0.6.115

- A child-to-parent `agent_message` carrying readable text and an encrypted
  sidecar is now delivered to an external model as a `delivered_message` tool
  result. The router forwards the readable text, withholds the encrypted block
  and marks the result incomplete so the recipient can request a plain-text
  resend. Recovery requires non-empty readable text and a non-empty sidecar;
  opaque assignments, self/peer messages and malformed messages remain
  fail-closed.

## 0.6.114

- A subscription Responses request rejected with `invalid_encrypted_content`
  now gets one bounded retry after the router removes OpenAI-owned reasoning
  blobs from `input`. Healthy requests and approval decisions are unchanged.

## 0.6.113

- Release tags now use the short `vX.XX` form, derived from the release
  counter in `packaging/VERSION`: `0.6.113` is tagged `v1.13`. Beta and
  Express suffixes still identify the channel and urgency, while the semantic
  build version remains unchanged for updater ordering.

## 0.6.112

- A router update keeps the release's effort list. An older feed can no
  longer shrink or widen it on restart, which is what made MiMo refuse
  `xhigh` with "use one of none" after the picker already offered it.
- An update restores the ChatGPT picker when the saved roster is empty.
  A non-empty custom list is left alone.

## 0.6.111

- Both Xiaomi MiMo rows offer the effort list Xiaomi documents (`none`,
  `minimal`, `low`, `medium`, `high`, `xhigh`), default `none`. OpenRouter
  advertises no names, so the picker had been showing a single Medium
  control with nothing to choose.

## 0.6.110

- The update notice lists new models as bullets, one picker label per line,
  instead of joining them into one sentence.
- Quit and reopen on macOS waits until Codex has quit, for up to five
  seconds, before opening it again. The button relaunches the app instead
  of only quitting it, and a quit that never finishes still opens it.
- The Xiaomi picker labels read `Xiaomi: MiMo V2.6 Flash` and
  `Xiaomi: MiMo V2.6 Pro`, matching the other rows. A live refresh keeps
  that spacing instead of putting the upstream hyphens back. Both still
  offer only `none`, so there is no effort menu to open.

## 0.6.109

- Claude Code attached to the router defers MCP tool definitions instead of
  sending every schema on every turn. Claude Code turns deferred loading off
  for a base URL that is not Anthropic's own host, so the installer owns two
  more `env` settings, `ENABLE_TOOL_SEARCH=true` and
  `_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL=1`, restores them on detach, and
  refuses to attach while `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS` is set
  anywhere in reach: that switch forces the feature off and no value
  overrides it. Measured on Claude Code `2.1.223` with 700 synthetic MCP
  tools, the first request of a session carries 727 tool definitions and
  271 KB without deferral, and 11 definitions and 100 KB with it.
- The external Messages route rewrites that shape, because OpenRouter
  implements none of Anthropic's deferred-tool protocol: the
  `DeferredToolPlaceholder` and a server-side search tool entry go, the
  `defer_loading` flag goes (the released definition already rides in the
  same request's tool list, so the model keeps the tool), and a
  `tool_reference` content block becomes the text naming the tool it stood
  for, which keeps every `tool_use` and `tool_result` paired. The
  subscription route stays byte-identical. A live probe on
  `z-ai/glm-5.3-flash` completed the deferred round trip in three turns with
  a 700-tool catalogue, and the control against the installed release passed
  too: OpenRouter currently tolerates the raw shape, so this is hardening
  rather than a repair of a live failure, and no routed turn depends on that
  tolerance any more.
- `tools/capture_claude_shapes.py` captures what Claude Code actually sends
  against a local sink: no model call, no billing and no credential read,
  across the deferral flag, the first-party assumption and the hard switch.
  `tools/probe_claude_code.py` gained `--deferred` (a synthetic 700-tool MCP
  server, one search round trip) and `--candidate` (an isolated router from
  the working tree), and `--doctor` now fails the Claude row, naming the
  file, when the hard switch is set.

## 0.6.108

- Two Xiaomi MiMo 2.6 rows join the picker: `xiaomi/mimo-v2.6-pro` and
  `xiaomi/mimo-v2.6-flash`, verified by hand because the probe harness bills
  its round trip at `low` and these rows accept only `none`. Both were
  served solely by the first-party Xiaomi endpoint, which the account's
  org-level Allowed Providers list did not include, so no key could reach
  them and the picker had nothing to offer. Allowing that provider also
  restored `qwen/qwen3.8-max-0902`, hidden for the same single-endpoint
  reason.

## 0.6.107

- A pinned row survives a model cache written by an older release. The
  hourly model refresh keeps a cache of the last roster it fetched, and the
  boot path applied that cache whole: after the roster moved to Grok 4.7,
  a cache from the 4.6 era put the retired id back and hid the new one, so
  the picker offered Grok 4.6 while the router only served 4.7 and every
  request was refused as unavailable. Both the boot cache and the hourly
  payload now overlay the bundled roster instead of replacing it: they may
  update the rows the bundle knows and add rows the bundle has never seen,
  but neither restores a retired slug nor drops a pinned one.
- The new-model prompt can name a row the cache was hiding. The dialog asks
  the running router which picker rows are new; while the stale cache
  supplied the roster, that answer was empty and the sentence fell back to
  its version-only shape. With the bundle authoritative the answer names
  the added rows again, so an update that adds a model says which one.

## 0.6.106

- The picker pins Grok 4.7. Upstream moved while the roster pinned 4.6, and
  the router does not follow upstream movement on its own, so the pinned id
  was replaced and `x-ai/grok-4.6` joined `RETIRED_SLUGS`: an upgrade drops
  the superseded pin instead of offering it beside the new one. The new row
  keeps the family's adapter quirks (`json_text_root` tool schemas, the
  350-tool ceiling, and text-only image turns) and was proved rather than
  inherited, with an isolated-router round trip on tool, stream and
  compaction. Image turns were re-tested with the quirk cleared and the
  upstream still refuses them, so the text-only treatment stays.
- A `drop_images` row no longer implies an image probe leg. The media leg
  asserts the model saw the attached image, so a row that replaces images
  with a note by design could never pass it, which left the documented probe
  path unusable for that shape. The row's other legs are unchanged.

## 0.6.105

- `--desktop` finds the Claude desktop app on every platform it ships for,
  instead of only on macOS. The third-party profile was resolved as
  `~/Library/Application Support/Claude-3p` unconditionally, so on Windows and
  Linux the installer looked in a directory that does not exist there and
  attaching the desktop app silently did nothing. The profile now resolves the
  way the app's Electron build does: Application Support on macOS, the roaming
  AppData directory on Windows, and `XDG_CONFIG_HOME` with a `~/.config`
  fallback on Linux. `CLAUDE_USER_DATA_DIR` still overrides all three.
- Switch Claude is still macOS-only. Its dialog, app restart and shortcut are
  built against macOS, so the desktop app on Windows and Linux can be attached
  but not switched from the shortcut yet.

## 0.6.104

- The README beside the router home is now the one that belongs to the
  installed release. A host that kept whatever page its first install wrote
  went on describing a router it no longer ran: the copy on this machine still
  said "only the six configured OpenRouter models" and never mentioned Claude
  Code or the client chooser, so anyone reading their own install was pointed
  at a product two months old. The home files step now refreshes it from the
  release on every install, update and rollback, so the page tracks the release
  being applied instead of whatever the first install wrote. A failed health
  check restores the previous release and leaves the newer page in place until
  the next successful install or update, and a release that predates the
  bundled page leaves the existing copy alone: this page is documentation, and
  it never fails an install or a rollback.

- `tools/probe_claude_code.py` accepts a row whose answer contains the
  synthetic marker rather than only one that is exactly the marker. Some rows
  narrate the file they read, and the strict comparison reported
  `google/gemini-3.1-pro-preview` as a failure on a working turn. An empty or
  refused turn still fails, and the acceptance rule now has an offline test.

## 0.6.103

- Claude Code can finish a turn on every routed model it is offered. Two
  shapes the client cannot survive are now repaired on the external Messages
  route, and only there. The `system` block carrying the client's own
  `x-anthropic-billing-header` line is dropped, because it made
  `anthropic/claude-fable-5.1` refuse every turn with HTTP 400 before the
  model was ever reached; the line only matters to Anthropic's billing, which
  this route does not use. A thinking block that arrives with a signature but
  no thinking is dropped from the stream, because
  `google/gemini-3.8-flash` returns one after a tool result and Claude Code
  discarded the whole reply as a result, showing an empty answer. A live sweep
  of Claude Code `2.1.223` through the router now completes a Read-tool round
  trip on 18 of 18 advertised rows, up from 16, and the subscription route is
  untouched. `tools/probe_claude_code.py` reproduces the sweep on demand.

## 0.6.102

- `--setup` repairs a host whose activation receipt is unreadable again. The
  chooser's "already attached" check read the receipt eagerly and crashed on
  corrupt JSON before the repair path could run; that check now reads it
  tolerantly, treating a receipt it cannot parse or open as attached, so the
  repair runs and the chooser never prompts on top of state it cannot read.
- The existing-beta instructions show `--channel=beta` for the bootstrap
  chooser command, since the chooser ships on the beta channel.

## 0.6.101

- The installer asks which assistant and where it is used (ChatGPT, the Claude
  desktop app, Claude Code in the terminal, or both Claude surfaces) and
  attaches only that. `--choose-clients` asks again on a machine that is
  already attached, `--clients none --desktop` is the desktop app alone, and
  attaching never detaches a client the answer did not name. Cancelling either
  question attaches nothing and detaches nothing, and the distributed
  bootstrap forwards `--choose-clients` so an installed host can reach it.
- An explicit `--clients claude`, `--clients both` or `--clients codex` now
  attaches on a machine that is already on the current version. It used to
  print `up to date` and stop before the client stage, so the request silently
  did nothing until the next release.

## 0.6.100

- Claude desktop setup on macOS installs **Switch Claude**, a shortcut for
  switching between your Claude subscription and OpenRouter without signing
  out. Each profile keeps its conversations. Setup and router updates preserve
  your selection and refresh the shortcut automatically.

## 0.6.99

- Claude desktop shows the full approved OpenRouter roster again. Stable
  router IDs avoid the app's model-name filter while the picker keeps each
  real vendor, model and billing label. Existing session IDs still route.
- Desktop attachment now works when the router is already up to date and
  creates its configuration on first use, without a manual Developer-menu setup.

## 0.6.98

- Muse Spark 1.3 and Contributor no longer receive Codex's ChatGPT-specific
  `access_programs` field. A controlled comparison of a failing desktop request
  isolated that field as the trigger for Meta's unnamed 400 response. The
  OpenAI subscription route retains it; model, effort and tools are unchanged.
- Annotation retries now report eligibility, dispatch and the actual outcome
  through content-free events. A failed retry follows the normal authentication,
  credit, context and validation error handling instead of hiding behind the
  original rejection.

## 0.6.97

- When an OpenRouter Responses turn is rejected without a named cause, the
  router retries once with annotation-only
  request fields (prompt cache options, client metadata, store, user and
  similar) removed before treating the turn as refused. A refusal the router
  cannot attribute is no longer described to the client as a model refusal.
  This retry did not resolve every Muse first-turn rejection; see 0.6.98.

## 0.6.96

- Linux on arm64 is a first-class install target: the runtime lock now
  pins the aarch64/glibc CPython build, so a Graviton host bootstraps
  natively instead of being carried on x86_64. The bootstrap also verifies
  archives with GNU `sha256sum` when a host has no `shasum`.
- A compressed turn past the request cap is read and decided on its decoded
  size instead of being refused as malformed. The 2026-09-18 thread
  (01a0b155) carried ten attached images that compressed to 17.6 MB, and the
  declared-size gate answered `INVALID_REQUEST_SIZE` before the body was
  read: the person saw "Invalid request size" with no remedy, the trim that
  could have served the turn never ran, and the log recorded a framing error
  for a turn that was merely large. A zstd body is now read up to the decode
  ceiling and takes the single oversized-read slot before that read, so one
  oversized body is still the most in memory; the slot taker is idempotent
  because the declared size and the decoded size both ask. A turn that still
  does not fit answers `BODY_TOO_LARGE`, whose message and docs name the
  remedy. Identity bodies keep today's answer: without zstd a declared size
  past the ordinary cap is still a framing error.

## 0.6.95

- Wide compactions now fit the request instead of refusing it. A real
  window carries hundreds of items, and the state budget only shrank each
  item, never the number of them, so 59 of 60 measured 600-item windows
  declined before asking anything. After the per-item ladder the state now
  keeps the newest 64 retained entries at 500 characters, then 32 at 120,
  then 16 at 60, and records how many older entries it left out. A 20-window
  replay at the same size: 17 of 20 now reach Jev, median request 7 KiB, and
  the three that do not simply have no eligible pair. Thinning is not
  one-way safe, so both questions name the omitted count and forbid
  inferring coverage from absence.
- Jev compaction now reads its own questions correctly. Both are positive
  propositions ("the facts are already covered", "knowing the call still
  matters"), but the rule compared each against the threshold backwards and
  dropped precisely the pairs the judge had called *uncovered*; at the
  shipped 0.90 with measured scores topping out at 0.83 that deleted every
  judged pair. A pair is now dropped only when its facts count as covered
  and the call no longer matters.
- Jev compaction no longer declines the whole window because a tool output
  has no call left to pair with. Pairing is local: only complete, ordered,
  unpinned pairs become candidates, a duplicated call id protects every item
  sharing it, and anything unpairable stays verbatim. Replaying 60 archived
  threads showed the old global rule refused 40 of them for an unmatched
  output, protecting nothing while leaving the feature inert; no window is
  refused for closure now. `docs/jev-compaction-benchmark.md` records the
  measurements, the score distribution and why the threshold stays
  conservative.

## 0.6.94

- Experimental Jev compaction is opt-in through the `jev-compaction` home
  file. Start with `shadow` to measure without changing today's summary;
  `on` returns retained evidence inside the existing V1/V2 envelopes.
  Both enabled modes send selected history text to TypeSafe and are billed.
  Complete tool pairs and pinned history are protected, invalid decisions
  and size overruns use the existing summarizer, and subscription threads
  are unchanged.

## 0.6.93

- The restart dialog after an update names the models that update added,
  using the same picker labels the desktop notification and the approval
  page show. A dialog that cannot reach the running router keeps its
  version-only sentence, nothing outside the machine's policy is announced,
  and the approval page no longer repeats a raw model id beside each name.

## 0.6.91

- A fresh Codex install starts on DeepSeek V4.1 Flash at Max thinking. The
  attachment seeds `model` and `model_reasoning_effort` inside the managed
  block; Codex writes the owner's later pick into those same lines and an
  update carries it forward, so the seed never resets a choice or adds a
  second `model` key. Carried lines now stay root keys in `none` mode too,
  instead of landing inside the provider table the block declares.
- The attachment also manages two Codex desktop preferences in the config's
  `[desktop]` table: follow-up messages steer the running turn instead of
  queueing, and the effort list offers Max without Ultra. Both are re-applied
  by an update and put back as they were on detach; a value the owner changed
  after the install is left alone. A `[desktop]` table or value the installer
  cannot rewrite safely skips the edit with one line of output rather than
  risk a second definition or a mangled value.
- Ultra is no longer served. It is Codex's automatic-delegation level, so
  `gpt-6-astra`, `gpt-5.6-sol` and `gpt-5.6-terra` now advertise `low` to
  `max`, and the next merge strips Ultra from a row an older release wrote.

## 0.6.90

- A ChatGPT helper turn that carries tools is answered from its OpenRouter
  twin again. Client 0.154 puts the read-only app tool allowlist it derives
  from the installed apps and MCP servers on the title, description and
  summary helper turns, and the fallback refused every tool-bearing turn, so
  an exhausted allowance left titles as slices of the prompt. The twin
  answers the client's own payload, tools included.

## 0.6.89

- The subscription picker gate is gone. A ChatGPT subscription row is always
  listed, exhausted or not, and its OpenRouter twin (`openai/<slug>`, labelled
  `· OpenRouter`) is listed beside it, so the paid route is chosen on purpose
  rather than swapped in under the subscription row's name. An exhausted row
  answers the refusal message that names the model and points at a routed row.
- Removed with the gate: its state document, the usage and refusal evidence
  reader, the four-hourly recheck (`subscription_probe` in router state is now
  ignored), and the `subscription_gate_changed` and `subscription_probe`
  events. The helper-turn OpenRouter fallback and the install-time
  no-subscription default stay. The next install re-merges `mixed-models.json`,
  so the rows come back without further steps.

## 0.6.88

- A routed Codex turn that carries tools now reports the weight of the
  history the thread actually carries, so the client compacts before a thread
  outgrows the request budget. The completed frame's `input_tokens` is raised - never
  lowered - to `bytes / 5.8` for text plus the flat image allowance, clamped
  to the row's context window, and `total_tokens` follows. Provider detail
  fields are untouched, the helper twin and subscription passthrough keep the
  provider's own usage - as do tool-free responses, which keep their verbatim
  forwarding - and one `usage_reported` line records the change.
  Without this the slim the router performs is invisible upstream: the
  2026-09-16 thread carried 67 MB while upstream was billed about 1 MB, so
  Codex never reached 90% of the window and never compacted.

The first beta tag for this change set, `v0.6.87-beta`, failed its native
installer checks before anything was published (`ai_router/turn_budget.py` was
missing from `docs/runtime-files.md`); tags are immutable, so the version
rolled forward.

## 0.6.86

- A routed turn that is over the 16 MiB prepared budget is now reduced with
  visible notes instead of being refused outright. Repeated released-tool
  listings collapse to the newest copy per tool (the 2026-09-16 thread
  carried the same three namespaces 2,690 times), the oldest images past the
  newest four become a note, and long old tool outputs are truncated head and
  tail. Tool call/output pairing and the newest items are never touched, and
  a turn with nothing reducible left still answers today's 400.
- One `turn_trimmed` line records what each trim replaced, by count and byte
  weight. No content is logged.

## 0.6.85

- A search-heavy Codex thread no longer dies at the request-size gate. The
  zstd decode ceiling that exists so prepare can slim released-tool schemas
  now reaches six times the request cap (96 MiB decoded; the compressed body
  is still capped at 16 MiB), so a 67 MB thread like the 2026-09-16 one
  (2,690 tool-search results, about 1 MB prepared) is prepared instead of
  refused.
- One oversized body is expanded and prepared at a time. The slot is taken on
  decoded bytes, the moment a turn passes the 16 MiB cap, so a second one -
  including parallel sub-agents replaying the same large history - gets one
  retryable 503 `OVERSIZE_BUSY` until the slot frees. A body inside the
  ordinary cap never touches the slot.
- A refused turn logs one `turn_refused` line naming its sizes and what the
  turn carried, by class and byte weight (released-tool results, tool
  outputs, reasoning, messages, images). No content is logged, and the
  client-visible message is unchanged.

## 0.6.84

- Error messages are plain language, and the technical reason rides the log
  line instead. A provider's status, code, provider name, offending tool and
  field, the wait time, and a credential failure's OS reason no longer appear
  in the sentence Codex or Claude shows; `ai_router/errors.py` remains the one
  catalogue. Statuses, `error.code`, `Retry-After` and every frame shape are
  unchanged.
- Every refusal now leaves one `request_rejected` line, including the
  retryable 503s (draining, busy, refused subscription turn, unavailable
  provider) that used to answer with no log line at all. Credential detail is
  logged as a bounded, path-redacted `detail`, and `upstream_rejected` carries
  the bounded name of the tool the provider refused.
- Logs age out. A file under `logs/` is deleted 30 days after its last write,
  at every router start and every scheduled update, so a machine that has been
  updating for years keeps no pile. The three files a running router writes
  (`router.jsonl`, `launchd.log`, `update.log`) are never removed by age and
  keep their existing size caps.
- Path redaction moved to `ai_router/redaction.py`, a leaf, so the message
  catalogue stays inside its recorded size ceiling. `errors.redact` still
  works for existing callers.

## 0.6.83

- The Codex picker no longer keeps a ChatGPT subscription model that cannot
  run. The router reads the allowance evidence its own turns already carry -
  the usage headers when upstream sends them, a refused turn, or an auth
  refusal - and drops that slug from `mixed-models.json` until a turn
  succeeds, its reported window resets, or the hour long bound expires. Only
  the refused slug moves, and only when the install's own roster names it: a
  bucket that still works (for example `gpt-5.3-codex-spark`) stays
  selectable.
- The OpenRouter twin of a subscription model (`openai/<slug>`) now takes
  the hidden row's place instead of listing beside it, so the same model
  never appears twice: the twin shows while the subscription row cannot
  run, and hides again once it works. An install with no subscription at
  all keeps listing the twins exactly as before.
- While a slug is blocked, the router rechecks it against the subscription
  upstream once every four hours - one bounded request, using the login the
  client last presented, held in memory only, never written to disk and
  never logged - so a replenished allowance brings its rows back without
  waiting for a turn. `subscription_probe: false` in router state disables
  the recheck. Every change is silent and logs one `subscription_gate_changed`
  event, and every recheck that reaches upstream logs one `subscription_probe`
  event.
- A fresh install on a client with no ChatGPT login now defaults to
  `--openai-mode none` by reading the presence of a Codex `tokens` block (no
  token value is ever read or logged), so the picker never offers rows that
  cannot run. An explicit flag or the stored mode still wins, and an
  unreadable store keeps the old default.

## 0.6.82

No change to what a running router does: this release carries the publish
alert's failure handling and the probe tooling that landed after 0.6.81.

- A feed publish alert that cannot be delivered is no longer silent. A failed
  delivery is kept in a dead-letter queue, and an alarm on the rule mails the
  operator through the same topic, so a formatter failure reaches a person
  instead of only a log line. The bundle mail itself is unchanged.
- The capability probe's web-search leg runs again. The client renamed the
  config value it reads for search, and the probe was still sending the old
  one, which stopped the probe's client from starting at all; it sends the
  client's live-search value now. Probe tooling only.
- Documentation and hygiene riding the same release: the probe matrix and the
  filed upstream report are recorded in `docs/compatibility.md`, and
  `.gitignore` now keeps per-install router state, logs and local artefacts
  out of a checkout.

## 0.6.81

- On Windows, task registration now recovers when a stale Task Scheduler task
  belongs to a different principal. A local-account install is "Access is
  denied" to the same person's domain token (and the reverse), which left
  auto-update parked and re-installs failing with `Access is denied`; a failed
  `schtasks /create /f` now deletes the stale task and re-creates it under the
  current account. A first, clean install is untouched.
- Fifteen routed models now offer the client's freeform `apply_patch` tool,
  where the row previously advertised no patch override: a live probe applied
  a synthetic edit and read it back on each of them. The two Meta rows and the
  xAI row keep the old state - Meta's upstream drops a turn carrying the tool,
  and xAI's model never calls it. Reasoning summaries, the experimental
  `clock` tool and the pinned-endpoint setting stay off everywhere they were
  probed.
- New models that arrive through the hourly model refresh are now offered
  with the restart prompt on the next update check, not only when a new
  version is installed.
- Stream log lines name a fourth fact, `unattributed_delta_bytes`: the
  forwarded bytes that are neither the model's answer nor item-shaped
  reasoning. A turn that dies mid-stream can now be explained from its log
  line alone. Reasoning a provider streams as text rather than as an item
  (`response.reasoning_text.*`) counts as reasoning instead of landing in that
  residue; a 2026-09-16 capture found that shape on
  `deepseek/deepseek-v4.1-flash`.
- A managed install, one whose state sets `policy_enforced`, now denies
  external routing when its model policy is missing or unreadable instead of
  allowing every model. A personal install is unchanged.
- A managed install now lists only the models it is allowed to route, on the
  Claude model listing as well as the picker. A personal install is
  unchanged.
- The first-run key window reads the provider's own name instead of a
  hardcoded one, so a second external provider cannot be labelled OpenRouter.

## 0.6.75

- A turn a subscription route refused now answers with the model, the
  subscription that refused it and the next step - retry shortly, or select
  a routed model - instead of the bare "Upstream rate limited". The status,
  the code and `Retry-After` are unchanged, and an external provider's
  transient 429 keeps the neutral wording. The message comes from the
  provider's own definition, so a new provider supplies its own login label.
- `pyproject.toml` moves back in step with `packaging/VERSION`, which the
  version-match test had been failing on since 0.6.73.
- The picker file no longer carries a model roster that grows with the
  visible rows: past forty ids the instruction text lists that many and
  points at the router's own model listing, and subscription rows are served
  their own wording instead of being told they run a routed model. For the
  current 27-row roster that takes the merged file from about 630 KB to
  485 KB, and
  `catalogue --merge` now reports its row count and size.
- The Windows key window lays its controls out. WinForms gives a control
  added straight to a form the corner (0, 0), so the key box and both
  buttons were stacked behind the icon and prompt and the key could not be
  typed or submitted; every control now sits in a top-down panel. Its combo
  boxes also use the enum name instead of an invalid ordinal.
- The feed publishers require `--bucket` and the release workflow reads the
  feed bucket, publisher role and signing-seed ARN from repository settings
  instead of carrying them in the tree, so the stack template and the release
  path no longer publish an AWS account id. A fork that runs a publisher with
  no arguments now fails instead of targeting our bucket.
- The feed publisher role writes only what a release publishes --
  `bundles/*` and the two channel documents -- and an explicit deny refuses a
  delete or any change to the bucket's own configuration. Bundle uploads are
  create-only, so S3 itself refuses a second write of a published key, and an
  email reports every bundle write so a replacement that skips the flag is
  visible.

## 0.6.74

- A model refused because it needs a subscription now says to select a routed
  model instead, without naming a provider. Failure describing, the key check
  and the context frame now follow the provider's own definition, so a second
  provider is one table entry rather than a name compare.

## 0.6.73

- Update notices, the picker baseline and the model catalogue are written
  through the same atomic writer as the rest of the router, so on Windows a
  destination that is read-only or briefly locked is retried instead of
  dropping the write.

## 0.6.72

- A feed document without a bundle checksum is refused instead of
  installing an unverified tarball, and feed, bundle and key-check fetches
  never follow a redirect off the trusted origin.

## 0.6.71

- An oversized compact now summarizes instead of refusing: V1
  `/responses/compact` and inline V2 triggers decode up to the existing
  64 MiB zstd ceiling before the local summarizer runs, which still sends
  only a bounded transcript upstream. Past that ceiling the turn keeps
  today's 400 `BODY_TOO_LARGE`.

## 0.6.70

- The router no longer holds the request body and its parsed form for the
  duration of a streamed turn: the relay now runs after the request frame
  returns, so both buffers die before the stream starts.

- Rename the product and GitHub repository to SC AI Router
  (`software-combined/SC_AI_Router`). Active documentation, release metadata,
  feed trust references and plugin marketplace sources now use the new name;
  the previous GitHub URL remains accepted during the redirect transition.

## 0.6.69

- Upstream reads are bounded the way request bodies are: SSE adapters parse
  bounded line pieces, whole-body reads are capped at 16 MiB (1 MiB for
  error envelopes), and an over-cap upstream ends the turn 502 instead of
  growing the router without bound.

## 0.6.68

- Codex sessions now get a full-lane spawn hint: if spawn is refused
  because every subagent lane is taken, close finished agents (or all
  of them if needed) and retry. The same sentence is appended once to
  `spawn_agent` and `close_agent`. Claude Code does not receive it,
  and neither client gets an annotated spawn-error output.
- A deeply nested request body now ends the turn with a 400 instead of
  dropping the loopback connection, and drain admission is decided under
  one lock so a drain landing mid-admission still refuses cleanly.
- The installer hands the setup URL to the key window on stdin instead of
  the command line, so it never appears in `ps` output on a shared machine.

## 0.6.67

- An image sent to a model that cannot read images no longer ends the
  turn. The image is replaced with a note that tells the model to say
  so in the conversation, and the turn continues.
- Stream log lines name two more facts: `max_output_tokens`, the output
  cap this request sent upstream (the twin row's own cap after a helper
  fallback), and `reasoning_delta_bytes`, how much of the forwarded stream
  arrived as reasoning output items rather than answer. The cap is exact;
  the reasoning count covers item-shaped reasoning only.

## 0.6.66

- Codex deferred-tool search now tells the model to call the exact
  returned name once, and to stop searching if the tool is missing.
- Native installer CI jobs run only on pull requests into `main`;
  develop PRs keep the cheap Ubuntu check. Develop `v*` tags still
  publish through the release workflow.

## 0.6.65

- An OpenRouter turn refused for funds now ends at once with a key
  credit message naming the model and pointing to IT for a topped-up
  key, instead of a generic upstream rejection. The 429 rate-limit
  path is unchanged.

## 0.6.64

- Plan 175 paid probe matrix sessions 3 to 6: per-model legs A-G recorded
  for GLM 5.3, DeepSeek Pro, Gemini Pro, Grok, the four Anthropic rows and
  the four GPT twins, with serving endpoints. Parallel-call serialization
  confirmed as an eight-vendor harness/client confound; image colour misses
  are vendor behaviour. No roster row edits proposed.

## 0.6.63

- A long Codex turn that is only oversized because it repeats full
  `tool_search` schemas is decoded far enough for prepare to slim those
  items, then refused only if the prepared upstream body is still over
  16 MiB. Uncompressed requests stay capped at 16 MiB; zstd may expand
  at most four times that far.

## 0.6.62

- Feed signature enforcement is live: the compiled `FEED_PUBLIC_KEY` is
  set, the release workflow reads the signing seed from Secrets Manager,
  and the live `scg-router-feed` stack now publishes from
  `software-combined/SC_Unlimited_ai` with GetSecretValue limited to that
  one seed ARN. Unsigned HTTPS feeds fail closed.

## 0.6.61

- Feed documents are signature-enforced end to end (Plan 145): the
  publisher signs the exact served bytes, the updater verifies the
  detached sidecar before parsing and refuses unsigned or tampered feeds
  with the `feed_signature` code, and the publisher role may read exactly
  one secret, the signing seed. `file://` manual installs stay
  operator-trusted.

## 0.6.60

- The router installation carries the key-filtered picker re-merge (PR
  #133): every availability refresh re-merges `mixed-models.json`, so a
  dashboard-blocked row such as Qwen leaves the picker within one refresh
  cycle. Includes the 131 residual ownership split and the 099 Step 3
  `models_url` wiring from the feed origin.

## 0.6.59

- Dashboard-blocked models no longer linger in the picker file: every
  key-availability refresh now re-merges it, so a row the key cannot use
  is removed within one refresh cycle (Codex shows the change after
  reopening). Request routing already refused such rows; now the picker
  agrees with it.

## 0.6.58

- The picker, request routing, Claude discovery and the new-model prompt now
  honor what the installed key may use: each router refreshes
  `GET /api/v1/models/user` with its ordinary inference key at startup,
  every five minutes and after a key or region change, and shows the
  intersection of the approved roster, the key snapshot, local policy and
  client rules. Temporary failures keep the last good snapshot for the same
  key and region; authentication rejection clears it. Subscription rows are
  unaffected. Regional endpoint profiles (`global`, `us`, `eu`) live in
  `provider_defs.py`; the per-machine `openrouter_region` state selects the
  inference and key-filtered discovery host, and those requests never fall
  back outside it (credential verification still uses the global host). No workspace
  names, provider allowlists, budgets or guardrail IDs are stored in the
  router: those remain OpenRouter dashboard controls.

## 0.6.57

- Both GLM rows now carry the documented `max_tools: 128` ceiling (Z.ai
  allows at most 128 functions per request), so oversized tool lists degrade
  gracefully instead of failing upstream.

## 0.6.56

- Switching to a text-only model no longer refuses a thread that carried
  images: historical images are noted on the wire as
  `[image omitted: this model runs text-only]`, the same treatment the Grok
  row already had. Only an image in the message being sent is still refused
  with an actionable message.

## 0.6.55

- Registry rows can now carry an optional `provider_prefs` object that
  reaches the OpenRouter wire body as `provider`, so a future data edit can
  steer a row away from a strict or flaky endpoint. No row sets it yet;
  pins wait for plan 175's probe evidence and owner approval.

## 0.6.54

- Delivered cross-thread messages are now named `delivered_message` and
  `delivered_app_message` instead of tool-sounding names, so a model that
  copies a name it saw gets a hint pointing at the answer box instead of an
  `unsupported call` dead end; a readable alias with a dropped character
  (within two edits) now repairs onto its tool, while an ambiguous near
  miss is still left to the client.

## 0.6.53

- Every OpenRouter Responses request now sends `X-OpenRouter-Metadata:
  enabled` from the provider definition table (the Messages ingress stays
  byte-identical), and the router logs the serving endpoint
  as bounded `serving_endpoint` on `upstream_rejected`,
  `upstream_unavailable`, `request_completed` and `request_failed`, so a
  refused or flaky turn names the backend that answered it.

## 0.6.52

- ChatGPT native service paths are now a prefix rule instead of a four-entry
  list: any path under `/alpha/` or starting with `/guardian` forwards to
  the ChatGPT backend with the client's own login in subscription mode
  (Codex's checkpoint notes and read-only history tools work through the
  router) and answers 404 in `none` mode. Dot segments, percent-encoded
  dots and backslashes are refused before the prefix test. The context
  recovery guidance now tells models to search the tool list for the
  history tools instead of calling remembered names.

## 0.6.51

- Carried history now stops at the model-switch boundary. The client's
  `<model_switch>` message persists in history, so the portable pass used to
  rewrite every later turn and drop the current model's own reasoning; now
  only items before the last marker are treated as foreign, and a marker
  inside a tool run moves the boundary back so the run replays whole. The
  Muse Contributor row keeps whole-history rewriting until it is probed.
  `ai_router/history_portability.py` carries the pass as a leaf.

## 0.6.50

- Stream failures now classify on OpenRouter's canonical top-level
  `error_type` instead of the lossy `error.code` collapse, and the log
  records `upstream_error_type`, `upstream_provider_code` and
  `failure_class` (`context`, `final` or `transient`). A refused stream
  keeps the `invalid_prompt` code Codex treats as fatal instead of the
  router's own code, which Codex retried five times; the log keeps
  `UPSTREAM_INVALID_PROMPT`. The one pre-answer stream retry now requires
  a `transient` class, so deterministic refusals are never re-sent.
- Router answers on the Responses protocol now match what the Codex client
  does with them: deterministic refusals (unsupported preparation, oversized
  turn, spent provider credit) answer HTTP 400, which ends the turn at once
  instead of costing five silent retries; transient upstream failures (5xx,
  408) answer 503 with `Retry-After`, which the client retries on its own
  backoff. Only the compaction summariser keeps a retryable 409. An upstream
  429 is classified from structured codes only: quota answers 400 with
  billing guidance, auth opens the key window, transient keeps the 503. The
  Anthropic Messages path keeps its existing answers except at the shared
  HTTP size boundary, where an oversized turn answers 400 like Responses
  (no Messages client issues such turns today). Client hang-ups log
  `client_disconnected` instead of sharing `transport_error` with upstream
  faults, and 5xx/408 turns log `upstream_unavailable`; the refusal cache
  stores only 400 answers.

## 0.6.49

- A failed stream now records who wrote the terminal frame the client received
  (`terminal_source`), how many bytes reached it (`forwarded_delta_bytes`) and
  how many of those were the model's answer rather than setup
  (`content_delta_bytes`). A 2026-09-13 incident on one OpenRouter model row
  took an hour of log forensics because the log could not tell the provider's
  own `response.failed` frame from the router's frame on a dead socket.
- One provider failure is now absorbed before the client sees it: when an
  OpenRouter Responses stream ends with the provider's own failure frame while
  every byte so far is still held, the router re-opens the upstream once and
  continues the same response. Setup frames are held until the answer starts
  (bounded at 64 KiB) so the retry replaces them instead of appending a second
  copy; any byte already sent, a failure after an answer frame, the
  provider's own prompt refusal, and a context refusal all pass through
  unchanged. A retry that answers with a non-200 status or a different body
  ends the stream with the provider's original held verdict plus the router's
  own terminal frame, and a retry that dies mid-stream the same way; the
  verdict the client keeps decides `terminal_source` (`upstream` when the
  provider's frame survived, `router` when only the router's did). Each retry
  logs `stream_retry` with the provider code that caused it.
- `forwarded_delta_bytes` counts bytes the upstream produced, including held
  setup frames once flushed; the router's own terminal frame is not counted.

## 0.6.48

- Installer-changing pull requests now run native installer checks on macOS
  and Windows plus a real Python 3.9 surface check, scoped by
  `tools/ci_scope.py`; the single required `Test` gate fails when any
  scoped job fails. Releases run the installer jobs unconditionally.
- The Windows loopback listener binds exclusively (`SO_EXCLUSIVEADDRUSE`,
  `SO_REUSEADDR` off), so a second local process can no longer bind the
  same port and receive router traffic. The dialog liveness probe test
  tolerates transient cold-probe stalls on Windows CI.
- The source-limits baseline check rejects nonexistent files, incorrect
  counts and entries below their soft cap instead of drifting silently.
- Seeded ingress input-shape coverage and router-level SSE framing cases
  pin the rejection and framing contracts without adding guards.
- Carried history no longer splits a parallel tool group. On a thread that
  switched models the `<model_switch>` marker keeps the portable pass running,
  and its tool-search note was written between a group's calls and their
  outputs, so the converted chat history held calls with no results and a
  strict upstream refused the turn ("incomplete parallel tool-call group",
  and Meta's synchronous HTTP 502 on the same carried body when the thread
  switched to `meta/muse-spark-1.3-contributor`). The note now waits until the
  tool run closes, and reasoning notes wait with it.
- A provider refusal that OpenRouter raises after the stream has opened
  (`invalid_prompt`) is now answered as `UPSTREAM_INVALID_PROMPT` with one
  actionable sentence, instead of relaying the provider's whole schema dump to
  the client. OpenRouter's bounded code still reaches the service log, and no
  retry or request translation was added.

## 0.6.47

- A failed stream now records why the upstream ended it: the terminal event,
  the provider's error code, or an incomplete response's reason. An incomplete
  response is logged as `UPSTREAM_INCOMPLETE` instead of the generic upstream
  failure, and provider message text is never recorded.
- A client that disconnects before a JSON reply is flushed (health and model
  listing polls) no longer raises out of the handler, so it no longer writes a
  BrokenPipeError traceback to the service log.

## 0.6.46

- Express release tags publish urgent updates on either stable
  (`v<VERSION>-express`) or beta (`v<VERSION>-beta-express`).
- macOS, Windows and Linux gain a separate minute Express check using the
  existing verified installer. Ordinary releases keep the four-hour schedule.
  Existing machines gain this capability through their next ordinary update.
- Express checks preserve channel selection, install locks, health rollback
  and failure limits. After one failed attempt, retries use the normal cadence.
  Older restored releases skip the Express check without losing regular updates.

## 0.6.45

- Importing the router remover no longer changes Codex settings or stops the
  service. The installer Python compatibility check compiles executable scripts
  without running them and imports library files in a scratch environment.
- Existing installations affected by the September 13 compatibility-check
  incident recover their Codex routing settings when the installer runs again.
  See `docs/codex-routing-incident-20260913.md` for the cause and recovery plan.

## 0.6.43

- Codex remote compaction V2 now returns the completed compaction item and
  response completion through the streamed Responses contract, while V1 and
  non-streamed V2 keep their existing JSON shape.
- Summaries truncated with the structured `max_output_tokens` condition
  receive one bounded retry at 8,000 output tokens, clamped to the registry
  ceiling, with a shared 120-second deadline.
- The offline context-budget probe now covers both V1 and V2 threshold and
  context-error recovery, plus truncated-summary recovery, against the
  installed Codex app-server with a fake upstream.

## 0.6.42

- External Responses streams now translate context-limit refusals into Codex's
  recognized error code, including nested metadata codes and the exact numeric
  "The prompt is too long" refusal. Terminal stream failures are logged as
  failed requests even when the upstream HTTP status is 200. Successful output
  and usage are preserved; this does not guarantee automatic in-turn compaction.

## 0.6.41

- Claude Code drift check (plan 148): attaching Claude Code records the
  served listing snapshot (ids, display names, tiers and the served-at time)
  inside the existing activation receipt, and `--doctor` now reports whether
  the live `GET /v1/models` listing still matches it - `match`, `drift` with
  the added and removed ids, `unknown` when the router is not answering, or a
  warning when the attachment predates snapshots. The contract note in
  `docs/claude-code.md` records why `ANTHROPIC_AUTH_TOKEN` and
  `ANTHROPIC_API_KEY` must stay unset and why a launcher alias was rejected.

## 0.6.40

- Codex windows that declare a previous context window now receive explicit
  assignment-recovery guidance on both subscription and external Responses
  routes. The shipped instructions distinguish summarized compaction from
  `new_context`, which can omit the brief. Agents must retrieve their prior
  assignment and progress before treating a reset as an unassigned task.
- Upgrades replace the exact legacy context paragraph in retained subscription
  templates while preserving custom instructions and model settings.
- A real-client probe exercises initial delivery, unsummarized reset,
  read-only history retrieval and completion of the recovered assignment.
  Its default is scripted; optional live acceptance has a strict call cap.

## 0.6.39

- Releases serialize publication to the shared update feed and verify the
  maintainer-created tag before publishing. Release reruns are limited to
  Cyril and Brent. Contributor guidance now covers public pull requests
  against `main`, and model capability refreshes use the normal reviewed PR
  process instead of a scheduled workflow blocked by organisation policy.

## 0.6.38

- An encrypted handoff to an externally billed child can no longer end the
  turn silently. When the upstream model picked the native encrypted spawn,
  follow-up or send for a child this thread created on an external model,
  the router answered with a synthesized tool result; Codex recorded that as
  unexpected and stopped. The rejection now keeps the native function, item
  and call identity and replaces only the unreadable arguments with a
  bounded diagnostic, so Codex raises a real argument-validation error,
  asks for the next inference and the parent corrects the call within the
  same turn. The diagnostic contains no assignment text, ciphertext or
  target name; native encrypted handoffs and valid plaintext calls are
  unchanged.
- The handoff probe gains an installed-Codex recovery run: it rejects each of
  the three native handoffs, requires the matching validation error, then
  proves the corrected plaintext call and the parent's final answer land in
  the same turn, in both classic and Responses Lite wire modes.
- Release publishing uses the pushed tag for the bundle URLs and for
  `gh release create --verify-tag`, so publishing no longer depends on a
  workflow-created secondary tag.

## 0.6.37

- Operator surface (plan 147): `--doctor` prints one read-only row per
  component (runtime, install, service, each provider's key, picker
  catalogue, scheduled command, update recency) with a `Fix:` line on every
  WARN or FAIL, `--json` for machines and exit 1 when a row fails.
  `--status` now reports the last update check, the last applied version,
  the last error code and any parked versions from state. `--support`
  writes a 0600 bundle containing booleans, enums, versions, counts and
  timestamps only, and prints just the path. `--check-update` is now
  read-only: it names the installed and available versions and never
  installs or writes the ETag; the applying command is `--update`, which
  the home launcher, the systemd unit and the Windows task now run.
  The home launcher picks the applying verb the release `current` points
  at advertises, so a scheduled pass keeps working after a rollback to an
  older release (the channel then offers the newer release again, as
  before).
  `--rollback` with no argument lists the installed releases, and
  `--rollback --to VERSION` performs the switch `--version VERSION` still
  performs as an alias.
- Mixed-provider subagent assignments now work with native Responses Lite
  tool declarations. Plaintext aliases and encrypted-handoff steering apply
  to both wire formats; native OpenAI handoffs keep their encryption.
  The handoff probe now uses the actual installed subscription metadata.
- Child messages use matched tool results on external routes, avoiding
  Sonnet assistant-prefill rejections. External parents also produce
  executable plaintext calls when they select the native handoff tools.
- Switching from an external model to a ChatGPT subscription model now
  normalizes reasoning records in the outgoing request, including compaction
  requests. Foreign plaintext reasoning items are omitted; native encrypted
  reasoning, messages, tool results, and saved task history are preserved.
- Codex Responses validation failures retain HTTP 400 instead of becoming
  retryable 409 errors. Diagnostics include only validated structural field
  paths, and cached refusals retain the original client status.

## 0.6.36

- Ingress hardening, second wave (plan 146): the router refuses a state
  token that is not at least 32 characters of `[A-Za-z0-9_-]` (the installer
  already mints one), answers 429 with `Retry-After` beyond 32 concurrent
  turns and reports `inflight`/`max_inflight` on `/health`, answers 415 for a
  non-JSON body before parsing, and strips filesystem paths and the caller's
  model id from credential and unknown-model errors. `opencode_auth` must
  name the OpenCode client's own `~/.local/share/opencode/auth.json`; a
  state key pointing elsewhere is refused, and the installer resolves the
  same path so it never counts a key the service cannot read. A Windows ACL
  verdict is cached for 30 seconds per file instead of spawning icacls and
  whoami on every key read.
- New-model prompt (plan 135): when an update adds models for the machine's
  policy scope, the scheduled updater asks the running router over loopback
  and offers a Codex restart. A desktop notification names up to three of
  the new models and the single-use approval page (48 h link, Restart Codex
  or Later) opens in the browser; only the Restart click quits and reopens
  Codex, on macOS. Notifications and the page are macOS and Linux (with the
  platform tools present); Windows records the offer in the update log. The
  first run, removals and version-only updates stay
  silent, an unverified or out-of-policy row is never announced, and the
  offer is best-effort: a failed notification or browser can never change
  the update result. A Claude-only or service-only install is never told to
  restart Codex, and `ROUTER_NO_NOTICE=1` silences this offer too. The
  landing that first runs the trigger only seeds the snapshot, so
  announcements begin with the next landing that adds models. The hourly
  model refresh gains the same call when plan 099 wires it.
- Public repository readiness: the README is rewritten around the
  product with screenshots of the Codex picker row, the first-run key
  window and the update notice, a logo that switches to a white
  wordmark in dark mode, and a maintainer contact. `SECURITY.md` names
  the reporting address and scope, `CONTRIBUTING.md` carries the branch
  rules and gates, issue templates steer vulnerability reports away
  from public issues, `CODEOWNERS` moves under `.github/`, the model
  allocation review moves to `plans/model-allocation/`, and
  `pyproject.toml` gains the project URLs. Documentation only; the
  installed router is unchanged.
- Subagent model visibility (plan 151): Codex builds the `spawn_agent`
  "Available model overrides" text from the first five picker-visible
  multi-agent models in catalogue order, and the catalogue lists the
  subscription roster first, so every router model was hidden from that
  list even though the picker showed them all. The served model
  instructions now carry the visible router roster plus the rule that an
  id missing from that list can still be passed, with any router
  rejection reported, and the starter global instructions carry the same
  rule for subscription-model sessions. A fresh merge renders the roster
  from the picker's own projection, so it never names an allowlisted-out
  or client-hidden model; `catalogue --check` compares the rendered form.
  The client cap itself is unchanged upstream, so plan 151 stages 3-5
  stay open.
- Model verification gate (plan 145): `models add` now writes new rows as
  unlisted preview (`listed: false`), hidden from the Codex picker and
  `GET /v1/models` while staying routable for their own probe. Only a
  passed `--probe` promotes to `listed: true` with `tier: verified`; a
  failed or refused probe changes nothing and prints why. New read-only
  `models discover` reports addable, registered, unavailable and retired
  ids without writing or billing, and the compatibility record names the
  legs that ran (`tool,stream,image,compact`).

## 0.6.35

- Carried-history portability, second slice: a portable turn (the Muse
  Contributor row, or any turn carrying the client's `<model_switch>`
  marker) now drops carried reasoning items instead of replaying them.
  Measured on 2026-09-12: Meta answers a carried deepseek reasoning item
  with a bare HTTP 400 while the identical turn without it is accepted.
  Native, marker-free turns keep their reasoning items.

## 0.6.34

- A fresh install opens the first-run key window by itself whenever the
  installed service has no key: the installer mints the setup nonce and
  spawns the native popup without needing `--setup`, which stays as the
  explicit force and now also works on an up-to-date home by restarting the
  current release with a fresh setup link, never re-extracting it. A
  shell-exported `OPENROUTER_API_KEY` no longer counts as configured (the
  service does not receive the invoking shell's environment), so it prints
  one non-secret notice and still opens the window. A non-blank key file
  with widened permissions refuses before install with the file and the
  required permission. Scheduled and manual `--check-update` runs never pop
  the window (`ROUTER_NO_KEY_WINDOW=1` on the installer child, also the
  unattended opt-out); the next request opens it through the request path.
  Cancelling the native key dialog now counts as a cancel instead of a
  dialog failure, so it no longer opens the browser setup page (macOS
  reports the cancel as "cancelled" with AppleScript error -128).
  `--setup` also repairs when the feed lags the installed release, without
  downgrading it.

- Carried-history portability (plan 150, slice 2a): turns on the
  `meta/muse-spark-1.3-contributor` row, or turns carrying the
  client's `<model_switch>` developer marker, replay a carried tool-search
  call as its declared tools with the search call itself omitted.
  Refusals on a routed turn now name the provider code when the field
  is already code-shaped and say to switch the thread back or start a
  new thread; an identical deterministic refusal answers 409 once more
  without dispatching again (8 entries, 60 s, never a 5xx). Rejection
  logs carry counts only.

## 0.6.33

- Namespaced client tools are exposed to routed models under readable aliases
  (`namespace__tool`) instead of `ns_<hash>_<tool>`; collisions and over-length
  names fall back to the same readable stem plus a short digest, sanitised to
  provider-legal characters, so a routed model can still read the tool it is
  calling. The digest widens until the name is unique; a tool set that exhausts
  that ladder fails the request instead of sharing a wire name.

- A tool call is repaired before dispatch only when it is the plain native tool
  name of exactly one exposed namespaced tool, the dotted `namespace.tool` form
  shown in its description, or a fallback alias whose digest characters were
  re-typed. A call that already carries a namespace, a readable-name typo, an
  ambiguous name, a native name the per-model tool ceiling withheld, and an
  unrelated name are never rewritten; they reach the client unchanged and the
  guidance line then names the exact exposed tool. Repairs and unresolved names
  are counted in content-free `tool_call_repaired` / `tool_call_unresolved` log
  events.

- When the client still answers `unsupported call: <name>`, the router adds one
  line naming the exact exposed tool to the model-facing history, and the routed
  base instructions now state that tool names must be copied verbatim.

- Documentation now ships with every release: the bundle carries `README.md`
  and `docs/*.md`, `docs/troubleshooting.md` covers the staff-real failures
  (a parked update, a client that needs a restart, key recovery, Claude Code
  routing, request error codes) and `docs/README.md` indexes the set. CI runs
  the offline unit suite on every pull request, parses the shipped shell and
  PowerShell scripts, and the secrets scan covers `*.yml`, `*.sh` and `*.ps1`.

- README: the router home path and the installed-release installer are
  documented, installs and updates need no GitHub account, and switching
  channels by hand requires clearing `feed-serial`.

- Repository README rewritten for public consumption: an install quick start,
  client and model guidance, updates, security, architecture and development
  sections, with the installed-file inventory moved to
  `docs/runtime-files.md`.

- Repository relicensed to Apache-2.0 only: `LICENSE` carries the Apache
  License 2.0 text, `COMMERCIAL_LICENSE.md` is removed, a `NOTICE` file is
  added, and package and plugin metadata use the `Apache-2.0` SPDX
  identifier. `packaging/VERSION` remains the release authority, and
  `pyproject.toml` now tracks it exactly (a test fails on drift). Publication
  remains blocked until the provenance question for
  `ai_router/openrouter_base_instructions.txt` is resolved.

- Automatic updates come from the public token-free feed: every install
  polls `https://dist.softwarecombined.com/<channel>/latest.json` with no
  token, no enrolment, no GitHub account and no repository access. Checks
  run every 4 hours (Linux also checks 5 minutes after the timer activates;
  macOS checks when the job loads). The `channel` file in the router home
  selects `stable` (default) or the public pre-release document at
  `beta/latest.json`. Checksums, version and identity checks, and the
  serial replay guard are unchanged, and `--feed` remains the manual
  install and update route. A leftover `feed-token` file on an older host
  is inert.

- The restart notice is about the picker, not the version: it is staged only
  when a release adds a picker row the last install did not announce, so a
  routine update no longer asks for a Codex restart that would change
  nothing. An attempt that merged rows and then failed still prompts on its
  retry, an unshown notice is refreshed with the running version, a notice
  that could not be written is retried by the next install, and a catalogue
  or baseline this comparison cannot read keeps the previous behaviour and
  stages the notice. Additions that never pass through an install (live
  refresh, picker mode changes) still need Plan 135.

- The picker pins exact model ids: `anthropic/claude-opus-5`,
  `anthropic/claude-sonnet-5`, `anthropic/claude-fable-5.1`,
  `anthropic/claude-haiku-4.5`, `google/gemini-3.8-flash`,
  `google/gemini-3.1-pro-preview` and `x-ai/grok-4.6` replace the
  `~...-latest` aliases, which are retired via `RETIRED_SLUGS` so upgrades
  drop them. The router no longer follows upstream `latest` movement on its
  own; a new version is a registry row plus a retirement. Opus 5, Fable 5.1
  and Haiku 4.5 passed isolated base round trips and are verified (Haiku at
  `none`, its only supported effort), and the Grok image-stall hint keeps
  matching the pinned row.

- Providers are now data, not code paths: `ai_router/provider_defs.py` holds
  one definition per upstream (host, endpoint prefixes, key location, model
  catalogue, key-info endpoint, failure dialect), and the Responses and
  Messages adapters are parameterized by it. OpenRouter remains the built-in
  external provider and behaves exactly as before. Several external
  providers can serve at once, each with its own owner-only key file and its
  own fail-closed state: one missing key no longer stops the others. Picker
  labels and billing lines read the row's provider label, `models add` /
  `live_refresh` / `models check` follow the row's provider (with
  `--provider`), `--status` reports a `providers` key map, and the setup
  window names the provider whose key it collects. Failure policy moved to
  `ai_router/upstream.py`; the setup page it shares with the native popup
  renders the provider's own label.

- Linux keeps checking for updates after a failed install step: the systemd
  backend stopped the timer to replace its units and restarted it only at
  the very end of a successful install, so a refused settings merge or a
  failed client attach left every later poll dead until a reinstall. The
  timer now starts where it was stopped.

- The restart notice survives a headless updater run: a dialog that dies at
  once -- the scheduled systemd service has no display, so zenity exits
  with "Failed to open display" -- was recorded as shown and never seen
  again. The notice stays pending until a run that can actually draw the
  dialog shows it.

- `bootstrap.sh --channel=beta` (and the PowerShell equivalent) now writes
  the router home's `channel` file. The flag previously chose only that
  install's bundle, so the host silently followed stable on every later
  poll.

- A refused settings merge no longer hides the update it landed: when the
  installer exits non-zero but the router is already serving the new
  version, the scheduled updater records the pass, shows the pending
  restart notice and stops parking a release that works here. A pointer
  without a serving router is still parked, and the exit status stays
  non-zero so the problem remains visible.

- A bootstrap channel switch resets the anti-replay serial, whose old value
  refused every poll until the new channel's next release. The channel file
  is written only once the host runs the feed's version or newer: a
  lock-deferred run exits 0 without installing and must not switch the
  channel, while a host already ahead of the requested channel (beta ahead
  of stable) still moves.

- Release tags created by the workflow now name the commit the bundle was
  built from (`gh release create --target "$GITHUB_SHA"`), so a tag's
  commit and its assets agree.

- The Codex picker lists the OpenRouter-billed GPT twins again: Astra,
  Sol, Terra and Luna appear beside their ChatGPT subscription rows, so a
  refused or exhausted allowance still leaves them selectable on the
  OpenRouter key. The subscription rows are unchanged and still first in
  the picker; the `· OpenRouter` label and the client's billing note keep
  the two routes apart. Nothing changes on the Claude side: the gateway
  listing already includes every registry row, and the mirror rule stays
  in the `--client claude` catalogue merge.

- First install no longer needs the repository: the pinned CPython runtimes
  and both bootstrap wrappers are published to the public feed, so any
  machine installs and then auto-updates with no token, no GitHub account
  and no repo access. The new `tools/publish_first_install.py` verifies
  every runtime against `packaging/runtime.lock` before upload and is
  idempotent.

- First-run key setup is a native popup instead of a browser page: macOS,
  Windows and Linux are asked for the OpenRouter key, the ChatGPT-subscription
  choice and the starter in one flow, and the popup confirms the stored key
  with its remaining credit. It submits through the same single-use nonce
  route as before, so validation and owner-only storage are unchanged; a host
  with no dialog tool still gets the loopback page. The popup carries the same
  product icon and plain-language wording as the update notice, and the new
  popup-style rule in `AGENTS.md` (pinned by `tests/test_popup_style.py`) keeps
  every future dialog consistent. `ROUTER_NO_NOTICE=1` silences the post-update
  restart dialog for unattended installs, and the test suite no longer spawns
  real dialogs.

- The setup and update dialogs follow the install's client set: a Codex-only
  machine is asked about ChatGPT and offered "Quit and reopen Codex", a
  Claude-only machine is asked about Claude and told to restart Claude Code
  (no Codex app button), and a both-clients machine gets both questions and
  both instructions. The installer records the attachment set in the router
  state, and a scheduled update reads it back for the notice.

- Licensing groundwork: the repository now carries the verbatim PolyForm
  Shield License 1.0.0 text with the `Required Notice: Copyright 2026
  Software Combined Pty Ltd` line, `COMMERCIAL_LICENSE.md` explains when a
  separate commercial licence may be needed, and `THIRD_PARTY_NOTICES.md`
  records the MIT-licensed opencodex material in `ai_router/compaction.py`.
  Package and plugin metadata move from `UNLICENSED` to
  `LicenseRef-PolyForm-Shield-1.0.0`, and every release bundle now ships the
  licence files. No runtime behaviour changes. The repository stays private;
  publication remains an owner decision.

- Nested cross-task messages now reach tasks running on OpenRouter models.
  Codex Desktop injects `create_thread` / `send_message_to_thread` turns as
  standalone tool outputs with no `call_id`; the router used to drop them
  as orphan tool fragments, so delegated tasks on OpenRouter models never
  saw the message. Each standalone app-injected output is now rendered
  before the scrub as a matched tool-result pair -- a synthesized complete
  `function_call` plus the `function_call_output` carrying the delegation
  text verbatim -- which the model acts on as a tool result. Assistant-role
  plaintext was tried first but live acceptance rejected it (the child
  replied `NO-ASSIGNMENT` instead of acting on the assignment).

- Tagged releases now publish to the public update feed at
  `dist.softwarecombined.com` as well as to GitHub Releases, so an
  installed router updates with no token, no GitHub account and no
  repository access. The feed stack lives in this repository
  (`infra/feed-cert.yaml` in us-east-1, `infra/feed.yaml` in
  ap-southeast-2), and a tag-only GitHub OIDC role is the sole publisher.
  GitHub Releases remain a public mirror of each release for humans,
  published after the feed. Bundles are immutable, the channel feed is
  invalidated on publish, and no client request-path behaviour changes.

- Context size is the provider's call again: the OpenRouter pre-flight
  refused a turn whenever serialized characters divided by four exceeded
  the model window, but real tokenizer ratios run 4.4-5.8 chars/token over
  long sessions, so the estimate refused turns the client still had room
  for and Codex ended the thread instead of compacting. Live 2026-09-11
  (thread 01a08ba0): a 4,324,328-byte turn billed 750,806 tokens upstream,
  was estimated at 1,091,485, and was refused at 79% of the model window
  with 193k tokens left in the client's compaction budget. Local refusals
  are removed; a genuine upstream context error still arrives as the typed
  `context_length_exceeded`, now also recognizing OpenRouter's explicit
  top-level `error_type` shape. The output-reservation math is unchanged.

- After an update the router shows a single desktop dialog (macOS, Linux
  and Windows) carrying the SCG product icon. It offers "Quit and reopen",
  which quits the Codex desktop app and launches it again so the new models
  load: the macOS bundle `com.openai.codex`, the Windows Store package
  `OpenAI.Codex`, and the Linux preview app `chatgpt` when it is
  installed. "Later" dismisses the dialog; where the app is not installed
  the restart button simply does nothing. Only one dialog is ever on
  screen: an update that lands while the previous dialog is still open
  folds into it instead of stacking a second one. The notice is
  best-effort, fires once per version, and never blocks or delays the
  update. The Linux update unit keeps `KillMode=process`, so the detached
  dialog survives the oneshot run that spawned it.

- Replayed reasoning history no longer disappears before OpenRouter turns.
  `strip_reasoning_blobs` now strips only the provider blob field and keeps a
  reasoning item whenever readable summary or `reasoning_text` content
  remains, so DeepSeek thinking mode receives the prior reasoning the API
  requires; the old key-presence test dropped every item even when
  `encrypted_content` was null. Real blobs are still removed, items with no
  readable text are still dropped, and compaction briefs now read reasoning
  text from both `summary` and `content` instead of treating any
  `encrypted_content` key as opaque.

- The pre-flight context estimate no longer counts base64 image payloads in
  replayed history as text, so a turn carrying images inside tool outputs is
  no longer refused as over-context; image blocks now cost a flat per-block
  allowance, and text-only models detect images that sit inside tool outputs.

- Install and update need no GitHub CLI: the updater reads the public feed
  directly, so the scheduler-minimal PATH resolver for `gh` is gone.

- No-subscription installs (`openai_mode: none`) now list the
  OpenRouter-billed OpenAI rows (Astra, Sol, Terra, Luna) in the Codex
  picker instead of the dead subscription slugs; mode flips in the setup
  window refresh the picker file. Subscription installs are otherwise
  unchanged.

- Models whose OpenRouter row carries no web-search capability no longer
  receive Codex's `web_search` server tool. OpenRouter cannot execute it
  for those models and aborted the stream with `Server tool request
  failed`, killing the turn a few seconds in; the affected rows (DeepSeek
  V4.1 Flash and V4 Pro 0813) keep their client-side tools.

- Thread titles, descriptions, summaries and title reconsiderations run as
  helper turns on the subscription model. When the ChatGPT allowance is
  exhausted upstream refuses every helper turn and the client stores a
  slice of the prompt as the title instead. With the new
  `openai_helper_fallback` state flag on (default off) the router answers
  just those helper turns from the registry's OpenRouter twin row
  (`openai/<slug>`) and logs `subscription_fallback`, so generated titles
  survive an exhausted allowance; ordinary turns keep the existing 503.
  A provisioned portco allowlist still gates the twin, and enabling the
  flag bills the OpenRouter key for helper-shaped prompts.

- The Codex picker groups OpenRouter rows by vendor A-Z, verified before
  preview inside each vendor; `models add` renumbers priorities into that
  order and the global "preview last" offset is gone, so Anthropic's four
  rows sit together again.

- DeepSeek keeps two pinned, verified rows: `deepseek/deepseek-v4.1-flash`
  (newest Flash, image-capable) and `deepseek/deepseek-v4-pro-0813`
  (newest Pro, text-only). The `~deepseek/deepseek-v4-flash-latest`
  tracking alias and the `deepseek/deepseek-v4-flash-vision-exp` row are
  retired via `RETIRED_SLUGS` so upgrades drop them from the picker.

- Install global starter instructions once from the setup window: after the
  key is stored, a Dev or General choice writes the matching full
  `AGENTS.md` only when no global instructions file exists yet. Existing
  files are never overwritten, and updates and uninstall leave them alone.

- Bootstrap downloads need no token: `bootstrap.sh` and `bootstrap.ps1`
  fetch the pinned runtime and the release bundle from the public feed
  with plain requests and verify both checksums. The header-file and
  `feed-token.previous` machinery is gone.

- `--uninstall --dry-run` now previews: it reports the target home and
  exits before touching client settings or services, matching the other
  dry-run actions. The scratch-home guard is unchanged.

## 0.6.13

- Auto-update without repo access (Plan 054, source slice): the scheduled
  updater learns a feed token from `latest.json` and switches itself from
  private GitHub Releases (gh) to the token-gated feed at
  `dist.softwarecombined.com`, per host, with no manual step. Hosts without
  a token keep the exact pre-migration route, so old and new installs
  coexist; a host that is already current still migrates on its next poll,
  because the token is learned after the serial check and before the
  version comparison. Feed and token handling consolidate into
  `packaging/feed.py`; feeds and bundles off the trusted origins are
  refused, and refusal messages never echo a URL query string. The
  CloudFront distribution, publish workflow, and library page remain
  owner-gated.

- Refuse mutating installer runs against a scratch `--home` unless
  `ROUTER_LIVE_RUN=1`: service names are machine-wide, so a run pointed at
  /tmp still bootstraps, bootouts, or TERMs the production jobs. Read-only
  `--status`/`--preflight` stay exempt; `--uninstall` is refused with or
  without `--dry-run`. A prior simulation against /tmp took down the
  production router this way; the guard makes that shape refuse before any
  service call.

- Operator bootstrap for no-repo-access installs: `packaging/bootstrap.sh`
  (macOS/Linux) and `packaging/bootstrap.ps1` (Windows) install a router
  host from the Technology library page with `SCG_FEED_TOKEN`, resolving
  the pinned Python runtime from `runtimes.json`, which `release.py` now
  emits next to `latest.json`; `release.py --feed-token-file` embeds the
  publish-time feed token, and `docs/operations.md` documents the flow.

- Add `docs/agent-install-prompt.md`: a paste-to-agent prompt for the
  Technology library page so users can have their agent run the bootstrap
  and verify setup without repo access.

- Rename the runtime package `codex_router` to `ai_router` (Plan 074): the
  router serves Codex, Claude Code, and OpenRouter side by side, and the old
  prefix misled readers into treating the Codex adapter as the whole router.
  Distribution and bundle names become `ai-router`. Installed homes, service
  labels, state/catalogue filenames, and the `codex_router` log name stay so
  existing installs keep working; a thin `codex_router` alias re-exports
  `ai_router` during the transition, and the launcher boots either package
  layout. Client-specific modules (`clients/codex.py`, `claude.py`,
  `codex_config.py`) keep their names.

- Keep one effective discovered schema per tool through compaction: the
  discovered-tool store deduplicates by (namespace, name) before memory/disk
  writes and on recall, so repeated rediscovery no longer grows duplicate
  definitions; first full definition wins with stub completion preserved.

- Name the model id on catalog misses: `UNKNOWN_MODEL` now carries the
   requested `model` plus a `candidates` list holding at most the exact
  tilde-alias slug (e.g. bare `anthropic/claude-opus-latest` offers
  `~anthropic/claude-opus-latest`), so a parent can retry once instead
  of probing the catalog. Identity stays strict: nothing auto-routes,
  and the hint never names a slug the portco allowlist excludes.

- List every OpenRouter row in the Claude desktop third-party gateway
  picker: `GET /v1/models` rows now project `anthropic_family_tier`
  (`sonnet` for non-Anthropic rows, each Anthropic alias's own tier
  word), which the desktop requires for non-Anthropic-looking ids. No
  registry field is added and ordering and labels are untouched.
  `packaging/install.py --desktop` attaches and detaches the desktop
  gateway profile with the same ownership receipt discipline as the
  Claude Code CLI attach, and refuses when `claude_mode` is `none`.

## 0.6.12

- Make the Windows installer work end to end (Plan 057 Stages 3, 4 and
  the first real-machine proof, Windows 11 2026-09-10): the router task's
  logon trigger is scoped to the installing user (an unscoped one needs
  elevation) and its recovery trigger carries the `StartBoundary` Task
  Scheduler requires; an update or restart drains the running router through
  `/shutdown` and waits for the instance to end before relaunching, since
  `IgnoreNew` made the old `/run` a no-op; uninstall ends both tasks before
  deleting them (a deleted task leaves its process running); both tasks run
  `pythonw.exe` through a home-root `task_launch.py` (written on every
  install) that routes stdout/stderr to `logs\launchd.log` and
  `logs\update.log`, and every console child is spawned windowless.
- `stop` on a never-registered task no longer masks the real failure, and
  the installer prints why a backend refused before it rolls back.
- Ship `packaging/platforms/windows.py` in the release bundle: without it
  every scheduled update and rollback on an installed Windows router failed
  to load the backend.
- Write the Codex catalogue path with forward slashes: a native Windows
  path in the TOML block made `config.toml` unreadable to Codex.
- Protect `mixed-router-state.json` (loopback token) and the router home
  itself on Windows with the key's owner-only `icacls` grant, inheritable so
  every file the router writes later is born owner-only; grants name the
  account as `whoami` reports it.
- `install.ps1` runs the installer through the `py` launcher instead of the
  bare `python` alias, which opens the Microsoft Store on a stock profile;
  the no-interpreter message names the Windows remedy instead of Homebrew.
- Uninstall drops the Codex activation receipt after restoring the config
  (all platforms): a stale receipt made the next install refuse the
  subagent guidance it found missing and exit 1 with the service running.

## 0.6.11

- Forward stream bytes without waiting for identity inspection: the
  tool-free observer now yields each piece as it arrives and parses at
  most 64 KiB retained bytes (JSON, post-EOF) or complete SSE frames,
  instead of buffering the body first. Oversized or malformed bodies
  disable observation, never forwarding. No deployed latency claimed.

- Attribute router latency per phase instead of one cumulative number:
  `request_completed` now carries `read_ms`, `prepare_ms`, `connect_ms`,
  `send_ms`, `headers_ms`, `first_data_ms`, and `first_write_ms`, plus
  fixed-category `response_kind`/`response_encoding`; failures record
  the phases that completed. Cumulative fields keep their meanings.
  This enables measurement; it claims no latency improvement.

- Attribute context refusals and estimate the full billable request:
  the pre-flight estimate now counts serialized tools and instructions
  alongside input (image blocks excluded, matching the client counter),
  and each `context_length_exceeded` rejection logs the model, path,
  and `used`/`reserved`/`window` integers so the next incident needs
  no by-traffic attribution.

- Enforce per-portco model allowlists as resolved data (Plan 068, source
  only): `<home>/model-policy.json` (`0600`, atomic write) carries the
  centrally resolved slug subset; the picker (`merge`/`check` plus the
  `--allowed` CI flag) and both protocol routers reject non-listed
  OpenRouter slugs with the existing closed error while subscription
  rows are unaffected. Absent file means all approved models; malformed
  files fail closed to an empty OpenRouter set. Central grant schema,
  refresh delivery, and per-install issuance stay gated on Plan 054 Stage 4.

- Give the first-run key page an executive light-theme layout matching
  SC_360 (single card, blue-600 primary control, slate hairlines,
  labelled key field and described subscription choices, inline error
  banner, detail list on the connected page). Style is inline only, so
  the loopback page still fetches nothing; the form contract, statuses,
  single-use nonce and owner-only key write are unchanged.

- Tell the Windows truth sooner and more usefully: `--status` and
  `--preflight` now run on Windows (read-only; install and update still
  refuse before changing anything), and the owner-only key check
  tolerates the OS principals every default profile inherits
  (`NT AUTHORITY\SYSTEM`, `BUILTIN\Administrators`) while still
  refusing broad groups and other users.

- Steer parents back to readable handoffs: an encrypted handoff that cannot
  arrive readably (OpenRouter-model spawn, or follow-up/message to an
  OpenRouter-spawned child) is replaced with a targeted error naming the
  exact `collaboration_plaintext` call to make instead, before history is
  poisoned. Proven by a Luna v1 parent reaching a real Muse child end to
  end after one steered retry (Codex 0.153.4).

- Deliver readable agent handoffs to OpenRouter children without weakening
  native encryption: new `collaboration_plaintext` aliases for the already
  exposed spawn/message/follow-up tools, restored to native calls with
  `encrypted_function_args: []` on JSON and SSE responses, plaintext agent
  messages converted at the OpenRouter boundary with sender/recipient kept,
  and opaque or mixed encrypted assignments rejected before credential
  lookup. Proven Astra v2 parent to Muse child with scripted children
  (installed router, Codex 0.153.4); v1 subscription parents stay
  fail-closed and need their own plan.

- Attach Claude Code without touching Codex: new `--clients
  claude|both` merges only the two owned `env` settings into the
  user's `settings.json` with conflict refusal and receipt record,
  plus validated `scg-openrouter` plugin manifests and a shared
  `manage-router` skill driving the canonical installer (offline
  proofs; staff-surface acceptance still pending).

- Read installer state without touching it: new `--status [--json]`
  prints installed version, service state, attached clients, and
  key-present/usable booleans with no secret-bearing values. The
  read-only preflight/status commands move to `packaging/diagnostics.py`,
  bringing the installer back under its entrypoint size budget.

- Recover a missing or revoked key without hand-deleting files: a keyless
  router boots, the first request opens the loopback setup page once per
  live nonce with a clear message, and the page replaces a stored key
  only after OpenRouter itself rejects it on 401/403 (offline proofs;
  central issuance remains owner-gated).

- Report missing install prerequisites before writing anything: new
  `--preflight` flag prints each missing item (Python 3.14, `gh`
  binary for the transitional feed route, Codex CLI unless `--client
  none`) with its remedy and exits non-zero, without creating the
  router home.

- Harden Windows key protection in source: icacls owner-only enforcement
  with verify-after-write, a read-time ACL gate mirroring the POSIX check,
  and setup-window refusal on unprotectable keys (offline proofs only;
  the installer still refuses Windows until backend acceptance).

- Add the Windows Task Scheduler backend in source (Plan 057 Stage 3,
  offline proofs only): per-user logon router task plus 15-minute updater
  task, pythonw.exe router with python.exe updater, graceful /shutdown
  restart, and registration readback that names group-policy refusals.
  The backend is now wired: the installer routes Windows to it instead
  of refusing. Staff rollout stays gated on real-machine acceptance.

- Pin the private CPython 3.14 runtime: new `packaging/runtime.lock`
  names one install-only distribution per qualified target with validation
  and wrapper-table generation (Stage 1). All four targets now carry
  reviewed pins (CPython 3.14.7, astral-sh build 20260814) with URLs and
  SHA-256 digests verified against the downloaded archives.
  Release builds validate the lock first.

- Give each client explicit activation: new `packaging/codex_config.py`
  owns the Codex block, picker preservation, guidance, and receipts; the
  installer checks the remover's exit status instead of its wording.
  `--client none` installs service-only without touching client settings,
  and `--anthropic-mode` sets the Claude subscription choice independently
  (unset follows the OpenAI mode as before).

- Give model facts one owner each: pure metadata normalization moves to
  `model_metadata.py`, the Codex capability projection is shared by merge
  and apply (identical fields for the same snapshot, audio preserved where
  advertised), and picker visibility moves to the client domain. No roster,
  tier, or routing changes.

- Tell the truth up front: the README names Windows installer support as
  not-yet (the installer refuses before changing anything), lists GitHub
  CLI access as a transitional requirement, moves Arch setup below the
  generic Linux path, and qualifies key-file protection per platform.
  Supervisor logs rotate at service start (1 MB each, two backups).

- Separate HTTP transport from wire-protocol policy: shared `Prepared`,
  hop-header, stream, and header-relay leaves move to `transport.py`, and
  the handler dispatches through an explicit `protocols/` method/path
  table instead of client-specific branches. On-wire behavior is unchanged.

- Refuse unreadable encrypted agent briefs before dispatch: an
  `agent_message` carrying an encrypted block now fails closed with a
  content-free preparation error instead of forwarding opacity a child
  would infer around. Plaintext agent labels survive compaction summaries.

- Keep upstream prose and exception text out of diagnostics: rejected
  upstream turns now name a fixed category (tool-schema, tool-call, or
  request rejection) with the provider and offending tool instead of
  reflecting upstream prose, and structured logs carry the stable error
  code without message content. Client status codes are unchanged.

- Wrap Grok tools whose object root carries an `anyOf`/`oneOf` union with a
  non-object branch (reported 409: `automation_update` declares
  `type: object` with a root `oneOf` including a scalar). The PR #25 guard
  only checked the root `type`, so the tool sailed through unwrapped and
  xAI rejected the turn. Object-only unions stay native.

- Order the picker for scanning: subscription rows in roster order, then
  verified OpenRouter rows A-Z by display name, then preview rows A-Z, in
  both the Codex catalogue merge and the Claude `GET /v1/models` listing.
  Values are never rewritten to achieve the order.
- Seed fresh installs with the native subscription reasoning levels per
  model (e.g. Sol defaults low, Spark defaults high) instead of a single
  medium placeholder, so the effort picker works on a new Mac the way it
  does on an upgraded one. Existing catalogues are untouched.
- Drop `gpt-reserve` from the default subscription roster and picker.
  The next scheduled update evicts the row from the catalogue and prunes it
  from preserved state, so routing stops authorizing it as well.
- Repair subscription rows stuck on the 0.6.10.23 single-medium placeholder:
  the next merge upgrades exactly that legacy signature to the native levels
  per model and leaves richer and custom rows untouched. Updated machines
  whose GPT rows showed only medium effort regain the full picker.
- Default omitted OpenRouter output limits to at most 32,000 tokens, bounded
  by the provider ceiling and the headroom after Codex's 90% compaction
  threshold. Reserving half the window previously rejected long tasks well
  before native compaction. Explicit output limits keep their existing caps.
- Report estimated context exhaustion and explicit upstream context-limit
  codes using Codex's `context_length_exceeded` signal: `response.failed`
  over SSE for streaming requests and HTTP 400 JSON otherwise. Other
  preparation errors remain 409. Native compaction thresholds are unchanged.

## 0.6.9

- Make `--feed` one-shot for the anti-replay serial as well as the URL. A
  local bundle carries its own build number as its serial, so a pinned
  install recorded a number the real feed had not reached, and every later
  scheduled check refused the real feed with `stale feed serial` -- updates
  stopped silently. A pinned feed is now exempt on both sides: its serial is
  neither checked against nor recorded. Checking it was the trap that invited
  choosing a build number high enough to pass, which is what froze the
  channel; the unattended channel keeps full replay protection.

- Stop the updater from unloading the router and leaving nothing running.
  `launchctl bootout` returns 0 as soon as teardown *starts*, so the
  `bootstrap` issued immediately after it failed with `Bootstrap failed: 5:
  Input/output error` and the job ended up loaded nowhere. Recovery then
  could not work either: both the reload's heal and the health-check rollback
  relied on `launchctl kill TERM` plus `KeepAlive`, and an absent job has
  nothing to keep alive. Every subsequent 15-minute update run spent 150s
  waiting on a `/health` that nobody was serving and reported "new version
  failed health check" against a release that was perfectly good. Unload and
  load now wait for the launchd domain to settle, retry a bootstrap that lost
  the teardown race, verify the end state, and fail closed rather than
  mistaking a surviving stale job for a successful reload.
- Never report a clean rollback over a router that is not serving. Every
  install path, success or rollback, now ends by asserting a loaded job that
  answers `/health` on the expected version, bootstrapping it when missing,
  and says the router is down when it cannot.
- Reload the service only when launchd's in-memory copy actually differs from
  what is being written, compared against the loaded job rather than the file
  on disk. An ordinary version update now hands over in place with a TERM:
  `router_launch.py` re-reads `current` on exec and launchd keeps the
  listening socket, so in-flight requests drain on the old process, no
  connection is refused, and no bootout can strand the machine.
- Compare interpreter identity by resolved path. `/opt/homebrew/bin/python3.14`
  and `/opt/homebrew/opt/python@3.14/bin/python3.14` are one binary reached by
  two symlinks, and a string compare called them different, forcing the
  destructive reload path on runs that needed only a handover.
- Point the scheduled-update job at a stable `update_launch.py` in the router
  home instead of a per-release `install.py` path, and reload that job when
  its command changes. launchd runs its in-memory copy of a loaded plist, so a
  versioned path outlived the release it named: after a prune the updater kept
  invoking a deleted installer every 15 minutes.
- Adopt a changed scheduled-update command by comparing the whole loaded
  command, not just the interpreter. On a normal upgrade the interpreter is
  unchanged, so an argv[0] check never fired and launchd kept running the old
  per-release installer path indefinitely.
- Never `bootout` the scheduled updater from inside it. That job is what runs
  the installer, so the bootout would kill the process issuing it, wait out
  its whole timeout for a label that cannot leave the domain while its own
  process lives, and return without bootstrapping: automatic updates gone,
  exit status clean. A scheduled run now leaves the rewritten plist for the
  next manual install or login to adopt, and the installer reports it when
  the updater is not loaded instead of exiting quietly.
- Stop waiting for an idle router before updating. A swap is a pointer write
  plus a `TERM`: launchd holds the listening socket, so new connections queue
  for the incoming process while the outgoing one drains the requests it
  already accepted. The idle gate delayed every update on a machine that was
  actually in use and protected nothing the drain does not already cover.
- Serialise installs on every platform, not just Linux, with one advisory
  lock on `install.lock` taken at the entry point. The scheduled pass and a
  manual run could previously interleave on macOS, both swapping `current`,
  rewriting both plists and reloading the same label. The duplicate lock in
  `systemd.py` is gone; `--dry-run` takes no lock and creates no router home.
- Enforce the documented source budget on `packaging/` too. The checker only
  walked `codex_router`, `tools` and `tests`, so the two installer entrypoints
  grew unguarded and their baseline entries were decorative; `install.py` had
  reached 16 lines short of its hard limit with no signal. The failure-count
  helpers moved to `service.py`, which already owns state reads and writes.
- Keep the release that launchd's loaded updater command still names. A
  scheduled run defers the updater reload (it cannot bootout its own job), so
  launchd goes on running the old per-release installer path; pruning that
  release would leave it firing a missing file every fifteen minutes, which is
  the failure this release exists to remove.
- Count an installer child that never reports as a failed attempt. A child
  killed by the 900-second timeout raises `TimeoutExpired`, which is a
  `SubprocessError` and not an `OSError`, so nothing recorded it and the
  version was never parked.
- Park a version that fails three times instead of
  re-fetching and re-activating it every fifteen minutes. Each failed pass
  cost a service restart and most of a cycle with the router down. A
  successful install clears the count, and a different version always gets
  its own attempts. The count lives in the state file, which is what parks a
  version on the production feed: that feed is read through the GitHub CLI
  and carries no ETag to save.
- Let installer failures reach their own rollback. The health guard caught only
  `OSError` and `CalledProcessError`, so the `SystemExit` raised by a failed
  reload or launcher install skipped the rollback block entirely and left the
  pointer on an unverified release.

- String-wrap non-object tool parameter roots for `~x-ai/grok-latest`
  (new `json_text_root` schema mode): xAI rejects union-root schemas such
  as the desktop automation tool, failing even a plain greeting. Ordinary
  object-root tools are unchanged; Meta recursive-schema handling is kept.
- Name upstream failures at the client: stalls before upstream headers keep
  502 but name the model, elapsed wait and timeout with a retry action
  (Grok image turns stall upstream, retry text-only); DNS/refused names the
  host; parseable upstream 4xx bodies become 409 with the provider reason
  and offending tool instead of a bare passthrough; unknown shapes relay
  verbatim and mid-stream disconnects stay log-only.
- Retire the stale `deepseek/deepseek-v4-pro` (V4 Pro 0423) picker row via
  `RETIRED_SLUGS`. Kept DeepSeek rows: Pro 0813, the Flash Latest tracking
  alias, and Flash Vision Exp.

- Preserve the owner's picker selection (`model`, `model_reasoning_effort`)
  inside the managed Codex config block across installs and scheduled
  updates instead of resetting it on every rewrite.
- Reject image-bearing turns routed to a text-only model (409 naming the
  image content and the target model) instead of silently stripping the
  images: switch back to an image-capable model or continue without images.
- Route defined HTTP failures through one shared error catalog with stable
  codes (`codex_router/errors.py`, now in the deploy list); CLI/tool exits
  print `CODE: message` and logs record the same code.
- Promise and prove mid-thread model switching in Codex: switching models
  from the picker continues the same thread with history and tools
  intact, since every turn routes on its own model. If one
  model reports it is at capacity, switch to another and carry on.
  Astra subscription history (encrypted reasoning blobs, compaction
  items, tool calls/results) replays cleanly on Muse; blobs are
  stripped, readable summaries and results are kept, and opaque native
  compaction replays as a visible note rather than readable context.
  Image blocks do not carry over to text-only models. A model
  tool-count ceiling (Grok, 350 tools) defers instead of rejecting:
  over-ceiling turns go out with the search tool plus already-released
  tools, and the rest load on demand; the 409 stays only when the turn
  cannot fit under the ceiling that way. Grok image turns run text-only (new pinned
  `drop_images` registry quirk) with a short note where each image was,
  instead of stalling upstream.
  The thread effort carries over, and an effort the new model does not
  support (for example carried max onto Contributor) is rejected with
  the allowed levels instead of failing opaquely upstream.
- Scrub incomplete tool history before forwarding: partial calls and
  orphan outputs left by interrupted turns are dropped from replayed
  history instead of failing the whole turn with an upstream 400.
  Complete call pairs pass through untouched, on every model.

## 0.6.7

- Reject OpenRouter requests whose estimated input plus reserved output
  would exceed the model's context window (409 with an actionable message)
  instead of forwarding a doomed turn that the endpoint 400s outright.
- Retry transient feed-fetch failures inside the scheduled update check
  (up to 4 attempts, 30s/60s/120s backoff) instead of waiting a full
  15-minute poll cycle; deterministic errors still fail fast.
- Normalize picker labels to `<Vendor>: <Model> <Version?>` (e.g. `Z.ai: GLM 5.3
  Flash`, `Anthropic: Claude Haiku Latest`, `DeepSeek: V4 Flash Latest`):
  every `display_name` is stored qualified with its vendor prefix, alias rows
  track with `Latest` instead of a pinned snapshot, and pinned rows keep any
  version/snapshot token verbatim. `models add` (`qualify_name`) and
  `live_refresh` (alias rows keep their pinned tracking label) now produce
  conforming rows, and a registry test pins the convention.
- Merge the dated DeepSeek flash snapshots into the tracking alias
  `~deepseek/deepseek-v4-flash-latest` (upstream serves this id, aliasing
  0731); the old `deepseek-v4-flash` and `deepseek-v4-flash-0731` picker rows
  retire via `RETIRED_SLUGS`. Upstream serves no pro-latest id, so Pro keeps
  dated ids with clean names. Vision Exp stays separate as the only
  image-capable DeepSeek row.
- Repair existing bare or incomplete subscription catalogue rows on merge,
  preserving their model-specific metadata. Catalogue checks now reject
  rows missing schema fields instead of accepting an unusable picker.
- Add Linux systemd user service installation, updates, rollback and uninstall.
  Migrate legacy symlink installations to the stable launcher, replace old
  checkout/local-feed timers, and serialize installation operations. The
  service grants the router's drain time and restarts on exit.
- Leave busy installations untouched, restore the previous catalogue on a
  failed upgrade, and retain the updater's ETag when a child installer defers.
- Download this private repository's release assets through the user's
  authenticated GitHub CLI, including scheduled checks.
- Make the cross-platform pieces work on Windows so `python -m unittest
  discover` runs green there. The discovered-tools cache stamped each new file
  one nanosecond past its siblings to order eviction by insertion, but Windows
  FILETIME truncates that bump on readback, tying timestamps and evicting the
  wrong entries; it now steps past the sibling by an amount it confirms
  survives readback. Release bundles and the source-limit checker build member
  and baseline paths with POSIX separators (`as_posix`) instead of the host
  separator, and the stable launcher reads its pointer file as UTF-8. The
  install, update and service suites (macOS launchd / Linux systemd, which have
  no Windows equivalent) and a few POSIX-permission assertions are skipped on
  Windows only; they still run in full on macOS and Linux.

## 0.6.6

- Fix launchd spawning nothing after update: the installer persisted
  find_python's bare discovery token (`python3.14`) into the plist,
  which launchd cannot resolve (no Homebrew PATH). It now persists the
  probed absolute `sys.executable`, both plist renderers fail closed on
  non-absolute interpreters, and upgrades detect a legacy bare-python
  plist and reload the main agent (updater untouched) to heal it.

## 0.6.5

- Remove feed signature enforcement: the installer accepts unsigned
  feeds again, trusting version, URL, checksum and serial plus the
  feed/manifest/marker identity check. The Ed25519 module and its
  `--gen-key`/`--sign` tooling stay in the tree as a documented
  opt-in for later. Owner decision: ceremony overhead outweighed
  the publisher-authentication benefit on this channel.
- Fix Claude POSTs with a query string (`/v1/messages?beta=true`)
  being rejected: `do_POST` now strips `?...` for route matching,
  mirroring `do_GET`, so query-bearing inference calls route like
  the bare path.
- Fix tag-gated releases never matching: the workflow stripped
  `-v` instead of `v`, so every tag would have failed the
  version check. Tags now compare correctly.
- Fix the Codex picker catalogue for Codex >=0.153.4 (desktop
  26.901.51231): every catalogue row now carries the full required schema
  (`display_name`, `available_in_plans`, `prefer_websockets`,
  `minimal_client_version`, `supports_parallel_tool_calls`,
  `supports_reasoning_summaries`, `default_service_tier`, `model_specialty`,
  `auto_compact_token_limit`, `auto_review_model_override`). Subscription
  roster rows seed as full-schema `subscription_stub()` entries with the
  live picker labels instead of bare `{'slug': ...}` stubs, which made chat
  creation fail with `missing field 'display_name'`. Defaults mirror the
  client's own embedded model catalogue.
- Test credential isolation: handler/compact/setup tests inject credentials
  instead of reading the machine's router home, so the suite stays green on
  machines where the router is installed (the real `openrouter.key`
  previously won the ordered lookup and turned 15 contract tests red).
  `Router` and `Credentials` accept optional injected credentials/home, and
  `default_home()` resolves `ROUTER_HOME` at call time. Also fixes the flaky
  `test_compact_holds_inflight_slot` (slot releases after response bytes
  leave the socket) and documents Linux `systemd` units plus the Arch
  `codex-desktop-git` pre-req in the README.
- Harden updates against live traffic: installs defer when the router
  is busy instead of killing in-flight requests, rollback restores the
  old pointer with `TERM` (never `bootout`, which stranded machines
  with no router), releases install only when feed, manifest and
  bundled marker versions agree, `--feed` is one-shot and never pinned,
  and three releases are retained for rollback depth. Releases publish
  from `v*` tags only; work lands on `develop` via short-lived
  branches, `main` stays release-only.
- Serve Claude Code model discovery: `GET /v1/models` answers
  `{data: [{id, display_name}]}` from the local registry so the CLI
  `/model` picker and the app picker list the router models as `From
  gateway` entries when
  `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=true` (Claude Code
  2.1.x, restart after changing the base URL). Listing ids are
  `claude/<vendor>/<name>` aliases, plus the bare `anthropic/...`
  Claude aliases which already pass the client's `claude|anthropic`
  filter; the router strips each alias back to its registry slug
  before routing, so billing follows the registry row and direct
  slugs keep working byte-identical. Unknown `claude/`-prefixed ids
  pass through to the subscription untouched.
- Hide OpenRouter-billed GPT rows from the Codex picker: the
  `openai/*` OpenRouter entries no longer list, so the picker shows
  the ChatGPT subscription models instead of a same-name paid
  duplicate. A directly requested hidden slug still routes to
  OpenRouter; nothing else in request handling changes. The future
  Claude listing reuses the same rule to hide OpenRouter-billed
  Anthropic rows.
- Fix context overflow on OpenRouter models: the output reservation is now
  capped at half the model's context window. The registry's 943718-token
  reservation on a 1048576-token window left ~105k for input, so ordinary
  long-task requests were rejected as exceeding the context.
- Clarify that the router runtime supports macOS, Windows, and Linux while
  the managed installer remains macOS-specific.
- Fix subscription-model 401s: the router no longer requires a
  subscription `Authorization` header on the loopback hop. Codex 0.153.4
  authenticates with the URL path token and omits that header, so every
  subscription request was rejected locally before reaching chatgpt.com.
  Headers now forward unchanged; missing or expired subscription
  credentials surface as the upstream response instead.

- Beta channel resolves to `beta/latest.json` on the same origin
  instead of calling the GitHub releases API.
- First-run key window claims the installer's empty key placeholder, and
  none-mode Codex config authenticates through the per-install path token.
- Service lifecycle: `POST /<token>/shutdown` drains and exits behind the
  path token; the service runs `router_launch.py` from the router home and
  `current` is a pointer file instead of a symlink.
- Offline probe accepts `--provider <id>` for the tool round trip on a
  custom provider.

## 0.6.1

- Rename the repository to
  `software-combined/SC_OpenRouter_adapter` and reframe the README for
  both clients: the router now serves the Codex picker and Claude Code.
  Update the release and updater URLs to the new location. No behavior
  change.

## 0.6.0 (Claude Code ingress, Preview)

- The loopback router now speaks the Anthropic Messages API at
  `/<token>/v1/messages` (plus `count_tokens`) for Claude Code, with the
  same billing split as the Codex picker: OpenRouter-registry slugs go to
  OpenRouter's Anthropic-compatible endpoint with the router key as the
  only credential, everything else passes through to `api.anthropic.com`
  with the client's own subscription credentials.
- OpenRouter-bound bodies travel byte-identical, so thinking blocks,
  tool_use IDs and cache_control keep full fidelity with no translation
  layer. Subscription requests keep version and beta headers; hop headers
  are stripped. No-subscription mode still serves OpenRouter models.
- Setup is one variable, `ANTHROPIC_BASE_URL` with the path token, and
  deliberately no API key variable, which would override the subscription
  bearer. Operator notes live in `docs/claude-code.md`.
- Preview status and residual risk: unit-verified against a fake upstream
  only. A paid live probe through real Claude Code sessions (one
  OpenRouter model, one subscription model) must pass before this is
  relied upon. Installer support for `~/.claude/settings.json` is
  deferred to a follow-up slice.

Entries older than the 0.6 series are archived unedited in
[docs/changelog-archive.md](docs/changelog-archive.md).
