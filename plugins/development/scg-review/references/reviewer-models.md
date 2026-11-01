# Reviewer model policy

Read the bundled [model routing policy](reviews.md) immediately before each
review, together with applicable host/project requirements. That release copy
defines model-agnostic selection, bounded availability fallbacks and escalation.
It is synchronized from the canonical optimal-subagents skill; do not add a
second model table here or rewrite user instructions during plugin installation.

Explicit exact-model requirements still take precedence. Otherwise an
eligible fallback is permitted without a new permission question. Preserve the
work and report `BLOCK` if no allowed model can complete the pass; do not switch
runtimes, credentials or data policy to evade the requirement.

Record requested and returned model/effort for each pass and the reason for a
material substitution. Absent returned fields are `unverified` and do not block;
a known mismatch invalidates the pass. The receipt records the actually requested
successful-pass identity, never a selected model that failed before execution.
Confirm full-scope review output; a successful dispatch is not review evidence.

The plugin supplies no credentials or provider adapter. Its setup check proves
local prerequisites only; actual review calls establish model availability.
Codex is the delivered runtime. Other clients need separately verified adapters.

## Exact Codex child evidence

Before spawning each pass, record the parent's actual thread ID and the
assignment start time with a UTC offset. Keep the returned `agent_id` and
the completion time. Never infer IDs from names, timing or a model label.
On Codex V1 the returned ID matches the child's HTTP `thread-id`; recheck
this contract with `tools/probe_agent_identity.py` after client upgrades.

After the child finishes, resolve the installed router release from its
`current` pointer and run its inspector from that release directory:

```sh
python3.14 -m ai_router.inspect_requests --agent-summary --json --limit 100 \
  --thread-id <agent-id> --parent-thread-id <parent-id> \
  --since <assignment-start-with-offset> --until <completion-with-offset> \
  --model <requested-model> --expected-effort <requested-effort>
```

This is a read-only, credential-free lookup. `records` preserve each request,
attempt and report source. The summary never filters away a mismatching retry.
Compaction and non-turn helper records are counted separately. Coverage is
always `retained_records_only`: rotation, limits and an interrupted process
can leave gaps, so it is not proof that every inference was observed.
When the page is full, `limit_reached` is true and matching fields remain
unverified; retained mismatches and contradictions still invalidate the pass.

Use `Upstream reported: <model>; effort: <reported value or unverified>` in
the recap, alongside `Requested: <model> at <effort>` and the coverage limit.
Do not label provider reports as independent model attestation or an effort
echo as measured reasoning compute. Only use a returned receipt value when
that field's summary is `provider_reported_match`; retain the supporting IDs
and sources in review notes. A `mismatch` or `contradictory` field invalidates
the pass even if another attempt matches. Missing or partial reports remain
unverified. Never use `/health served_models`, the compatibility response
header or the reviewer's self-description as proof. An older router, absent
headers, an unknown parent ID or another client leaves identity unverified;
do not guess, alter configuration or make extra paid calls to fill the gap.
