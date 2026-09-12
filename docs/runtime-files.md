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
`ai_router/registry.py`, `ai_router/credentials.py`,
`ai_router/tool_adapter.py`, `ai_router/tool_aliases.py`,
`ai_router/agent_handoffs.py`, `ai_router/sse.py`,
`ai_router/capabilities.py`, `ai_router/compaction.py`,
`ai_router/standalone_outputs.py`, `ai_router/discovered.py`,
`ai_router/errors.py`, `ai_router/candidate.py`,
`ai_router/setup.py`, `ai_router/setup_page.py`, `ai_router/key_store.py`,
`ai_router/key_dialog.py`, `ai_router/key_prompt.py`, `ai_router/runtime.py`,
`ai_router/catalogue.py`, `ai_router/local_services.py`,
`ai_router/live_refresh.py`, `ai_router/models.py`,
`ai_router/apply_catalogue.py`, `ai_router/activation.py`,
`ai_router/__init__.py`, `ai_router/__main__.py`,
`ai_router/model_metadata.py`, `ai_router/model_refresh.py`,
`ai_router/winacl.py`, `ai_router/image_items.py`,
`ai_router/model_prompt.py`, `ai_router/model_prompt_page.py`,
`ai_router/model_policy.py`,
`ai_router/subscription_roster.py`, `ai_router/retired_slugs.py`,
`ai_router/clients/__init__.py`, `ai_router/clients/codex.py`,
`ai_router/transport.py`, `ai_router/subscription_fallback.py`,
`ai_router/subscription_history.py`,
`ai_router/provider_defs.py`, `ai_router/upstream.py`, `ai_router/ingress.py`,
`ai_router/relay.py`, `ai_router/tool_merge.py`, `ai_router/atomic_write.py`,
`ai_router/state.py`,
`ai_router/protocols/__init__.py`, `ai_router/protocols/responses.py`,
`ai_router/protocols/messages.py`, `ai_router/models.json`,
`ai_router/openrouter_base_instructions.txt`, `ai_router/agents.py`,
`ai_router/agents_general.txt`, `ai_router/agents_dev.txt`,
`tools/probe_codex_runtime.py`, `tools/global_instructions.py`,
`tools/disable.py`.

The feed-signature module lives with its consumers as
`packaging/feed_verify.py`: `packaging/feed.py` and `packaging/release.py`
load it as a sibling, never from the runtime tree. Signature enforcement
engages only once `FEED_PUBLIC_KEY` is configured (Plan 106's decision).

The installer also places `packaging/router_launch.py` and
`packaging/update_launch.py` beside the state directory as `router_launch.py`
and `update_launch.py`, so restarts and scheduled updates follow the pointer
without symlinks. Windows Task Scheduler runs those through the packaged
`packaging/task_launch.py` copied to `task_launch.py`, which routes the
task's output into `logs/`.
