# Muse first-turn rejection

Codex desktop can send `access_programs` with a fresh task. This is a
ChatGPT-specific field, so `ExternalResponsesProvider.prepare` removes it
before dispatch. `SubscriptionProvider.prepare` retains it. The boundary
does not change the requested model, reasoning effort, tool declarations or
tool-result history.

On 20 September 2026 AEST, a controlled comparison used the failing desktop
request in memory. Its 51 tools and instructions succeeded with essential
Responses fields. Adding `tool_choice` or `parallel_tool_calls` still
succeeded; adding `access_programs` alone produced the same unnamed Meta 400.
The earlier stripped retry also failed because its annotation list did not
include this field. Successful continuations were insufficient evidence that
the first-turn defect had been resolved.

Only structural counts, field names, token usage and fixed error categories
were retained. The temporary diagnostic module was removed from the candidate.
No request bodies, tool content or credentials were retained for this work.

The annotation retry remains bounded to one additional dispatch. Its
`annotation_retry` event records `eligible`, `attempted` and `outcome`:
`ineligible`, `unchanged`, `started`, `accepted`, `rejected` or
`transport_error`. Rejections include status and bounded classification
metadata. `accepted` means HTTP acceptance; semantic completion is established
by the normal stream outcome and client acceptance probe. A rejected retry
uses the ordinary failure policy, including credit, authentication and context
handling, and deterministic refusals are cached against the original request.

Offline regressions cover both Muse variants, first turns and tool-result
continuations, preserved subscription metadata, retry observability and final
error handling. Removing the field fix makes all four Muse boundary cases fail.
Live client and release evidence belongs in [Compatibility](compatibility.md).
