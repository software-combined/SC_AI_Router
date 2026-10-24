# Router architecture: domain ownership

Single-page map of where new work goes. The dependency direction is inward:
leaves know nothing about their consumers. Verified against current source;
transitional owners name the plan that will move them.

Native packaging lives under `packaging/native/`; it wraps the canonical
installer without adding inference rules. `native_payload` retains disposable
downloads. `native_setup` owns the graphical flow and uses the existing client,
service and key-window owners. Repair uses the canonical `--repair` path;
explicit assistant additions use the existing client-selection path.
`repair_ui` owns explicit maintenance's graceful assistant-close prompt.
Scheduled updates never call it. Public bootstrap scripts retain the saved
channel and working runtime; repair never starts key setup.
`dialog_tool` is a Python 3.9 leaf shared by installer and runtime dialogs.
It validates retained setup paths before selecting the Linux wrapper.
`native_dialog` distinguishes cancellation from failed presentation so renewal
notices remain pending until a window appears.
`install_delivery` verifies and retains maintenance code before assistant
discovery. Attachment conflicts cannot block its controller, stable launchers
or Linux scheduler repair. Plugin and native controls delivery remain separate
from routing health, on both full and same-version installs.
The health-verified completion also owns installation evidence. Attachment failures
have separate events. `assistant_status` shares attachment classification with outer reconciliation.
`client_choice` resolves explicit additions, receipt-owned attachments and saved
choices. It persists Claude choices in `anthropic_mode`; the runtime keeps its
existing policy reader. Same-version mode changes use the service repair
lifecycle before client attachment, with prior state restored on reload failure.

`codex_owned` compares the live marked region with the saved attachment using
standard-library TOML. It preserves added single-line root settings and comments
outside the replacement block. Unknown structures and changed connection values
refuse before a write. Its bounded managed-Python verifier keeps Python 3.9
entrypoints importable without another TOML dependency. Removal uses the same
proof and atomic writer, preserving dotfile links and detecting concurrent edits.
Preference and reviewer edits use the same lossless line helpers, including
client-written line endings and inline comments.

`client_removal` checks all connected assistants before detaching any. Its
JSON edits use `owned_json` to preserve unrelated bytes and reject duplicate
keys. Receipts retain original values and the written connection values.
Legacy Claude receipts use the saved Router state for those connection values.
Completed restores remain complete after an I/O failure; remaining receipts
keep the service running for a safe retry. Atomic writes compare saved content
again after preparing the temporary file.

`native_controller` retains verified installer code under an independent version
pointer. `update_launch` selects that controller across runtime rollback.
Linux reloads and reads back the effective stable updater command before
pruning. Loaded jobs and a running legacy updater retain their release files.
`runtime_rebind` uses verified retained resource metadata after `setup-current`
advances. The Windows task adapter snapshots all three owned definitions,
changes only the executable and verifies its exact path, enabled and pending states.
Its JSON subprocess contract uses explicit UTF-8 output and decoding for Unicode paths and saved XML.
A failed readback restores attempted definitions. Both runtimes remain retained.
The outer maintenance cadence checks owned task paths without the installation lock.
Only a required repair repeats verification and changes tasks under that lock.
`desktop_menu` records helper exit codes and controller exception types.
It retries an unexpected helper exit once after one second within the controller.
Quit and removal stop it. Resource replacement uses the existing reload path.
Resource advancement launches with `--after-update`, bypassing only sign-in preferences.
That path never opens a chooser or warning. A held session lock leaves reload to its owner.
`feed` downloads public software without credentials. Legacy `download_auth`,
`download_oauth` and `download_session` helpers are retained for compatibility,
but the installer and updater no longer require them. `control_models` checks
model bytes against a signed feed's checksum. The inference process only reads
the resulting model cache. `infra/downloads` owns token verification and short
download grants for legacy consumers. It cannot change model routing or provider credentials.

`update_status` owns verified channel facts, cache identity and repair summaries.
Only a verified release for the same channel and source can support a cached
current-version response. Diagnostics and controls read those facts without
changing state. A successful feed check clears only earlier feed-verification or
transport errors. Unchanged Express checks record that recovery without claiming
installation success or consuming a regular update. Rejected data never reaches installation.
Temporary failures and missed checks remain visible as automatic retries.
A successful feed check cannot clear an incomplete installation or failed component.
`update_warning` offers a detached repair dialog after an applying check or when
controls open, only for incomplete installations, failed components or parked installers.
Its separate receipt records presentation time only; it cannot
clear verified facts or interfere with installation. Missing dialogs leave
the warning pending. Controls bind manual-check results to installed version,
channel and source before displaying them.

## Domains and direction

`update_reconcile` runs after applying-update installation locks close, including
unchanged regular and Express checks. Read-only preflight does not take the installation lock.
An attachment repair, runtime repair or changed attention result takes the lock without waiting
and repeats verification. Healthy unchanged checks do not acquire it.
Restart-notice presentation runs after the lock closes.
`codex_recovery` repairs only an absent block under a valid, active receipt and
healthy Router. `codex_owned` validates absence, connection conflicts and TOML.
Configuration and receipt writes compare their prior contents and verify readback.
Original uninstall evidence remains intact. The receipt retains a repair event
until `notice` can offer its configuration-only restart reason.
Normal attachment uses the same receipt event after configuration and receipt readback.
Unsafe active recovery marks assistant attention without replacing configuration or other component results.
The Windows task launcher records task kind, time, numeric status and safe failure classes.

`winsecurity` reads Windows security descriptors through the operating system.
`winacl` owns the permitted identities and rejects unsupported rules. Checks
have no verdict cache, so permission changes apply on the next key read.
Temporary operating-system failures cannot grant access or open key setup.

Desktop connection commands accept explicit destinations. The switch owner
rechecks the current selection while holding the installation lock, followed
by the client transition and profile locks. Repeated destination selections
do nothing. Existing shortcuts retain their toggle behaviour. Platform identity
and lifecycle helpers serve both clients; the configuration proof uses the
CLI bundled with the verified desktop app.

```
provider_defs (one definition per upstream, imports nothing) + errors,
redaction, sse, tool_merge, image_items, turn_budget, atomic_write, dialog_tool, state,
events, history_items (leaves: no module-level local imports; events' one
call-time state lookup is the only exception)
  ^
  |
registry / capabilities (model facts) + request_context (one request's
registry snapshot) + wire_shape (the learnt wire contract): stdlib plus the
provider table and registry only
  ^
  |
transport (Prepared, hop-header rules, raw stream, header relay) + upstream
(failure policy) + outcome / attempt_policy (terminal verdicts and sends) +
stream_errors / messages_events (classification) + stream_events / stream_attempt (frame kinds,
the uncommitted attempt) + stream_relay (one stream for relay.py): wire and
failure policy, consumed by the adapters below
  ^
  |
subscription_recovery -> subscription_discovery / subscription_catalogue + catalogue / models /
live_refresh / apply_catalogue (client projections and native discovery)
  |
tool_runs (the pairing model, on history_items alone) + agent_handoffs /
compaction / tool_adapter / tool_history / tool_aliases / discovered (request
normalization); external_history reads compaction's codec, never the reverse
decisions (typed-decision wire client, imports only provider_defs)
  |
jev_compaction (opt-in evidence selection, consumes decisions/compaction/tool_runs)
  |
outbound (pure Responses stages and Messages projections over the stages above)
+ rejected_repair (the Responses adapters' pure rejected-request repair proposals)
  |
providers (Responses adapters) + claude (Messages adapters)
  |
protocols (explicit method/path dispatch table; imports the adapters because
it selects one, and holds no policy of its own)
  |
ingress (auth/rebinding, body limits, GET routes, error shaping) + relay (upstream loop)
  |
router (HTTP control: drain/inflight and POST orchestration) + runtime (boot
composition: state, credentials, policy) + __main__ (process entry)
```

`events.py` owns the event log; only `router.py`, `ingress.py` and
`__main__.py` still import `runtime` (for the boot constants and the
handler's injected `log_event`), and nothing else under `ai_router/` does.
`tests/test_import_graph.py` is the enforcement, not this page.

`request_evidence.py` observes each ledger-owned send. Protocol parsers retain
bounded model, effort and endpoint reports with their source; the transport
observer measures actual reads while preserving bytes. A prior attempt's
identity never attests a later one. These records cannot authorize replay.
`inspect_requests.py` reads the existing rotated log without contacting a model
or loading credentials. Request outcomes and each attempt's observed ending
remain separate when recovery preserves an earlier terminal for the client.
Canonical Codex child and parent UUID headers bind the ledger to a child;
`inspect_requests` owns exact assignment-window lookup and retained-only
summaries. No agent names, turn metadata blobs or tool results are persisted.

`wire_shape.py` reads measured extra item types from the request's captured row.
The registry owns that profile; absence means unverified and never changes
what is forwarded. A model-family prefix cannot grant another row's evidence.
The route conformance suite enumerates all registry rows and provider-supported
protocols, including hidden rows. It exercises the real handler and common
request owners with simulated upstreams, plus discovered and future native
IDs. Native bytes and auth remain the native provider's contract.
The policy scan rejects literal model-name comparisons and prefix decisions in
runtime Python. Only the existing, exact discovery, picker and tracking-alias
predicates are exempt; preparation and recovery use capability data instead.

`candidate_evidence.py` owns content-free onboarding proof beside `candidate.py`.
It reads normalized registry capabilities, provider protocols and client IDs;
request handling never imports it. `models.py` promotes a new row only after
every advertised route passes offline conformance and a real-client probe
against unchanged source and capabilities. The ledger checker shares this
validator. `tools/probe_candidate.py` owns one isolated send budget across the
common transport and compaction summary boundaries. Repairs, replays and
summary retries all consume that cap.
This guard belongs to the probe process and never changes production limits.

Rules:

`agent_handoffs.py` owns readable handoff schemas and the per-call plaintext
marker. Codex delivers a brief as plaintext only when its call carries
`encrypted_function_args: []`. The ChatGPT subscription adapter asks the
install's credentials whether any external provider's key resolves; only then
can an external child exist, so only then are native briefs made readable.
Without such a key the request keeps Codex's stock encryption contract and
gains only lane hints. The native backend refuses a canonical
`collaboration.spawn_agent`, `send_message` or `followup_task` whose message is
not `encrypted: true`, so a keyed native request moves those three out of each
`collaboration` namespace into a `collaboration_plaintext` namespace placed
after it, as readable copies. This happens in Classic, Lite and discovered
declarations; the other collaboration tools stay, and an emptied namespace is
dropped. The model therefore sees one handoff surface, with nothing to choose.
A changed Lite prefix receives a stable content-based identity.
Each alias call returns to its canonical name with the marker, so Codex
executes the normal tool and saves canonical history. Ciphertext under an alias,
or an upstream encryption marker, is refused, never relabelled. A canonical
call to a readable declaration gets the marker unless its message matches the
backend ciphertext fingerprint; that call stays unmarked for the guard.
`handoff_response.py` applies those decisions to native Responses envelopes and
records bounded structural provenance through the shared event logger. Its
per-response call ordinals retain upstream ids only until that response closes.
Observation never grants plaintext authority or changes a handoff decision.
An encrypted handoff to an external recipient raises a typed response refusal
before an executable completed item is released. `relay.py` returns HTTP 400
before JSON headers or one terminal `invalid_prompt` event on an open stream.
It never replays the parent request or invents a tool result. Earlier valid
calls remain released. `tool_adapter.py` promotes developer Lite declarations
through its existing tool map. External upstreams accept readable canonical
schemas, so external projection rewrites them in place, including recalled
schemas, and its effective tool map after paging controls which calls receive
the marker.
`sse.py` owns shared event framing without provider-specific argument rewriting.
`standalone_outputs.py` owns app-injected output projection. External requests
project readable peer messages and standalone outputs into matched tool results.
A child-to-parent reply with readable text plus an encrypted sidecar is
projected with the readable text and an incompleteness warning; the sidecar is
withheld. Other opaque messages fail closed. Subscription replay changes only a
thread that switched model: it applies the switch boundary, then projects fully
readable agent messages, the shape external peers send. The backend reads
native encrypted replies and app-delivered outputs itself, so those stay
unchanged. Client history is never edited.
`history_portability.py` owns the model-switch boundary: a `developer` or
`system` message whose string content, or any of its text blocks, starts with
`<model_switch>` after leading whitespace marks a switch, and items before the
last marker were produced under another model. The marker names no model, so a
switch between two subscription models gets the same treatment as a switch off
OpenRouter.
`history_items.py` owns the history vocabulary more than one outbound stage
reads: the tool call and output families, the readable-text readers, the two
encrypted predicates and the readable agent-message predicates. The two
predicates disagree on an empty marker: `has_encryption_marked_agent_item`
counts an `encrypted_content` marker whatever its value, while
`holds_encrypted_payload` needs a non-empty payload, and each call site keeps
its own. `tool_runs.py` owns the pairing model (`pairs`, `open_calls`) and the
fragment scrub, on `history_items` alone. Plan 183 moved these out of
`history_portability.py`, `compaction.py` and `agent_handoffs.py`; every
importer reads them from these two owners, and the old names are gone.
`compaction.py` owns compaction only: the prompt, the `ocx1:` codec, the V1
output and the summary transcript, including bounded native `apply_patch` and
tool-search call/result evidence. `external_history.py` owns the two external
stages that read that codec: compaction items replay as readable text
(`rewrite_input`), and OpenAI-owned reasoning blobs go (`strip_reasoning_blobs`,
which the subscription retry repair reuses). External Responses also drop
the contiguous reasoning suffix after blob stripping: Codex saves interrupted
reasoning before retrying, and an external upstream can reject that suffix as
assistant prefill. Subscription retry repair keeps its existing blob-only rule.
The
switch boundary's run check, the custom-pair call map and Jev's candidate
pairing keep their own id rules (any truthy id and any later output; the last
custom call; ambiguous ids pinned), so moving them onto `pairs` would be a
behaviour change with its own review, not part of the move.
`outbound.py` owns outgoing Responses and Messages projections (Plans 183/188).
Messages adapters call named external and subscription entrypoints. External
alias, billing-header and deferred-tool repairs copy only changed containers;
native Messages history returns unchanged, preserving the original wire body.
`EXTERNAL_STAGES` and `SUBSCRIPTION_STAGES` are tuples of named stages that
run in order over one `Projection`: the path, the client's model id, the
request's captured row, and what a later stage or the adapter reads back.
`tests/test_outbound.py` pins both orders, so a reorder is a visible edit. A
subscription compaction request runs only the two replay stages. The adapters
resolve the row, then keep destination, credentials, headers, body encoding
and the external turn-size fit. `outbound.contain` is the one opaque-brief
rule: the first external stage and `router.py`'s compaction guard (through the
`providers.reject_opaque_agent_items` name) both apply it.
`tool_adapter.prepare_tools(payload, row)` shapes the declarations only and
returns the tool list to send with the kind and wire-name maps.
`tool_history.py` then rewrites the external tool history against them:
custom pairs, discovery listings, tool-search items, call renames and
`json_text` arguments, output annotations, then the model-switch boundary.
Neither looks a row up. Preparation never edits the client's payload (Plan 183
phase 3). Every stage and helper returns its result: the value it was given
when nothing changed, otherwise new lists with copies of only the items and
containers it changed. `agent_handoffs.native_handoffs` returns the payload
with the readable-handoff metadata, `hint_full_lanes` and `rewrite_tool_history`
return the payload, and `rewrite_custom_pairs` returns the items. The external
turn-size fit follows the same rule: `turn_budget.fit` returns
`(payload, stats)`, and its image and tool-output trims copy only the path to
each trimmed block, never the whole body. The original body stays whole, so
the helper fallback's twin or a second route prepares again from it
with the same bytes. `tests/test_outbound_purity.py` pins this against every
replay fixture on both routes, the native-then-twin sequence and both trims.
Native passthrough still forwards the client's own bytes when nothing
changed.
`subscription_history.py` owns the pure outgoing projection of replayed
reasoning and the router's own non-empty, structurally valid `ocx1:` compaction
summary (sent as readable text) for subscription Responses requests; it never
edits persisted client history. Opaque, malformed, or mixed encrypted native
compaction data is preserved and never becomes a repair target.
`rejected_repair.py` owns the Responses adapters' rejected-request repair
(Plan 183 step 2.5). Each adapter's `repair_rejected(prepared, described, raw)`
proposes at most one repaired `Prepared` for the one rejection it can justify:
the external annotation strip for an OpenRouter 400 that names no cause, and
the subscription `invalid_encrypted_content` repair of reasoning blobs and the
router's non-empty, structurally valid compaction summary. Opaque, malformed,
or mixed encrypted native compaction data makes the proposal ineligible. None
means ineligible and a proposal without a body means unchanged. A proposal
opens no connection, reads no response, logs
nothing and never retries. `strip_retry.py` keeps the `annotation_retry`
lines and asks `attempt_policy.Ledger` for the one repair send. The Messages
adapters propose no repair.
`context_recovery.py` adds fixed recovery guidance for client-declared context
resets on either Responses route, finding the `<context_window>` message by the
same rule. Codex owns saved history and executes its
retrieval tools; the router stores no assignment or transcript cache.
It also owns the exact legacy paragraph migration used by catalogue upgrades.
`outcome.py` owns the terminal vocabulary. `attempt_policy.py` owns every send
and the one helper-fallback transition, deciding from `Outcome` and commitment
facts rather than metrics. Responses routes allow three, two and one sends;
the fallback gets one fresh route and cannot fall back again. `attempt_ledger`
reports bounded request, attempt and terminal facts.
The ledger captures routing facts before the first send. Each response attempt
also captures its protocol, operation, stream intent, body kind and encoding in
an immutable `transport.ResponseFormat`, held by `StreamRecord` and replaced on
replay. Parsing and terminal emission use these facts, so clearing or replacing
the diagnostic dictionary cannot change repair, replay or finalization.
`stream_errors.py` owns shared HTTP/SSE context-error classification and applies
it to external Responses terminal events after tool adaptation. It preserves
successful frames and records semantic failure separately from the HTTP status.
An unrecognised terminal error stays `unknown` and is never replayable.
The external Responses stream lifecycle (Plan 187) is shared by every model
on that protocol, and nothing in it reads a model name. `stream_errors.events`
parses each frame once and `stream_events.py` names its kind (setup,
reasoning, plumbing, answer, failure, completion, or opaque for anything it
cannot place), keeping the frame's original bytes. `stream_attempt.py` owns
the uncommitted attempt: one slot each for `response.created` and
`response.in_progress` in that order, one for a failure terminal without
output, and a shared 64 KiB budget for reasoning and data-less frames, so one
attempt retains at most three parser-capped frames plus that budget. Any frame
it refuses commits the attempt: the held frames go out in order, then that
frame. It also owns `replay_safe`, the request-level rule that a replay may
only follow a prepared body offering no tools or only client-run ones
(`function`, `custom`; preparation already turns client tool search and
namespaced tools into functions); a hosted tool such as `web_search`, or an
unknown type, may already have run upstream, so that request keeps the
provider's verdict. `stream_relay.py` owns one upstream stream for `relay.py`:
offering frames to the hold and recording what the client received by kind.
For a stream outside that normalized lifecycle, every upstream chunk is
forwarded unchanged. Only complete frames are observed as a sidecar, so an
encoded body or incomplete final frame cannot be delayed, rewritten or turned
into a router parsing failure.
The same Responses observer reads identity-encoded streaming turns whose
content type is absent or unrecognised, as current native Codex traffic can
use that representation. It preserves partial frames immediately and requires
a readable terminal to name the outcome. Unrecognised nonstream data and all
encoded data stay opaque and unknown. Responses and token-count JSON retain
their existing EOF rule; Messages JSON needs a readable message and stop reason.
`messages_events.py` owns both Messages routes' lifecycle observation. A valid
empty start followed by a final delta and stop distinguishes success, client
tool use, truncation, server-tool pause, refusal and context exhaustion.
Unknown endings remain unknown; documented overload errors are transient.
Signatures, redacted thinking and future events remain opaque. Native chunks
are forwarded immediately and the subscription route keeps one send.
External Messages generation may hold one validated empty start and one
failure terminal. The same ledger permits one transient stream replay, only
with client-owned `input_schema` tools or no tools. Tool, thinking, unknown
and signature frames commit; the compatibility repair emits an explicit
replay fence before holding a potentially removable thinking block. That
fence remains effective even when no wire bytes exist to flush. Setup slots
are protocol facts on the common event, not names interpreted by the hold.
Non-stream requests, token counting and HTTP errors gain no retry. `messages_errors.py` renders
the shared outcome as a native Claude error, including a truthful 5xx status
for temporary failures. A broken external stream ends with one Messages
error; native and encoded streams remain untouched.
`attempt_policy` decides and opens a safe replay. It replaces the uncommitted
attempt; a failed replay leaves its verdict to reach the client. These leaves
never dispatch or own credentials.
`wire_shape.py` owns the learnt upstream acceptance rules as data plus checks:
the tool call/output pairing rules the test fake also enforces, and every
other rule an incident taught, each with the route it binds, its level and its
evidence. It observes and never changes a request. Each body prepared for a
Responses turn is checked (not the helper-turn fallback twin, which is off
by default), a broken rule becomes one `wire_contract` log line, and a
refusal line carries the same facts beside the body's names and counts.
Enforcing a rule is a separate, evidence-backed change. Its call and output
families stay local rather than coming from `history_items`: they map only
the client-run calls that expect an output, including `computer_call_output`,
while the vocabulary's call set also holds server-side calls that never get
one, and the import would widen this layer.
`request_context.py` owns the request's one registry read (Plan 188).
A model refresh (`model_refresh.apply`) can swap the registry while a request
is in flight. So the protocol policy's `resolve` captures one read-only
slug-to-row snapshot before provider selection. It returns a frozen
`Resolved`: the request id, the resolved slug, its row and that snapshot.
Every later decision takes its row from `Resolved`, never from
`registry.by_slug`. That covers the owner, the upstream id, the protocol pair,
the tool and history quirks (`outbound`'s tool stages), effort
(`capabilities.check_row_effort`), images, the output cap, compaction budgets,
the Claude alias and the helper-fallback twin. The next request captures the
new registry. `Prepared.context` carries it to the relay, and the pending
fallback plan retargets it in place, so the twin keeps the same request id. A
native id with no registry row resolves with `row=None` and goes out as the
client spelled it. `request_started` and the final record share the
`request_id`. It is a random id, not derived from request content.
The readable-handoff metadata retains that same catalogue through response
adaptation. The encrypted spawn, send and follow-up guard resolves child models
from it, so a refresh cannot change an in-flight request's decision. Direct
helper callers without a request context capture once when creating it.
`codex_route.py` owns the switched Codex route. Switch Codex gives Codex a
provider entry that needs no OpenAI sign-in and sends `x-scg-codex-route`, so
that header marks the route; a missing credential cannot, because the normal
route may carry no Authorization header either. `subscription_fallback.prepare`
asks it about each request the ChatGPT subscription adapter would serve, before
anything is prepared or sent. Native service paths get the no-subscription
answers; every other request gets one final `invalid_prompt` refusal, which
`ingress.error` sends as a `response.failed` frame when the turn streams. The
refusal names the twin row only when the portco allowlist, the key's
availability snapshot and the Codex picker all admit it. Helper turns are
refused too: the helper fallback moves a turn to its twin only after the
subscription refuses it, and this route sends nothing to refuse.
`routed_models.py` owns `routed-models.json`, the picker Switch Codex points
Codex at: the rows no-subscription mode shows, under the mixed list's key and
portco filters. `availability.sync_catalogue` rewrites it after the mixed list,
never empty and never without a live snapshot, since Codex rejects an empty
list and a stale one offers models the key cannot use. `codex_route.ready`
answers whether Switch Codex may use it, reading "current" through
`availability.effective_ids`; it sits in `codex_route` because `availability`
imports the writer, so a check beside it would import `availability` back.
`usage_episodes.py` owns `codex-usage-limit.json`, the record of ChatGPT
usage-limit episodes the Switch Codex offer reads. `subscription_fallback.refused`
answers every ChatGPT 429, so it hands each one over with the drained error
body. Only the refusal Codex itself reads as a spent allowance counts
(`error.type` `usage_limit_reached`, per `codex-rs/codex-api/src/api_bridge.rs`),
and only from Codex desktop, recognised by the `(Codex Desktop; <version>)`
User-Agent suffix its app-server adds. The module imports leaves plus
`upstream.parse_payload`, keeps three fields and nothing from the request, and
swallows its own failures, so the client's answer never changes. The format
is in [runtime files](runtime-files.md#codex-usage-limit-record).

1. `provider_defs.py` owns every upstream fact (host, endpoint prefixes, key
   location, model catalogue, key-info endpoint, failure dialect) and imports
   nothing, so `packaging/` can spec-load it on Python 3.9. `registry.py`
   imports only stdlib plus that leaf. Nothing in `ai_router/` may make the
   registry import a client, CLI, installer, or HTTP module. Client listing
   and config modules consume it; never the reverse.
2. HTTP transport owns loopback auth, body limits, drain/inflight, and
   connection cleanup: `ingress.py` owns auth/rebinding, body limits, GET
   routes and error shaping; `relay.py` owns the upstream relay loop; and
   `router.py` keeps drain/inflight plus POST orchestration over both.
   `transport.MAX_REQUEST_BYTES` (256 MiB) is the local hard ceiling on wire,
   decoded and prepared bytes for every route and encoding, checked by
   `ingress.read_body`, `router.Handler.admit` and again on every send in
   `transport.post_with_phases`; `Prepared.decoded_body_bytes` keeps a
   compressed passthrough from being under-counted. `runtime.MAX_BODY`
   (16 MiB) is only the threshold for shared large-request reservations.
   `request_lease.py` owns the 1 GiB budget, reservations, bounded waits and scalar
   diagnostics. Its condition uses the server lock; releases and draining wake
   waiters. A first reservation waits up to 60 seconds for space. Existing
   holders grow without waiting, preventing deadlock while they retain bodies;
   the budget is therefore an admission target, not a hard process-memory limit.
   One request above the budget can start when no reservation exists.
   After preparation returns, the controller releases a reservation when the
   request fits the threshold and retains neither fallback nor response adapter.
   Otherwise it spans relay and cleanup. Retry admission counts both retained
   bodies and reacquires a released reservation before any additional send.
   `turn_budget.BODY_BUDGET` shapes external Responses turns only; native
   bodies are forwarded whole. Protocol representation lives in `providers.py` (Responses/Messages) and
   `claude.py` (Messages ingress).
3. Upstream adapters own target/credential construction and are
   parameterized by one `ProviderDef`, never by a provider-name branch. A
   new external provider is a table entry plus registry rows; a provider
   with a different wire format is a new adapter class, never a branch in
   the request path.
   AWS Bedrock is the second external provider. Its Mantle endpoint reuses
   the native Responses and Messages wire formats, so it adds no adapter
   class: `provider_defs.BEDROCK` owns the regional host builder, the
   `/v1` and `/anthropic` prefixes and the Bedrock API key location. A
   registry row may narrow its provider's protocols with `protocols`;
   `registry.row_serves` is the one rule routing, pickers, candidate
   evidence and the route matrix read. Availability keeps one snapshot
   per external provider (its own key, region and file), and pickers read
   the combined set while routing gates each provider on its own
   snapshot. Bedrock has no summary rows, so its compaction fails closed. `image_provider.py` owns the native Images wire format;
   `protocols/images.py` selects the originating chat's connection;
   `media_origin.py` retains bounded, content-free turn bindings after chat
   preparation. Standalone calls without provenance keep their profile contract.
   `video_provider.py` owns Responses video job submission. Both use `media.py`
   for media envelopes and retain
   the shared credential, admission and transport boundaries. Media rows do
   not enter the chat projection. [Media generation](media-generation.md)
   records the client contract and preview limits. `media_cli.py` owns the
   explicit fallback command, including bounded video polling, a recovery
   receipt and exclusive output creation; it reuses the canonical adapters.
   `external_provider.py` owns the region, provider identity and model
   authorization shared by chat and video adapters. It imports neither
   adapter; distinct wire formats remain in their own modules.
   External headers start fresh every request;
   subscription headers never accompany an externally billed request.
   `decisions.py` is the one client for a provider's typed-decision endpoint
   (Jev today): it holds no policy and answers only what it can validate, so
   every consumer fails closed on its refusals and nothing runs it by default.
4. Installer orchestration (`packaging/install.py`, `bundle.py`,
   `service.py`, `updater.py`) calls one explicit platform backend;
   `bundle.py` owns the release lifecycle (verify, install, prune,
   rollback). Unsupported OS is an explicit refusal. Backends do not import
   runtime providers or client catalogue policy.
   `platforms/windows_tasks.py` owns structured Task Scheduler access and
   principal/action checks; `windows.py` owns account-scoped names and lifecycle
   order. Owned legacy definitions remain available through registration and
   expected-version health checks. An active legacy updater keeps its ownership
   record until a later healthy install can remove it after exit.
5. A client is not a provider and an OS is neither. New clients reuse a
   proven wire protocol; a new protocol lands only after its contract is
   verified against the installed client version.
6. `packaging/` file-based imports (`spec_from_file_location`) avoid
   depending on a third-party distribution named `packaging`. Installer
   scripts stay Python 3.9-compatible; the runtime requires 3.14.
7. `tools/` holds checkout-run helpers (local probes, scans, key ceremonies)
   that are invoked by the developer or by CI, not by an installed router;
   `ci_unittest.py` owns bounded CI workers and their result reports, keeping
   unittest discovery and fixtures separate from router runtime behavior.
   `plugin_verification.py` owns conservative suite selection for local and CI
   checks; unknown scope retains full discovery.
   `packaging/` holds the modules an installed host executes. A new
   host-run script belongs in `packaging/`, even if nothing in `ai_router/`
   imports it. `packaging/release.py` includes only its named installed operator
   helpers from `tools/`; checkout verification tools stay outside the bundle.
   `tools/disable.py` is the installed-host remover that `packaging/install.py` runs.

`plugins/` and `.agents/plugins/marketplace.json` host the SCG agent-plugin
marketplace outside the router dependency map: no `ai_router/`, `tools/` or
`packaging/` module imports from `plugins/`, and plugin scripts never import
router code.

Plugin source is grouped under `plugins/<domain>/<plugin-name>/`; the
[domain index](../plugins/README.md) also routes to shared department briefs.
`packaging/release.py` discovers package roots by their Codex manifest, so
updater exclusions apply to each plugin. `packaging/agent_skills.py` reads both
domain folders and older flat bundles, then preserves flat installed paths.
Duplicate plugin folder names fail before marketplace files are written.

## Client contract

`ai_router/clients/registry.py` is the one owner of who sees what: one row per
client, carrying its primary picker protocol and supported wire protocols, the picker
predicate and the discovery predicate. Both Claude projections read it, and
`packaging/install.py` derives its `--client`/`--clients` choices from the
`ai_router/clients/roster.py` leaf, which is import-free so the installer can
spec-load it (`packaging/service.py::load`). Adding a client means:

1. a row in `ai_router/clients/registry.py` (and its id in the roster leaf);
2. protocols the router already dispatches on, per `protocols/TABLE`:
   Responses and native Images for Codex, Messages for Claude Code. A new
   wire protocol requires a verified client contract before it joins this table;
3. a capability projection under `ai_router/clients/` only if the client's
   catalogue shape differs from Codex's;
4. an activation adapter under `packaging/` owning that client's config file,
   the keys it owns, its conflict refusal and its detach path, following
   `claude_config.py` as the smaller of the two examples;
5. a receipt entry through the shared receipt writer, so `--status` and
   `--uninstall` know what was touched;
6. an entry in `docs/compatibility.md` naming the client version verified.

The genuinely hard case is a client that speaks neither protocol: it needs a
new adapter class behind the definition table, never a branch in the request
path (`AGENTS.md` section 3).

`packaging/claude_desktop_config.py` owns desktop attachment and its original
restore snapshot. A matching owned attachment keeps the user's selected
subscription or gateway mode on subsequent setup and update runs.
`desktop_windows.py` resolves the current user's registered Claude Store
package and its virtualized roaming profile; the gateway profile stays separate.
`windows_native.py` binds package, process, token and window APIs with explicit
pointer types. It owns native handles and returns identity facts to desktop policy.
It performs no discovery, shutdown or activation on import.
`windows_codex.py` owns fresh Store package discovery, process selection and
verified Windows Codex lifecycle policy. It reuses the desktop writer tracker.
Termination requires explicit consent from its caller and rechecks one open
handle's creation time, account, session, package and executable before use.
Query handles remain open through shutdown; a second snapshot checks parent metadata
before selection, preventing a reused process ID from adopting an unrelated app.
`windows_dialog.py` verifies the retained compiled helper for switch confirmation
and progress. The helper owns presentation; Python owns consent and configuration.
`claude_desktop_switch.py` owns the switch lifecycle. After Claude exits normally,
it shares the current account's local tasks and changes the mode only when all
required copies succeed. Open and Switch share one transition lock, held before
reading the mode through reopening, so overlapping requests cannot use a stale
source profile. The switch rechecks the attachment, managed policy and stopped
app before changing the mode. When setup recorded no Claude subscription, it
refuses a move to the subscription before asking or closing Claude, and the
menu disables that choice. Open Claude leaves histories alone. The stable
`claude_profile_launch.py` follows the installed release pointer so both actions
survive updates and release pruning. After a rollback to a release without task
sharing it runs that release's plain switch, opens Claude for Open Claude and
keeps the callback silent. Setup rebuilds 0.6 shortcuts and deletes only the
router's own copy of their home shim. Setup owns the callback installation and
removal. Existing recovery launchers remain Mac applications; the identity
callback also supports account-bound task sharing from Windows and Linux tray controls.

`claude_profile_rules.py` owns the local-data transfer policy being integrated
by Plan 169. It keeps conversation payloads intact, excludes separate sign-in
and credential files, and relocates only recognized metadata paths. The folder
Claude Code names after a task's workspace is exempt from the sensitive-word
name screen and the dashed -before/-after suffix rule, because its words are
the user's; router markers, credential file names and the content screen still
apply there. It imports
only the standard library. Callers must supply validated source and destination
paths and publish through their own transaction; the helper does not select an
account, change profiles or start synchronization.

`claude_desktop_policy.py` owns the read-only policy check for Plan 169's
switch path. Organization-managed connection settings take priority over a
local attachment; unreadable or ambiguous settings refuse the switch. Platform
readers follow the published [managed-policy precedence](https://claude.com/docs/third-party/claude-desktop/mdm).
The switch check returns a decision; it never writes or logs settings.

`claude_profile_records.py` discovers records within the resolved account and
store layout. It owns namespace selection, native abbreviated bundle paths and
source snapshots. Its `STORES` list is the only switch for which stores are
shared; the 1.0.0 beta shares the Code store and leaves Cowork untouched.
It does not guess identity from saved history or write tasks.
Profile paths follow the saved attachment, so an installer default change cannot
silently reassign an existing attachment or its restore record.

`claude_profile_identity.py` owns the account boundary for Plan 169. A native
session callback must match one exact host and CLI task pair. Cached account
state and the hashed workspace preference detect changes; they cannot select
an organization. Authentication values are neither read nor copied. Static
gateway identity comes from the existing device and local configuration.
A private router-local hash binds the account pair so a later sign-in cannot
inherit the previous account's copied tasks; the same hash keys the shared-task
ledger. The coordinator must hold both profile locks before creating that
binding; this helper does not start a copy.

`claude_profile_publish.py` and `claude_profile_transaction.py` share the record
and bundle publication contract. They validate file generations before exclusive
renames and retain originals and journals when competing writes make recovery
ambiguous. Committed cleanup accepts a partly deleted before-image, so an
interrupted cleanup finishes on the next run. Private control directories
protect backups without changing the permissions of hard-linked attachments
outside the profile. Callers must stop Claude, hold both profile locks and
provide a private, fully prepared bundle.

`claude_profile_bundle.py` assembles the complete admitted bundle union before
publication. It uses the shared transfer rules and retains unique duplicate
content before retirement. Task files keep their exact bytes; transcript rows
keep every field and only relocate profile paths. A losing transcript copy that
holds rows the kept copy lacks leaves the task unshared, because publication
would delete it.
`claude_profile_history.py` separates foreign request
metadata from native response diagnostics while preserving messages and IDs.
Repairs to shared CLI transcripts retain a private original and recover through
a separate journal because those files sit outside the desktop bundle. A
completed repair's original is checked by content, not file identity, so a
copied home still validates; a writer that races the rename gets its file back
and the next run repairs the new content.

`claude_profile_sync.py` coordinates both directions under the two profile locks.
Only the current account pair participates, and on the subscription side only
its resolved organization; the gateway's organization is synthetic, so it spans
the account. The outgoing profile wins conflicts; unique bundle artifacts join
the union before duplicates are retired. Shared CLI history takes precedence
over an older bundle snapshot. A task with no transcript anywhere, or with
diverged transcripts, is left unshared and counted. Invalid tasks are reported
to the switch caller, which must keep the current mode until every in-scope
task is safe. Before either pass, the ledger retires copies of tasks deleted
since the last clean sync, and only a clean sync updates what it remembers. The
coordinator has no app-lifecycle authority.

`claude_profile_ledger.py` keeps a deleted task deleted. After a clean sync it
records, in a private router-home file, a digest of each copy of every task both
profiles hold once: record bytes, bundle tree and paths, never titles or
content. Tasks the sync left unshared or refused are not recorded. Presence
counts across the whole account, so an organization change never looks like a
delete. A remembered task missing from exactly one profile has its other copy
retired to that store's `.claude-profile-control-trash` folder while the copy
still matches; a changed copy stays and is shared again. Retirement reuses the
publication pattern: a journal, then exclusive renames of the record and then
the bundle. The next run undoes an interrupted retirement before deciding again.
Interrupted transfers are recovered first; an unreadable record or a second
copy keeps every copy, and a profile that lost every shared task at once, when
there was more than one, is treated as a reset. Nothing is hard-deleted, and a
trash entry that cannot be put back safely stays for inspection and fails the
switch.

`claude_desktop_platform.py` owns native app identity, graceful shutdown,
dialogs and owned shortcuts. It waits for known writers and their children. A
Linux identity check delegates to `desktop_linux.py`, which selects one XDG
desktop entry, resolves its supported command shape, and validates the matching
Electron `resources/app.asar` package metadata. It reads only `package.json`
from the archive and never launches the desktop command or wrapper. Linux
tray switching uses this verified entry and waits for bundled writers.
Native desktop acceptance remains separate from these source and filesystem checks. A
process that execs another program keeps its start time and stays tracked; an
exited process still waiting for its parent (a zombie) can no longer write, so
it counts as gone. Before the quit request, an unknown writer or unreadable
process list refuses the operation, and a refused request ends it at once.
After a request that was sent, the wait decides the outcome, even when the
request timed out, because Claude may still close once its own confirmation is
answered. Processes that are quitting can briefly fail a check,
so a failed check, including a reused process ID, is retried until the deadline
and only a clean check ends the wait. Its macOS lifecycle helpers take an
`app` (bundle id, plus the executable names only that app may run) that
defaults to Claude; Switch Codex passes the ChatGPT app's, which lists no such
names, so unrelated standalone clients do not seed its writer set.
On macOS, bundle discovery uses Spotlight metadata because AppleScript app
lookup launches a closed app. Browser-owned native messaging hosts do not seed
the writer set, and crash reporters (any `crashpad_handler`) never join it:
they write only crash reports and can outlive an app update by days. Actual
app descendants remain tracked after reparenting.
Descendant discovery precedes rejection of an otherwise unknown Claude process,
because Desktop's Code executable can live outside its application bundle.
`claude_profile_launch.py` resolves the current installed release and dispatches
the requested action. `claude_profile_hook.py` owns only its exact SessionStart
callback entry and captures the focused native account identity asynchronously.
It never copies history, and uninstall preserves unrelated user hooks. The
callback runs Python with `-P`, so a file in the session's project folder can
never stand in for a module it imports.

`packaging/codex_switch_config.py` owns the three managed Codex blocks. The
default is `codex_config.build_block` unchanged, so a never-switched install
and older Codex builds see nothing new. `switched` is root keys only: Codex's
active provider becomes `scg_router`, which needs no OpenAI sign-in, sends
`x-scg-codex-route` and reads `routed-models.json`, and
`approvals_reviewer = "user"` stays, as in every managed block, because
attach moves the owner's own line into the receipt and this route refuses
ChatGPT's reviewer. `switched_back` is the default plus `scg_router` with
sign-in on, so threads started while switched still resume. The Codex receipt
entry records the variant (`variant`, absent until the first switch), and
`client_choice.attach_codex` rebuilds it on every install and update.
`switch` and `restore` are the only writers that change it. `switch` writes the config first, then the receipt, with the config
put back if the receipt write fails; `restore` undoes a switch, putting both
back. While Codex is switched, `tools/disable.py` (and so a
service-only install), `--uninstall` and `--rollback` refuse and leave its
settings as they are.

`packaging/codex_desktop_switch.py` owns the native desktop connection transition. It
moves an attached install to the other variant, holding the installer lock
throughout, and a hand-edited block refuses before anything is asked. Each
run appends one line to `logs/codex-switch.log` (docs/runtime-files.md).
`codex_switch_transaction.py` owns pending markers, proof and restoration of the owned settings.
Its Windows rollback guard verifies exit again if reopening may have launched the app.
An unavailable rollback shutdown keeps the pending marker and preserves the current configuration.
Windows Codex discovers the current Store package through native APIs and checks
registration before lifecycle actions. Process snapshots use Toolhelp metadata
and native token reads; they do not start PowerShell. A busy installation offers a Cancel window while
Switch Codex waits up to sixty seconds, before discovering the current app and settings.
Its process snapshot queries owners only for package processes, named writers,
descendants and previously tracked PIDs. Vanished processes do not invalidate a scan;
an unreadable relevant process still refuses. Windows CLI selection checks the package
boundary, executable header and `codex-cli` version before preflight and proof share it.
Only package-relative selection diagnostics enter the log; no Codex install path is persisted.
Windows confirmation names the full close and stopped tasks. Shutdown allows five seconds
for window closure, then ends verified surviving processes within a fifteen-second deadline.
Settings remain pending until proof and a visible reopened package window succeed.
Failure restores the previous owned settings and attempts fresh-package reopening.

`switched` is strict. It needs `codex_route.ready`, a subscription install
(no-subscription mode already runs without sign-in), exactly one ChatGPT app
(Codex) with its bundled CLI at the verified platform installation, and a verified
exit. It then writes a pending marker, calls `codex_switch_config.switch` and
proves the result with `codex_config_proof`: that CLI, started as an app
server on `~/.codex`, must load the config and report no managed
`model_provider` and no account. Any doubt refuses before the dialog; a failed
proof puts back the previous receipt entry and the block exactly as
config.toml held it, the owner's latest model pick included, through
`codex_switch_config.restore`, and reopens the app.

Switching back is the only way out of `switched`, since detach, uninstall and
rollback refuse while switched, so it depends on nothing it can lose. It runs
no proof: it only returns to the install's own block plus the provider entry.
Windows requires a current package identity and verified exit in both directions.
Mac and Linux retain their manual quit and reopen path when the app cannot be identified.

A switch that refused before writing needs no undo, and any refusal after the
quit reopens the app unchanged. A marker left by a run that stopped halfway is
kept when its switch was written and needs no proof or proves; anything else
is rolled back. Windows first obtains consent and verifies exit, then settles the
pending configuration and verifies reopening. Cancellation leaves the marker pending.

`packaging/codex_switch_offer.py` owns the automatic offers. The updater
calls it after every pass that holds the update lock, the minute Express job
included, and swallows anything it raises. It reads the router's
`codex-usage-limit.json` itself, because the router's reader needs Python
3.14, so its parsing and five-hour rule are copies that a test pins to
`ai_router/usage_episodes.py`. On macOS, for a Codex install in subscription
mode that has `APP`, it offers Switch Codex once per episode from an affected
desktop build, and the way back once Codex is switched and the episode has
ended or the installed ChatGPT app is at or above `FIXED_IN`. The dialog is
only the offer: its action opens Switch Codex, which asks before it changes
anything. `APP` is the one place the Switch Codex app's location is named.

`packaging/codex_switch_app.py` owns that app. Every Codex attach and update
builds or refreshes it on a Mac when Codex is attached in subscription mode
and either the installed ChatGPT app is at or above `AFFECTED_FROM` or Codex
is switched right now, so older Codex builds see nothing new. Otherwise it
removes an app it owns, but never while Codex is switched, because the app is
the way back. Detach and uninstall remove it through `tools/disable.py`,
which refuses while switched. The app is ours when its bundle id matches and
its Info.plist names this router home, so a run for another home (a test's)
never removes it. It runs `codex_switch_launch.py`, a copy in the router
home, under the router's own Python, which follows `current` to that
release's `codex_desktop_switch.py` and names an older release in one plain
message. `claude_desktop_platform.install_mac_app` builds it and both Claude
launchers, staged and then swapped in, and refuses an app it does not own. A
failed build prints one line and never fails an install.

## Distribution (outside the request path)

`desktop_control.py` owns the redacted desktop status and fixed action IDs.
It calls the existing client switchers, setup, support and update owners.
`desktop_service.py` uses the platform service lifecycle for bounded restart.
`desktop_model.py` gives native shells and the fallback window identical actions.
`desktop_menu.py` runs one shell per installation and graphical session.
On Mac, a session-scoped reopen request tells that shell to open its menu.
Fallback windows run one selected action and then close.
It serializes actions in a worker, while native menus stay responsive.
`desktop_startup.py` owns per-user startup entries and the persistent preference.
Only explicit choices write that preference. Windows defaults missing or invalid choices to On.
`desktop_launch.py` follows retained setup resources, independently of inference rollback.
Closing the shell never stops routing. Polling is silent and makes no model calls.
`native_resources.py` consumes only this target's signed Resources descriptor.
It verifies archive size, checksum and matching core identity before retention.
Installation owns its lock; failed menu delivery preserves the previous setup pointer.
Same-version installs and cached update checks retry missing controls independently of service health.
`native_resources_publish.py` validates all five archives before `publish_feed.py`
uploads immutable resources and signs the channel document containing their map.

`infra/` owns the update feed as code (repository-only templates, deployed from a checkout): the certificate stack, the private
bucket, the CloudFront distribution, the DNS alias, and the tag-only
publisher role. `tools/publish_feed.py` owns
release publication: it turns a built `dist/` into the feed's
`<channel>/latest.json` and the GitHub Release document.
`tools/publish_first_install.py` owns the first-install assets: the pinned
`runtimes.json` and `runtimes/*`, plus the `bootstrap/*` wrappers. The
router imports neither: hosts read the feed through `packaging/feed.py`, which
stays the client-side owner of origin and channel resolution.

`packaging/release.py` parses normal and Express tags; Express is feed
urgency on stable or beta, never a third channel or a package-version suffix.
The platform backends own a separate minute Express job alongside the regular
four-hour job. Both use `update_launch.py` (also installed as
`express_launch.py`) and `updater.py`; an update-parent lock serializes
them while the child installer retains its own installation lock.

## Transitional owners (do not entrench)

- `packaging/service.py` keeps the feed/state/cross-platform helpers
  (`health`, `wait_version`, `ensure_serving`, `install_lock`, `rotate_log`) and
  thin delegations for the installer's launchd bindings; the launchd
  rendering/reload half lives in `packaging/launchd.py` with the darwin backend
  (`packaging/platforms/darwin.py`), landed by Plan 103.
- `ai_router/providers.py` holds the Responses adapters and dispatch;
  `compaction_summary.py` owns bounded summary-model selection and requests;
  a key/region-matched availability snapshot gates summary disclosure before
  any history-bearing request; Jev is global-only and is skipped on regional
  routes, which use the region-bound summary path;
  the outgoing projection lives in `outbound.py`, failure policy in
  `upstream.py`, page markup in `setup_page.py`, shared transport in
  `transport.py`, and dispatch in `protocols/`.
- `ai_router/subscription_discovery.py` fetches Codex's native subscription
  catalogue; `subscription_catalogue.py` validates it and composes the
  effective roster without turning local configuration into entitlement data.
  `subscription_recovery.py` refreshes missing native membership before a
  resumed request is rejected, using the same account and client version.
  Concurrent requests share the refresh; external routes never use it.
  `ai_router/catalogue.py` + `models.py` + `live_refresh.py` share client
  projection duties through `model_metadata.py` (pure normalization) and
  `clients/` (capability projection, picker visibility); the served
  instruction text and its capped delegation roster live in the
  `model_instructions.py` leaf (Plan 154).
- Client activation lives in `packaging/codex_config.py`: the Codex block
  (its Switch Codex variants in `codex_switch_config.py`), picker
  preservation, the seeded startup model, the managed `[desktop]`
  preferences, guidance, and receipts. `--client none` runs the router
  lifecycle without touching client settings; absence of a client
  selection in legacy state means Codex. Subscription policy is per client:
  Responses follows `openai_mode`, Messages follows `anthropic_mode` when
  set, else the legacy `openai_mode` fallback.

## Acceptance gates are distinct

Source, packaged imports, native lifecycle, real-client tools, billing, and
release acceptance are different gates. Record client and OS evidence by
version; a global model tier never asserts every combination works.

## Jev consumer: compaction evidence

`jev_compaction.py` owns `state(home)` and
`summary(model, key, items, defn, home=None, ask=None) -> str | None`.
The two summary assignments in `ExternalResponsesProvider.compact` and
`compact_trigger` use it before falling back to `self.summarize`. The
external-only `compaction_call` gate is unchanged: subscription threads and
ordinary turns never reach Jev. Dependencies flow providers -> consumer ->
decisions/compaction/tool_runs -> leaves. Upstream facts remain in `provider_defs`.

The case-sensitive `jev-compaction` home file is read per compaction, with
`ROUTER_HOME` respected. `shadow` evaluates but returns `None`; `on` returns
kept text. Other, absent, empty or unreadable values mean off. The original
items are never modified. `remember(items, summary)` and the V1 summary and
V2 `ocx1:` envelopes consume the returned string unchanged. There is no new
capsule, replay module or request-path dispatch branch. Commands and the
TypeSafe data-sharing and billing disclosure are in
[operations](operations.md#experimental-compaction).

The consumer matches complete calls/results by `call_id`, rejects orphans or
ambiguous IDs, and selects at most 16 pairs by descending output size. It
never questions the first item, anything from the latest user message onward,
the newest six items, prior compactions, discovery outputs, agent messages
or developer/system messages. Pinning either member pins the whole pair;
unselected pairs stay verbatim.

One batch carries `{task, retained, candidates}`. Evidence uses
`compaction._item_text`, excluding opaque reasoning; candidate outputs carry
only `ok|error, N chars (omitted)`. Each item's text is capped at 2000, then
500, then 120 characters; if the body, including model and questions, still
exceeds 32 KiB, the newest 64 retained entries are kept at 500, then the
newest 32 at 120, then the newest 16 at 60, and the state records how many
older entries it left out. A real compaction carries hundreds of items, and
refusing those meant the feature never ran; thinning keeps the newest
evidence. It is not one-way safe: less evidence lowers the coverage score
(fewer pairs count as covered) and the "call still matters" score too, which
can turn a truncation into a drop. Both instructions therefore name
`retained_omitted` and forbid inferring coverage from absence. If even the
smallest step cannot fit, no partial state is sent.
Retained evidence never includes another candidate, so two candidates cannot
justify deleting each other. Candidate IDs are `p1..pn`; every instruction
names its backticked state path because Jev cannot see question IDs.

Two `noul` propositions ask whether the pair's task-relevant facts are
already covered by retained evidence, and whether knowing the call happened
still matters. These are probabilities of propositions, not importance scores.
The conservative experimental `THRESHOLD = 0.90` is applied directly to each
returned value, and both propositions are read positively: a pair drops only
when the facts count as covered *and* the call no longer matters; covered
evidence whose call still matters keeps the call with a shortened output; an
uncovered pair is kept verbatim. An earlier revision compared both values
below the threshold, which deleted exactly the pairs the judge had called
uncovered; the benchmark measured it and the polarity is now pinned by tests.
The first 300 output characters and the removed character count are kept, and
no re-run advice is added, since idempotency is not known here. Otherwise keep
both verbatim, in original order. The threshold needs
shadow calibration; the previous live trial's 0.69 on a plainly true fact
shows why the scores are not assumed production-quality calibration.

Any decision refusal, malformed/partial answer, invalid history, oversized
request or rendered text over 40% of the model row's context window returns
`None`. The byte ceiling uses `turn_budget.BYTES_PER_TOKEN`; an unknown window
also declines. The existing summarizer then runs unchanged. Logs contain only
mode, counts, byte sizes, elapsed time and a closed-set error code.

This is a one-shot T0 judgment with untrusted input, owned by the router
consumer; deterministic code validates the result before selecting text.
The paid-call budget is zero when off and at most one per eligible compaction,
using the decision client's five-second socket timeout. That timeout is not a
whole-run wall-clock guarantee. There are no retries, fallback models, decision
cache, model-selected tools or loops. Persistent writes, harmful-replay
coordination and broad-autonomy controls are not applicable to this consumer:
it returns text, without mutating history or executing tools. Reassess those
controls if it gains writes, retries, tools or per-turn authority.

`tests/test_jev_compaction.py` owns offline flag, selection, immutability,
failure, byte-budget and V1/V2 contracts. `tests/test_decisions.py` retains
wire validation, while packaging and import-graph tests enforce delivery and
dependency direction. Source implementation and offline acceptance do not
prove live calibration, deployment or release acceptance. No paid trial is
part of this change.
