# Read-only audit review brief

User request: audit the codebase for reorganisation/refactoring before adding
Windows, Linux, Claude Code and Kiro; produce clear domains, patterns, rules and
implementation plans. User explicitly authorised Muse 1.3 Contributor at xhigh
and requested an agent retry after earlier calls lost their briefs.

Work only from
`/Users/cyrilallart/Documents/Github/.worktrees/router-domain-audit-20260909`,
frozen source commit `6840312`. The parent owns all writes. Read-only reviewer:
do not edit any file, index or branch; do not run installs, services, client
configuration, cloud or paid/network probes; do not recursively delegate.

First acknowledge this exact task scope and the worktree path to the parent.
Read `/Users/cyrilallart/.codex/skills/improve/references/audit-playbook.md`,
especially Finding format and the relevant architecture/tests/security sections.

Then read `plans/2026-09-09-domain-architecture-audit.md` and draft numbered
plans 060 onward. Report only high-confidence material errors, missing extension
boundaries or implementation-plan ambiguities after opening the cited source.
Include source file/line, impact, confidence, fix effort/risk and minimal remedy.
Also identify needless abstractions or duplicated existing plans.

Runtime lane: validate 060 logging defect and 062 protocol/transport boundaries
against router.py, providers.py, claude.py and relevant tests. Do not interpret
domain as DNS; this is a code responsibility audit.

Architecture lane: validate installer/client activation and model projections,
bundle/import/test rules, and roadmap overlap. Draft 056-059 belong to another
writer under `/Users/cyrilallart/Documents/Github/.worktrees/router-plans-xplat`;
they may be read but must not be changed. Their reported live gates are not
evidence you independently verified.

Stop after one bounded pass. Send findings in your final report. Do not start
fixes, produce generic current-state deployment inventories, or inspect live
router state. The parent will independently verify your evidence.
