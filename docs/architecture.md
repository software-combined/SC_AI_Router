# Router architecture: domain ownership

Single-page map of where new work goes. The dependency direction is inward:
leaves know nothing about their consumers. Verified against current source;
transitional owners name the plan that will move them.

## Domains and direction

```
registry / capabilities / image_items (leaves: model facts, stdlib + dataclasses only)
  ^            ^
  |            |
catalogue / models / live_refresh / apply_catalogue (client projections)
  |
agent_handoffs / compaction / tool_adapter / discovered (request normalization)
  |
providers (Responses adapters) + claude (Messages adapters)
  |
protocols (explicit method/path dispatch table; no policy of its own)
  |
transport (Prepared, hop-header rules, raw stream, header relay)
  |
router (HTTP control: auth, body limits, drain/inflight, relay)
```

Rules:

`agent_handoffs.py` owns collaboration alias schemas and native-name restoration;
`sse.py` owns shared event framing without provider-specific argument rewriting.

1. `registry.py` imports stdlib only. Nothing in `ai_router/` may make it
   import a client, CLI, installer, or HTTP module. Client listing and config
   modules consume it; never the reverse.
2. HTTP transport (`router.py`) owns loopback auth, body limits,
   drain/inflight, and connection cleanup. Protocol representation lives in
   `providers.py` (Responses/Messages) and `claude.py` (Messages ingress).
3. Upstream adapters own target/credential construction. OpenRouter headers
   start fresh every request; subscription headers never accompany an
   OpenRouter request.
4. Installer orchestration (`packaging/install.py`, `service.py`,
   `updater.py`) calls one explicit platform backend. Unsupported OS is an
   explicit refusal. Backends do not import runtime providers or client
   catalogue policy.
5. A client is not a provider and an OS is neither. New clients reuse a
   proven wire protocol; a new protocol lands only after its contract is
   verified against the installed client version.
6. `packaging/` file-based imports (`spec_from_file_location`) avoid
   depending on a third-party distribution named `packaging`. Installer
   scripts stay Python 3.9-compatible; the runtime requires 3.14.

## Distribution (outside the request path)

`infra/` owns the update feed as code: the certificate stack, the private
bucket, the CloudFront distribution with its viewer-request token gate, the
DNS alias, and the tag-only publisher role. `tools/publish_feed.py` owns
release publication: it turns a built `dist/` into the feed's
`<channel>/latest.json` and the GitHub Release document.
`tools/publish_first_install.py` owns the first-install assets: the pinned
`runtimes.json` and `runtimes/*`, plus the `bootstrap/*` wrappers. The
router imports neither: hosts read the feed through `packaging/feed.py`, which
stays the client-side owner of origin, token and channel resolution.

## Transitional owners (do not entrench)

- `packaging/install.py` still dispatches `darwin` vs `linux` inline with a
  `systemd_manager()` two-valued flag (Plan 056 extracts `packaging/platforms/`).
- `packaging/service.py` mixes launchd/plist/feed/state helpers (Plan 056
  re-homes the launchd half with the darwin backend).
- `ai_router/providers.py` keeps Responses shaping plus failure
  description; shared transport lives in `transport.py` and dispatch in
  `protocols/` (Plan 062 landed the split; full protocol file moves remain
  open).
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
