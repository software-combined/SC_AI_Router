# Installed runtime files

An install unpacks the release bundle into its release directory. This page
lists the runtime modules in that bundle; the bundle also carries the
packaging modules that install and update the router, the licence and notice
files, and the markdown documentation (`README.md` and `docs/*.md`) so an
installed host can read the same pages the repository shows.
`packaging/release.py` holds the full bundle inventory. State, activation
receipts, catalogues, backups and logs are never part of a release bundle and
are never copied between machines.

`ai_router/router.py`, `ai_router/providers.py`, `ai_router/claude.py`,
`ai_router/media.py`, `ai_router/video_provider.py`,
`ai_router/media_origin.py`, `ai_router/media_cli.py`,
`ai_router/external_provider.py`,
`ai_router/image_provider.py`, `ai_router/protocols/images.py`,
`ai_router/claude_compat.py`,
`ai_router/availability.py`, `ai_router/snapshot_store.py`,
`ai_router/registry.py`, `ai_router/credentials.py`,
`ai_router/request_context.py`, `ai_router/request_lease.py`, `ai_router/outbound.py`,
`ai_router/tool_adapter.py`, `ai_router/tool_history.py`, `ai_router/tool_aliases.py`,
`ai_router/agent_handoffs.py`, `ai_router/handoff_response.py`,
`ai_router/sse.py`, `ai_router/outcome.py`,
`ai_router/attempt_policy.py`, `ai_router/stream_errors.py`,
`ai_router/capabilities.py`, `ai_router/compaction.py`,
`ai_router/compaction_summary.py`,
`ai_router/jev_compaction.py`, `ai_router/decisions.py`,
`ai_router/compaction_result.py`, `ai_router/history_portability.py`,
`ai_router/history_items.py`, `ai_router/tool_runs.py`,
`ai_router/external_history.py`,
`ai_router/standalone_outputs.py`, `ai_router/discovered.py`,
`ai_router/errors.py`, `ai_router/redaction.py`, `ai_router/candidate.py`,
`ai_router/candidate_evidence.py`,
`ai_router/setup.py`, `ai_router/setup_page.py`, `ai_router/key_store.py`,
`ai_router/key_dialog.py`, `ai_router/key_prompt.py`, `ai_router/runtime.py`,
`ai_router/dialog_tool.py`,
`ai_router/catalogue.py`, `ai_router/local_services.py`,
`ai_router/live_refresh.py`, `ai_router/models.py`,
`ai_router/apply_catalogue.py`, `ai_router/activation.py`,
`ai_router/__init__.py`, `ai_router/__main__.py`,
`ai_router/model_metadata.py`, `ai_router/model_refresh.py`,
`ai_router/winacl.py`, `ai_router/winsecurity.py`, `ai_router/image_items.py`,
`ai_router/turn_budget.py`,
`ai_router/model_prompt.py`, `ai_router/model_prompt_page.py`,
`ai_router/model_policy.py`,
`ai_router/subscription_roster.py`, `ai_router/subscription_catalogue.py`,
`ai_router/subscription_discovery.py`, `ai_router/subscription_recovery.py`,
`ai_router/retired_slugs.py`,
`ai_router/clients/__init__.py`, `ai_router/clients/codex.py`,
`ai_router/clients/registry.py`, `ai_router/clients/roster.py`,
`ai_router/transport.py`, `ai_router/subscription_fallback.py`,
`ai_router/codex_route.py`, `ai_router/routed_models.py`,
`ai_router/usage_episodes.py`,
`ai_router/subscription_history.py`, `ai_router/context_recovery.py`,
`ai_router/provider_defs.py`, `ai_router/upstream.py`, `ai_router/ingress.py`,
`ai_router/relay.py`, `ai_router/tool_merge.py`, `ai_router/atomic_write.py`,
`ai_router/stream_relay.py`, `ai_router/stream_events.py`,
`ai_router/stream_attempt.py`, `ai_router/strip_retry.py`,
`ai_router/rejected_repair.py`,
`ai_router/state.py`, `ai_router/wire_shape.py`,
`ai_router/events.py`,
`ai_router/request_evidence.py`, `ai_router/inspect_requests.py`,
`ai_router/protocols/__init__.py`, `ai_router/protocols/responses.py`,
`ai_router/protocols/messages.py`, `ai_router/models.json`,
`ai_router/messages_errors.py`, `ai_router/messages_events.py`,
`ai_router/routed_base_instructions.txt`,
`ai_router/subscription_base_instructions.txt`, `ai_router/agents.py`,
`ai_router/model_instructions.py`,
`ai_router/agents_general.txt`, `ai_router/agents_dev.txt`,
`tools/provision_key.py`, `tools/global_instructions.py`, `tools/disable.py`.

Development probes, capture utilities, benchmark scripts and publishing
helpers are source-checkout tools and are not shipped to end users.

The feed-signature module lives with its consumers as
`packaging/feed_verify.py`: `packaging/feed.py` and `packaging/release.py`
load it as a sibling, never from the runtime tree. Signature enforcement is active: the updater verifies the detached
sidecar before parsing (Plan 145). Key rotation adds the new public key
beside the old one, ships, waits one fleet cycle, starts signing with the
new seed, ships again, then removes the old key.

Claude profile task sharing ships as sibling helpers under `packaging/`:
`claude_profile_rules.py`, `claude_profile_identity.py`, `claude_profile_hook.py`,
`claude_profile_history.py`, `claude_profile_records.py`,
`claude_profile_bundle.py`, `claude_profile_publish.py`,
`claude_profile_transaction.py`, `claude_profile_ledger.py` and
`claude_profile_sync.py`. `claude_desktop_platform.py` supplies native
lifecycle commands and loads `claude_desktop_policy.py` for read-only switch
restrictions, while `claude_profile_launch.py` follows the installed
release pointer for both Open Claude and Switch Claude; setup deletes the
router's own `claude_switch_launch.py` home copy once it rebuilds a 0.6
shortcut. Temporary stages,
before images and transaction manifests stay inside the local session store
and are never release members. Private control directories protect backups;
POSIX attachment permissions stay unchanged so hard-linked originals elsewhere
are unaffected. Windows checks owner-only access. Recovery metadata includes store-relative paths, session IDs
and file digests, so it stays private. It contains no session text, credentials
or exception detail.

The empty `.claude-profile-switch.lock` in the router home coordinates Open and
Switch through the operating system. Its presence alone does not mean a switch
is running; the operating system releases the lock when the helper exits.

The installer also places `packaging/router_launch.py` and
`packaging/update_launch.py` beside the state directory as `router_launch.py`
and `update_launch.py`, so restarts and scheduled updates follow the pointer
without symlinks. Windows Task Scheduler runs those through the packaged
`packaging/task_launch.py` copied to `task_launch.py`, which routes the
task's output into `logs/`. On a Mac that gets the Switch Codex app,
`packaging/codex_switch_launch.py` is copied beside them as
`codex_switch_launch.py`; the app runs it under the router's Python, so it
follows the pointer the same way.

Windows task output also contains JSON launch, completion and failure events.
Their fields are task kind, UTC timestamp, numeric status and a safe error class.
Missing target scripts are recorded before execution. Windows failures before Python
starts require Task Scheduler History and last-result metadata.
Health-verified installation completion appends `installed <version>; health verified`
to `logs/update.log`, including direct, regular, Express and beta installation.
An attachment failure gets a separate event; unchanged checks and rollbacks make no installation claim.

## Codex usage-limit record

The router writes `codex-usage-limit.json` in its home when ChatGPT refuses a
Codex desktop request because the allowance has run out. It is machine state
like the catalogues: never bundled, never copied, and it holds nothing from
the request. It is the contract for the Switch Codex offer, so a reader may
parse the JSON directly, including packaging code on Python 3.9.

```json
{
  "seen_at": "2026-09-29T05:12:33+00:00",
  "resets_at": "2026-09-29T10:12:33+00:00",
  "client_version": "26.924.22138"
}
```

`seen_at` is when the episode started, in UTC with a `+00:00` offset, which
Python 3.9's `datetime.fromisoformat` reads. `resets_at` is when ChatGPT said
the allowance returns, in the same form, or `null` when it named no reset or
named one in the past or more than 31 days out. `client_version` is the Codex
desktop version from the request's User-Agent, digits and dots only, or
`null`.

Only one refusal counts: a ChatGPT subscription 429 whose body names
`error.type` `usage_limit_reached`, which is how Codex itself recognises a
spent allowance, from a request whose User-Agent carries the desktop's
`(Codex Desktop; <version>)` suffix. Other 429s are plain rate limits to
Codex; they and requests from the Codex CLI (`codex-tui`) never write the
file.

One episode is one limit period. It ends at `resets_at`, or five hours after
`seen_at` when `resets_at` is `null`. A refusal before then keeps `seen_at` and
`client_version` and can only change `resets_at`; a refusal after it starts a
new episode. The file is replaced atomically and is owner-only (0600). Nothing
deletes it when an episode ends, so a reader compares the times itself. A
missing, unreadable or malformed file means no episode, which is what
`usage_episodes.current(home)` returns as None. A failed write is logged as
`usage_episode_failed` and never changes the answer the client gets.

The updater remembers which Switch Codex offers it has made in
`codex-switch-offers.json` beside it, for the latest episode only:

```json
{
  "seen_at": "2026-09-29T05:12:33+00:00",
  "offered": ["switch", "back"]
}
```

`seen_at` names the episode, and a new episode starts with no offers made.
`switch` is the offer to move Codex to OpenRouter models; `back` is the offer
to return to the ChatGPT subscription. The offer is written before its dialog
appears and is owner-only (0600). A home that cannot be written therefore
shows no dialog rather than the same one every minute, and a dialog that
cannot be drawn is taken back off the list so a later pass offers it again.

## Switch Codex run log

Applying update checks append content-free records to `logs/maintenance.jsonl`.
The regular and Express tasks record launch, completion or failure.
Reconciliation records `repaired`, `unchanged`, `inactive`, `deferred`, `unhealthy`,
`conflict` or `failed` for the Codex attachment. Records contain no settings or keys.
A repaired attachment retains its original uninstall evidence in `activation.json`.
Verified normal attachments and repairs retain a `repair_notice` event to deduplicate the restart offer in
`update-notice.json`. A missing dialog leaves that offer pending.
An unsafe active recovery marks the existing assistant component as needing attention.

`desktop-preferences.json` records only an explicit startup choice.
Windows treats missing, unreadable or malformed preferences as On without rewriting them.
Verified resource advancement uses a quiet `--after-update` launch, independent of that choice.
The session lock prevents duplicates. A retained controller reloads the advanced resources.

Each Switch Codex run appends one JSON line to `logs/codex-switch.log`, so a
switch that refused can be diagnosed afterwards:

```json
{"at": "2026-09-30T12:31:05+10:00", "to": "switched", "open": ["ChatGPT", "browser_crashpad_handler"], "result": "The ChatGPT app (Codex) did not close. Quit it from the ChatGPT menu, close any Codex sessions in Terminal, then open Switch Codex again."}
```

`at` is the local time with its offset. `to` is the variant the run aimed
for, `switched` or `switched_back`, or `null` when it refused before choosing
one. `result` is `done`, `cancelled` or the message the person saw, which
never holds paths, settings, addresses or keys. `open` appears only when the
app did not close: the sorted file names of the executables still running
from the app bundle, never their paths or arguments, or `null` when the
process list could not be read. A line that cannot be
written never stops a switch, and the file ages out a month after its last
write, like the other logs.
