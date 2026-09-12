# Router architecture: domain ownership

Single-page map of where new work goes. The dependency direction is inward:
leaves know nothing about their consumers. Verified against current source;
transitional owners name the plan that will move them.

## Domains and direction

```
provider_defs (leaf: one definition per upstream, imports nothing)
  ^
  |
registry / capabilities / image_items (leaves: model facts, stdlib + dataclasses only)
  ^            ^
  |            |
catalogue / models / live_refresh / apply_catalogue (client projections)
  |
agent_handoffs / compaction / tool_adapter / tool_aliases / discovered
(request normalization)
  |
providers (Responses adapters) + claude (Messages adapters)
  |
protocols (explicit method/path dispatch table; no policy of its own)
  |
transport (Prepared, hop-header rules, raw stream, header relay) + upstream (failure policy)
  |
ingress (auth/rebinding, body limits, GET routes, error shaping) + relay (upstream loop)
  |
router (HTTP control: drain/inflight and POST orchestration)
```

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
  `clients/` (capability projection, picker visibility).
- Client activation lives in `packaging/codex_config.py`: the Codex block,
  picker preservation, guidance, and receipts. `--client none` runs the
  router lifecycle without touching client settings; absence of a client
  selection in legacy state means Codex. Subscription policy is per client:
  Responses follows `openai_mode`, Messages follows `anthropic_mode` when
  set, else the legacy `openai_mode` fallback.

## Acceptance gates are distinct

Source, packaged imports, native lifecycle, real-client tools, billing, and
release acceptance are different gates. Record client and OS evidence by
version; a global model tier never asserts every combination works.
