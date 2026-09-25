# Router architecture: domain ownership

Single-page map of where new work goes. The dependency direction is inward:
leaves know nothing about their consumers. Verified against current source;
transitional owners name the plan that will move them.

## Domains and direction

```
provider_defs (one definition per upstream, imports nothing) + errors,
redaction, sse, tool_merge, image_items, turn_budget, atomic_write, state,
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
(failure policy) + stream_errors (classification) + stream_events /
stream_attempt (frame kinds, the uncommitted attempt) + stream_relay (one
stream for relay.py): wire and failure policy, consumed by the adapters below
  ^
  |
subscription_discovery / subscription_catalogue + catalogue / models /
live_refresh / apply_catalogue (client projections and native discovery)
  |
tool_runs (the pairing model, on history_items alone) + agent_handoffs /
compaction / tool_adapter / tool_history / tool_aliases / discovered (request
normalization); external_history reads compaction's codec, never the reverse
decisions (typed-decision wire client, imports only provider_defs)
  |
jev_compaction (opt-in evidence selection, consumes decisions/compaction/tool_runs)
  |
outbound (each Responses route's ordered stage list over the stages above)
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

Rules:

`agent_handoffs.py` owns collaboration alias schemas and native-name restoration;
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
output and the summary transcript. `external_history.py` owns the two external
stages that read that codec: compaction items replay as readable text
(`rewrite_input`), and OpenAI-owned reasoning blobs go (`strip_reasoning_blobs`,
which the subscription retry repair reuses). The
switch boundary's run check, the custom-pair call map and Jev's candidate
pairing keep their own id rules (any truthy id and any later output; the last
custom call; ambiguous ids pinned), so moving them onto `pairs` would be a
behaviour change with its own review, not part of the move.
`outbound.py` owns the outgoing Responses projection (Plan 183 phase 2).
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
containers it changed. `agent_handoffs.add_plaintext_tools` returns the payload
with the alias metadata, `hint_full_lanes` and `rewrite_tool_history` return
the payload, and `rewrite_custom_pairs` returns the items. The external
turn-size fit follows the same rule: `turn_budget.fit` returns
`(payload, stats)`, and its image and tool-output trims copy only the path to
each trimmed block, never the whole body. The original body stays whole, so
the helper fallback's twin or a second route prepares again from it
with the same bytes. `tests/test_outbound_purity.py` pins this against every
replay fixture on both routes, the native-then-twin sequence and both trims.
Native passthrough still forwards the client's own bytes when nothing
changed.
`subscription_history.py` owns the pure outgoing projection of replayed
reasoning and the router's own compaction summary (sent as readable text) for
subscription Responses requests; it never edits persisted client history.
`rejected_repair.py` owns the Responses adapters' rejected-request repair
(Plan 183 step 2.5). Each adapter's `repair_rejected(prepared, described, raw)`
proposes at most one repaired `Prepared` for the one rejection it can justify:
the external annotation strip for an OpenRouter 400 that names no cause, and
the subscription `invalid_encrypted_content` repair of reasoning blobs and the
router's compaction summary. None means ineligible and a proposal without a
body means unchanged. A proposal opens no connection, reads no response, logs
nothing and never retries; `strip_retry.py` keeps the one-retry policy, the
`annotation_retry` lines and, until Plan 188's relay-owned attempt ledger, the
one send. The Messages adapters propose no repair.
`context_recovery.py` adds fixed recovery guidance for client-declared context
resets on either Responses route, finding the `<context_window>` message by the
same rule. Codex owns saved history and executes its
retrieval tools; the router stores no assignment or transcript cache.
It also owns the exact legacy paragraph migration used by catalogue upgrades.
`stream_errors.py` owns shared HTTP/SSE context-error classification and applies
it to external Responses terminal events after tool adaptation. It preserves
successful frames and records semantic failure separately from the HTTP status.
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
offering frames to the hold, what the client received by kind, the single
retry verdict (a provider failure before any forwarded byte, transient,
replay-safe), and opening the retry itself. A valid retry replaces the whole
uncommitted attempt; a retry that cannot open leaves the held verdict to
reach the client. These are leaves beside `stream_errors.py`, never a
dispatcher or a credential owner.
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
`agent_handoffs.steer_plaintext` still reads the live registry when it
rewrites a spawn target on the response side; that moves with the handoff
contract work.

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
   `transport.MAX_REQUEST_BYTES` (96 MiB) is the local hard ceiling on wire,
   decoded and prepared bytes for every route and encoding, checked by
   `ingress.read_body`, `router.Handler.admit` and again on every send in
   `transport.post_with_phases`; `Prepared.decoded_body_bytes` keeps a
   compressed passthrough from being under-counted. `runtime.MAX_BODY`
   (16 MiB) is only the threshold for the single large-request slot, which
   `router.py` holds until relay, repair, fallback and cleanup return.
   `turn_budget.BODY_BUDGET` shapes external Responses turns only; native
   bodies are forwarded whole. Protocol representation lives in `providers.py` (Responses/Messages) and
   `claude.py` (Messages ingress).
3. Upstream adapters own target/credential construction and are
   parameterized by one `ProviderDef`, never by a provider-name branch. A
   new external provider is a table entry plus registry rows; a provider
   with a different wire format is a new adapter class, never a branch in
   the request path. External headers start fresh every request;
   subscription headers never accompany an externally billed request.
   `decisions.py` is the one client for a provider's typed-decision endpoint
   (Jev today): it holds no policy and answers only what it can validate, so
   every consumer fails closed on its refusals and nothing runs it by default.
4. Installer orchestration (`packaging/install.py`, `bundle.py`,
   `service.py`, `updater.py`) calls one explicit platform backend;
   `bundle.py` owns the release lifecycle (verify, install, prune,
   rollback). Unsupported OS is an explicit refusal. Backends do not import
   runtime providers or client catalogue policy.
5. A client is not a provider and an OS is neither. New clients reuse a
   proven wire protocol; a new protocol lands only after its contract is
   verified against the installed client version.
6. `packaging/` file-based imports (`spec_from_file_location`) avoid
   depending on a third-party distribution named `packaging`. Installer
   scripts stay Python 3.9-compatible; the runtime requires 3.14.
7. `tools/` holds checkout-run helpers (local probes, scans, key ceremonies)
   that are invoked by the developer or by CI, not by an installed router;
   `packaging/` holds the modules an installed host executes. A new
   host-run script belongs in `packaging/`, even if nothing in `ai_router/`
   imports it. `packaging/release.py` globs every `tools/*.py` into the
   bundle, so a repo-only helper placed there ships to recipients; the one
   deliberate exception is `tools/disable.py`, the installed-host remover
   that `packaging/install.py` runs.

`plugins/` and `.agents/plugins/marketplace.json` host the SCG agent-plugin
marketplace outside the router dependency map: no `ai_router/`, `tools/` or
`packaging/` module imports from `plugins/`, and plugin scripts never import
router code.

## Client contract

`ai_router/clients/registry.py` is the one owner of who sees what: one row per
client, carrying the wire protocol the router already serves, the picker
predicate and the discovery predicate. Both Claude projections read it, and
`packaging/install.py` derives its `--client`/`--clients` choices from the
`ai_router/clients/roster.py` leaf, which is import-free so the installer can
spec-load it (`packaging/service.py::load`). Adding a client means:

1. a row in `ai_router/clients/registry.py` (and its id in the roster leaf);
2. a protocol the router already dispatches on -- `/responses` or
   `/v1/messages`, per `protocols/TABLE` -- or a STOP: a third protocol is a
   decision, not an edit;
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
`claude_desktop_switch.py` owns the macOS switch launcher and changes only
that mode after Claude exits normally; it never changes attachment or
credentials. Its stable `claude_switch_launch.py` entry point follows the
installed release pointer so the app survives updates and release pruning.

## Distribution (outside the request path)

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
  the outgoing projection lives in `outbound.py`, failure policy in `upstream.py`, page markup in `setup_page.py`,
  shared transport in `transport.py`, and dispatch in `protocols/`.
- `ai_router/subscription_discovery.py` fetches Codex's native subscription
  catalogue; `subscription_catalogue.py` validates it and composes the
  effective roster without turning local configuration into entitlement data.
  `ai_router/catalogue.py` + `models.py` + `live_refresh.py` share client
  projection duties through `model_metadata.py` (pure normalization) and
  `clients/` (capability projection, picker visibility); the served
  instruction text and its capped delegation roster live in the
  `model_instructions.py` leaf (Plan 154).
- Client activation lives in `packaging/codex_config.py`: the Codex block,
  picker preservation, the seeded startup model, the managed `[desktop]`
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
