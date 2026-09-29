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
`ai_router/claude_compat.py`,
`ai_router/availability.py`, `ai_router/snapshot_store.py`,
`ai_router/registry.py`, `ai_router/credentials.py`,
`ai_router/request_context.py`, `ai_router/outbound.py`,
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
`ai_router/catalogue.py`, `ai_router/local_services.py`,
`ai_router/live_refresh.py`, `ai_router/models.py`,
`ai_router/apply_catalogue.py`, `ai_router/activation.py`,
`ai_router/__init__.py`, `ai_router/__main__.py`,
`ai_router/model_metadata.py`, `ai_router/model_refresh.py`,
`ai_router/winacl.py`, `ai_router/image_items.py`,
`ai_router/turn_budget.py`,
`ai_router/model_prompt.py`, `ai_router/model_prompt_page.py`,
`ai_router/model_policy.py`,
`ai_router/subscription_roster.py`, `ai_router/subscription_catalogue.py`,
`ai_router/subscription_discovery.py`, `ai_router/retired_slugs.py`,
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
`tools/probe_codex_runtime.py`, `tools/probe_model_discovery.py`, `tools/probe_context_budget.py`,
`tools/probe_context_recovery.py`, `tools/probe_handoff_recovery.py`,
`tools/probe_history_switch.py`, `tools/probe_media.py`,
`tools/probe_standalone_outputs.py`, `tools/probe_agent_handoffs.py`,
`tools/probe_parent_switch.py`, `tools/probe_claude_code.py`,
`tools/probe_candidate.py`,
`tools/appserver_probe.py`, `tools/provision_key.py`,
`tools/verify_runtime_pins.py`, `tools/check_installer_python39.py`,
`tools/check_policy_scans.py`, `tools/check_source_limits.py`,
`tools/check_acceptance_ledger.py`,
`tools/publish_feed.py`, `tools/publish_first_install.py`,
`tools/global_instructions.py`, `tools/disable.py`.

The feed-signature module lives with its consumers as
`packaging/feed_verify.py`: `packaging/feed.py` and `packaging/release.py`
load it as a sibling, never from the runtime tree. Signature enforcement is active: the updater verifies the detached
sidecar before parsing (Plan 145). Key rotation adds the new public key
beside the old one, ships, waits one fleet cycle, starts signing with the
new seed, ships again, then removes the old key.

The installer also places `packaging/router_launch.py` and
`packaging/update_launch.py` beside the state directory as `router_launch.py`
and `update_launch.py`, so restarts and scheduled updates follow the pointer
without symlinks. Windows Task Scheduler runs those through the packaged
`packaging/task_launch.py` copied to `task_launch.py`, which routes the
task's output into `logs/`.

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
