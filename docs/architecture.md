# Router architecture: domain ownership

Single-page map of where new work goes. The dependency direction is inward:
leaves know nothing about their consumers. Verified against current source;
transitional owners name the plan that will move them.

## Domains and direction

```
provider_defs (one definition per upstream, imports nothing) + errors,
redaction, sse, tool_merge, image_items, turn_budget, atomic_write, state,
events (leaves: no module-level local imports; events' one call-time state
lookup is the only exception)
  ^
  |
registry / capabilities (model facts; stdlib plus the provider table only)
  ^
  |
transport (Prepared, hop-header rules, raw stream, header relay) + upstream
(failure policy) + stream_errors (classification) + stream_relay (one stream
for relay.py): wire and failure policy, consumed by the adapters below
  ^
  |
catalogue / models / live_refresh / apply_catalogue (client projections)
  |
agent_handoffs / compaction / tool_adapter / tool_aliases / discovered
(request normalization)
  |
providers (Responses adapters) + claude (Messages adapters)
decisions (one typed-decision side-call: no policy, off the request path)
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
`standalone_outputs.py` projects readable peer messages and standalone outputs
into matched tool results for external requests; client history stays unchanged.
`subscription_history.py` owns the pure outgoing reasoning projection for
subscription Responses requests; it never edits persisted client history.
`context_recovery.py` adds fixed recovery guidance for client-declared context
resets on either Responses route. Codex owns saved history and executes its
retrieval tools; the router stores no assignment or transcript cache.
It also owns the exact legacy paragraph migration used by catalogue upgrades.
`stream_errors.py` owns shared HTTP/SSE context-error classification and applies
it to external Responses terminal events after tool adaptation. It preserves
successful frames and records semantic failure separately from the HTTP status.
`stream_relay.py` owns one upstream stream for `relay.py`: which frames are the
client's answer rather than plumbing, the bounded hold that lets a retry replace
plumbing instead of appending a second copy, the retry verdict, and opening
the retry itself. It is a
leaf beside `stream_errors.py`, never a dispatcher or a credential owner.

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
   Protocol representation lives in `providers.py` (Responses/Messages) and
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
  failure policy lives in `upstream.py`, page markup in `setup_page.py`,
  shared transport in `transport.py`, and dispatch in `protocols/`.
- `ai_router/catalogue.py` + `models.py` + `live_refresh.py` share client
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

## Proposed Jev consumer: compaction evidence

At `155b268`, 2026-09-18 AEST; design, not implementation. Jev supplies
small semantic judgments, not a summary, planner or permission check. Choose
(a), compaction, first: narrow exposure and unchanged model/effort. Routing
(b) fits Jev's primitives too, but changes every turn's capabilities, billing
and cache behavior. Defer its ingress at `router.Handler._owned_post` before
`policy.select_provider`; `ai_router/policy.py` does not exist.

**Boundary.** Keep `providers.compaction_call`'s external-only V1/V2 gate.
Call proposed `compaction_decisions.prune_for_summary(items, *, defn, key,
region, mode='off') -> list` immediately before `compaction.transcript_for_summary`
inside `ExternalResponsesProvider.summarize`. Dependencies flow providers ->
consumer -> decisions/compaction -> leaves. Keep policy out of the adapter,
retain original items for user extraction and `remember`, and change neither
summary validation nor envelopes. Extract orchestration if necessary; never
grow a baselined file or add packaging machinery.

**Installed-host switch (proposed, not implemented).** Store `jev-compaction`
beside `channel` in the active router home. Accept trimmed `off` or `shadow`;
absent, unreadable, empty or invalid means off. `prune` is not accepted until
evaluated. The composition layer reads the file before eligible compactions
and passes `mode`; the wire adapter never reads host configuration. No restart.
For the default home, set the shell variable below; substitute the actual
service home for custom installations. These commands are inert until the
consumer ships. Reading shows the configured value; only `shadow` enables.

| Shell | Select home | Enable shadow | Disable | Read setting |
|---|---|---|---|---|
| macOS/Linux | `RH="${ROUTER_HOME:-$HOME/.codex/mixed-model-router}"` | `printf 'shadow\n' > "$RH/jev-compaction"` | `printf 'off\n' > "$RH/jev-compaction"` | `cat "$RH/jev-compaction"` |
| PowerShell | `$rh = if ($env:ROUTER_HOME) { $env:ROUTER_HOME } else { Join-Path $HOME '.codex/mixed-model-router' }` | `Set-Content "$rh/jev-compaction" shadow -Encoding ascii` | `Set-Content "$rh/jev-compaction" off -Encoding ascii` | `Get-Content "$rh/jev-compaction"` |

Opt-in permits eligible text to TypeSafe only within existing data policy.
Use the verified global definition and external key; regional/other routes
skip. No subscription headers, normal-turn calls or global fallback.

**Efficient judgment.** Deterministic code matches complete pairs and protects
instructions, mutations, errors, delegation, discovery, opaque items and the
latest two tool runs. Unrecognized tool semantics or ambiguous IDs mean keep;
do not parse arbitrary shell commands for safety. Evaluate at most eight
read-only pairs from the actual summary window, largest first. Skip exact
duplicates already decidable in code and pairs the summarizer would omit.
Build `task`, `retained` and `candidates` as named text fields, capped at
16 KiB including questions; no secrets or raw transcripts. Incomplete evidence
means skip, never truncate.
`retained` must be immutable evidence guaranteed to survive transcript
budgeting, never another candidate: otherwise a batch can delete both copies.

One `ask(..., defn=defn, key=key, timeout=1.0)` batches independent
`question('noul', instructions)` judgments. Each instruction explicitly names
`candidates.p0.result` and asks whether its task-relevant facts are preserved
in `retained`, considering its call. Question IDs are invisible to Jev.
Do not equate probability with importance or multiply correlated judgments.
Use `choice` only for genuinely exclusive alternatives, with an unknown option.

**Acceptance/failure.** `0.99` is an evaluation candidate, not calibrated
permission to delete; the live trial passed no pair at that threshold.
Shadow submits at most one observation to a nonqueued daemon-worker slot and
returns original input immediately; busy means skip. All results are telemetry
only. A 520 (`upstream_error`) records a skipped observation, never a chat error,
negative judgment, model switch, extra turn or retry. Hold the slot until exit;
socket timeout does not guarantee total wall time. No fallback or transcript
logs. Any future pruning mode must keep all items on error, retain uncertain
pairs, bound foreground wait to two seconds and discard late results.

**Economics and proof.** Four batched judgments cost US$0.000028434 versus
US$0.00004578 for just two singles; savings are workload-dependent. Pin the
verified snapshot; no decision cache initially. Prompt/state/model changes
invalidate calibration; changed summaries can lose prefix-cache hits.
Measure actual transcript bytes, not removed history bytes: the 24,000-character
window may refill. Require offline V1/V2, pair-closure, retained-anchor,
immutability, nonblocking shadow/520, home-file modes, timeout, fallback,
regional and import/size tests. Compare Jev
with unchanged and deterministic-only baselines on held-out synthetic tasks;
automatic pruning needs zero critical losses, positive net benefit and
downstream task parity. The eight-call/4-KiB-per-call/US$0.03 trial is complete
(US$0.000224994), not calibration proof. No consumer, `score`, picker row or
per-turn steering is enabled. Details and primary sources: `compatibility.md`.
