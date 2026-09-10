# Kiro compatibility spike (Plan 065), 2026-09-10

Research only. No adapters, credentials, client mutation, paid calls, or
installation were performed. `kiro-cli` is not installed on this machine
(`command -v kiro-cli` returns nothing) and no Kiro IDE bundle is present,
so all version evidence below is official-source dated, with local version
fields recorded as `unverified`.

## Decision

| client | version | source checked | hook | protocol | auth/config ownership | offline evidence | runtime evidence | outcome | next gate |
|---|---|---|---|---|---|---|---|---|---|
| Kiro IDE | unverified (not installed) | Models overview 2026-09-10; custom-agent configuration reference for IDE 1.0 / CLI 3.0, 2026-09-10 | NO VERIFIED INFERENCE HOOK | n/a: no custom endpoint surface found | Kiro model service owns model selection; agent `model` selects a service ID only | models page lists supplied models and serving geographies with no endpoint setting; agent reference requires the ID to come from Kiro's model service with fallback-plus-warning otherwise | none | Negative spike: no supported custom inference hook established | Reopen only on dated official evidence of a custom inference endpoint setting, then a thin implementation handoff per Plan 065 step 3 |
| Kiro CLI | unverified (not installed) | CLI settings reference 2026-09-10; custom-agent configuration reference for IDE 1.0 / CLI 3.0, 2026-09-10 | NO VERIFIED INFERENCE HOOK | n/a: no custom endpoint surface found | `kiro-cli settings` owns chat/model-selection/tool/timeout knobs; inference stays with Kiro's managed service | settings tables list `chat.defaultModel` (a model-service ID) and `api.*` timeout knobs with no base-URL row; MCP `url` rows configure tools, not inference | none | Negative spike: no supported custom inference hook established | Reopen only on dated official evidence of a custom inference endpoint setting, then a thin implementation handoff per Plan 065 step 3 |

## Key distinctions held

- Custom-agent `model` selection is not inference routing: the ID must come
  from Kiro's model service and unavailable IDs fall back with a warning.
- MCP server support (including remote `url` rows) configures tool
  endpoints, not the client's own inference path.
- Third-party gateway/proxy projects demonstrate unofficial bridging, not a
  supported Kiro inference hook; they are out of scope for this spike and do
  not reopen the decision.

## Reopening evidence

A dated official Kiro page or versioned local help excerpt naming a custom
inference base URL/provider setting, its wire protocol, auth mechanism, model
discovery constraints, and config ownership/restore path, for the IDE and CLI
separately.
