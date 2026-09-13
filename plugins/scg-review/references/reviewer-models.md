# Reviewer model policy

Read the bundled [model routing policy](reviews.md) immediately before each
review, together with applicable host/project requirements. That release copy
contains defaults, fixed effort, bounded availability fallbacks and escalation.
It is synchronized from the canonical optimal-subagents skill; do not add a
second model table here or rewrite user instructions during plugin installation.

Explicit exact-model requirements still take precedence. Otherwise a listed
eligible fallback is permitted without a new permission question. Preserve the
work and report `BLOCK` if no allowed model can complete the pass; do not switch
runtimes, credentials or data policy to evade the requirement.

Record requested and returned model/effort for each pass and the reason for a
material substitution. Absent returned fields are `unverified` and do not block;
a known mismatch invalidates the pass. The receipt records the actually requested
successful-pass identity, never a preferred model that failed before execution.
Confirm full-scope review output; a successful dispatch is not review evidence.

The plugin supplies no credentials or provider adapter. Its setup check proves
local prerequisites only; actual review calls establish model availability.
Codex is the delivered runtime. Other clients need separately verified adapters.
