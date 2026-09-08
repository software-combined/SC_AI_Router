# Changelog

## Unreleased

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

## 0.5.0

- Offer only the four Claude Latest aliases: Opus, Fable, Sonnet, and Haiku.
  Remove the previously pinned Opus 5 and Fable 5.1 picker entries on upgrade.
- Add DeepSeek V4 Pro 0813, V4 Flash 0731, and V4 Flash Vision Exp with
  current reasoning levels, input modalities, and token limits. Retain
  the original 0423 identities for existing tasks.
- Models without advertised effort controls can onboard with reasoning
  disabled; mandatory or unknown reasoning capabilities still fail closed.
- Newly added models remain Preview until paid Codex runtime probes pass.
- Install one global subagent-discovery rules block in Codex's active
  global AGENTS file, preserving existing instructions. Updates replace
  only the owned block; uninstall removes it. Rules are not repeated in
  the model catalogue and do not override permissions or delegation bans.

## 0.4.8 (first-run key window)

First-run setup and plan reconciliation from the audit brief, committed on
`codex/isolated-install-state`, not yet deployed (live router still runs
the pre-restructure prototype; see Plan 047 section 2):

- The router serves a first-run key window at `/<token>/setup/<nonce>`
  (Plan 047 G): single-use short-lived nonce, same-origin POST check, key
  validated against OpenRouter before anything is stored, owner-only key
  file, mode question asked up front, nonce closed on success. The generic
  DNS-rebinding rejection is unchanged for everything else.
- The router boots keyless while a fresh setup nonce is pending; every
  billable path still fails closed until a key resolves. `install --setup`
  mints the link and opens it instead of exiting without a key.
- `codex_router/router.py` stands at 256 lines against the 250 soft limit,
  pinned in the source-limits baseline with this justification: the loopback
  setup route shares the authenticated socket by design and all of its logic
  lives in the new `setup.py`; the router holds dispatch lines only.
- Plans truthfully reconciled: 041/043/045 marked implemented-not-accepted,
  044/046 partial, 042's two inaccurate plan-text claims corrected in-file,
  obsolete worktree instructions removed, request-cap and repository
  decisions recorded as settled, hourly hot-reload noted deferred.
- Residual risk: the setup window needs a live browser run before release;
  key validation calls OpenRouter but is never billed.

## 0.4.7 (acceptance harness slice)

Harness repairs from the audit brief, committed on
`codex/isolated-install-state`, not yet deployed (live router still runs
the pre-restructure prototype; see Plan 047 section 2):

- Compaction failure now fails verification: the probe raises instead of
  printing a status line and exiting zero, for both failed turns and
  protocol errors.
- New legs: `--compact-then-switch` compacts first and then retrieves the
  exact tool-result marker on another model; `--compact-twice` exercises
  repeated compaction; `--switch-to` replaces the hardcoded switch target
  so smaller-context models can be covered; `--expect-error` asserts a
  named rejection (unsupported effort, Grok's tool ceiling) exits clean
  while anything else still fails.
- Media evidence is attached, not discarded: `--image` sends a solid-red
  PNG and `--audio` a silence clip, with byte counts printed. Models with
  image input must name the color; text-only models pass by completing
  through the strip path. Wire shapes follow the canonical app-server
  protocol (`image`/`audio` items with data URLs).
- `CODEX_BIN` overrides the desktop binary so the legs above are proven
  offline against a scripted fake app-server (12 tests); isolated routers
  gain `restart()` for compact-restart-switch acceptance to build on.
- Residual risk: image/audio wire shapes and the color assertion still
  need one live paid run per modality before release.

## 0.4.6 (tool identity slice)

Tool-history, onboarding, and served-model fixes from the audit brief,
committed on `codex/isolated-install-state`, not yet deployed (live router
still runs the pre-restructure prototype; see Plan 047 section 2):

- Namespaced custom-tool history now converts exactly like its flattened
  definition: replayed calls and results take the wire name with no
  namespace, matching what the response leg already expects. Previously
  the guard missed namespaced entries entirely and survivors kept the
  wrong name.
- Served-model capture no longer depends on tool adaptation: tool-free
  200 responses are forwarded byte-identical while recording their model
  from JSON bodies and `response.completed` SSE events, for both
  providers. Error and malformed bodies stay untouched and unrecorded.
- `models add --probe` follows preview-activate-verify-promote: the
  candidate is written as preview first (the file-baked registry cannot
  route it otherwise), verified through an isolated router with its own
  home, port, token and catalogue, and only a pass promotes it to
  verified. `--dry-run` no longer bills a probe, and an explicit `--tier`
  still decides without probing.
- Alias display names refreshed from live `alias_target` data (four tilde
  rows); wire slugs, vendors, and all other fields untouched. Catalogue
  descriptions no longer double the vendor prefix on alias names.
- Residual risk: isolated probes bill the key and need the desktop app,
  so they stay owner-gated like all paid probes.

## 0.4.5 (compaction contract slice)

Compaction fixes from the audit brief, committed on
`codex/isolated-install-state`, not yet deployed (live router still runs
the pre-restructure prototype; see Plan 047 section 2):

- V2 `compaction_trigger` turns on OpenRouter models are answered inline
  with exactly one `ocx1:` compaction item briefed by the local
  summarizer; the trigger is never forwarded upstream. Contract proven
  against lidge-jun/opencodex f7f890f (MIT): trigger arrives as a normal
  non-streamed /responses call and the client fatals unless exactly one
  compaction item returns. Subscription traffic still flows to OpenAI,
  which mints its own blobs natively. `comp_hash` stays null.
- The summarizer rejects explicitly incomplete results
  (`incomplete_details.reason`) instead of installing a cut-off summary.
- An oversized newest message truncates to its tail instead of yielding
  an empty transcript.
- Discovered tool schemas persist per summary to `discovered-tools/`
  (owner-only, capped, insertion-ordered eviction) and chain across
  repeated compactions, so V1, V2, and restarted routers all resolve the
  same entry. Residual risk: live Codex acceptance of a real V2 trigger
  turn still needs a paid long-thread probe before release.

## 0.4.4 (installer lifecycle slice)

Lifecycle fixes from the audit brief, committed on
`codex/isolated-install-state`, not yet deployed (live router still runs
the pre-restructure prototype; see Plan 047 section 2):

- The pre-replacement Codex config is now backed up before the marked
  block is rewritten; previously the file was truncated first, so a crash
  between the two steps lost the backup.
- Uninstall runs the restore script with the installed home, checks that
  the restore actually happened, and aborts without stopping services
  when it did not. A failed restore used to be ignored while the agents
  were booted out anyway.
- `--version` rolls back to a previously installed release directory and
  health-checks it (restoring the prior pointer on failure) instead of
  trying to unpack the JSON feed document as a bundle. Only installed
  releases can be restored; the feed carries the latest bundle only.
- A failed first install removes the `current` pointer it created, so a
  retry reinstalls instead of reporting a never-served version as
  up to date.

## 0.4.3 (isolated-install slice)

Clean-install and configuration fixes from the audit brief, committed on
`codex/isolated-install-state`, not yet deployed (live router still runs
the pre-restructure prototype; see Plan 047 section 2):

- Fresh installs configure the static picker catalogue by default: the
  router serves no `/models`, so omitting `model_catalog_json` left a
  fresh picker with nothing to read. `--static-catalogue` stays accepted
  as a no-op.
- Fresh picker catalogues now list the subscription roster alongside the
  OpenRouter registry entries. `catalogue --merge` seeds missing roster
  slugs from the sibling state file as stubs and never rewrites existing
  rich entries. Plan 039's live `/models` remains the proper replacement.
- The no-subscription config block keeps root keys (`model_provider`,
  `model_catalog_json`) above the `[model_providers.scg_router]` table,
  uses the Plan 043 spike key name `SCG_ROUTER_TOKEN` instead of a
  per-port variable nothing provisions, and always points at the catalogue.
- Updates without `--openai-mode` keep the installed mode from state
  instead of silently rewriting a no-subscription block as a subscription
  block; the receipt records the installed mode.
- The updater agent is bootstrapped on fresh installs and carries
  `--home` always plus `--feed` when explicitly pinned. An explicit feed
  is pinned in `home/feed` (channel resolution otherwise); scheduled
  re-invokes no longer pin a channel-resolved feed.

## 0.4.2 (Plan 047)

Router correctness and installer fixes, committed on
`chore/no-request-cap-guard`, not yet deployed (live router still runs
the pre-restructure prototype; see Plan 047 section 2):

- Compaction keeps the newest transcript tail and names tools; runs
  before request preparation and holds a drain slot, so a release
  landing mid-compaction no longer loses the work.
- Discovered tools survive compaction; catalogue stubs are completed
  from discovered schemas instead of blocking them.
- Upstream 429 maps to retryable 503 with `Retry-After`.
- Summariser pinned to the lowest supported effort with a higher
  output cap; unreadable reasoning blobs stripped for OpenRouter
  models; image blocks stripped for text-only models.
- Installer seeds the picker catalogue (`catalogue --merge`) and
  writes `model_catalog_json` only with `--static-catalogue`.
- `/health` reports `served_models` (which upstream model actually
  served); tilde aliases display upstream alias names.
- CI fails if a request cap is reintroduced; `packaging/VERSION` is
  semver (`0.4.2`) and matches `pyproject.toml`.
- Internal router bugs surface as 500 with a traceback instead of 400.
- Upstream `openai-model` header is pinned to the requested slug so a
  rerouted model never triggers a mismatch warning; `/health` keeps
  reporting which model actually served.
- Release feed carries a monotonic `serial`; the installer refuses feeds
  older than the last accepted one and records it in `feed-serial`.
- OpenRouter picker entries carry the shared prompt in
  `model_messages.instructions_template` instead of the legacy
  `base_instructions` field.
- Fresh installs write the subscription-side model roster into runtime
  state (previously missing, so the router refused to start); existing
  state missing the roster is backfilled, never overwritten.

## 0.4.0 (Plan 041)

First installer release: `packaging/release.py` builds a deterministic
versioned bundle with `MANIFEST.json` and `latest.json`;
`packaging/install.py` (stdlib, Python 3.9+) verifies the checksum and
manifest, self-tests the bundle, swaps releases atomically with
health-check rollback, manages the LaunchAgents and daily update check,
and inserts the Codex config block. `packaging/install.sh` and
`packaging/install.ps1` are thin wrappers around the installer. GitHub
releases publish on `v*` tags with a beta channel.
