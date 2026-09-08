# Changelog

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
