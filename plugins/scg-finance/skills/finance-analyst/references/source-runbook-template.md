# Source Runbook Template

Copy this file to `references/<system>-runbook.md` (for example `myob-runbook.md`,
`quickbooks-runbook.md`, `sage-runbook.md`) and fill every section. Add the new file to the Task Routing table and the
Source Modes table in SKILL.md. Keep the method in SKILL.md unchanged; a runbook only teaches the skill
how to read one system safely.

State at the top whether the system is a ledger (Xero, NetSuite, MYOB) or a cash, payments or spend
platform (Airwallex, Stripe, a bank feed); the latter reconcile to the ledger and never replace it.

A runbook is complete when an analyst who has never seen the system can, from this file alone: confirm
they are connected to the right environment, find the accepted report for each statement, know the call
limits, and fill the Entity Profile facts listed in SKILL.md.

## 1. Connection and Health Check

- Tool or connector name as it appears in the session, including any prefix the client adds.
- Environment identifiers (production versus sandbox or demo) and how to verify which one you are on.
- The harmless read call that proves connectivity. Never use a write as a smoke test.
- How to classify failures: not connected, stale session, reauthorisation required, degraded tool.

## 2. Tool Inventory

Table of every tool the connector exposes, grouped as report, saved view, record, query, metadata, write.
Mark which are read-only. State which write tools exist even if the skill never calls them.

## 3. Read Routing

Order of preference (report engine, saved views, record reads, raw query) and why. Name the accepted
report for: income statement, balance sheet, cash flow, trial balance, budget versus actual, AR ageing,
AP ageing, general ledger detail. Note required parameters (dates and their format, entity, currency,
book, consolidation).

## 4. Budgets and Retries

Maximum read calls per user request, page sizes, when to stop paging, and which errors may be retried
once (typically rate limits and transient gateway errors only). Never retry authentication, permission,
validation or unknown failures.

## 5. Write Policy

Default read-only. If writes are possible, the exact preconditions: explicit user instruction naming the
record and effect, environment and role verification, metadata preflight, duplicate or current-state
check, one mutation, read-back, no automatic retry. If writes are not possible, say so.

## 6. Discovery Probes

For each Entity Profile fact in SKILL.md, the call or query that establishes it, in this order:
fiscal calendar, entity structure, accounting books, modules and features, trailing twelve months revenue
for the materiality tier, saved views inventory, period status. Prefer a dedicated tool over a query.
State the fallback when a probe fails and what to record in the profile.

## 7. Sensitive Data

Name the tools that return bank account numbers, routing codes, card details or personal contact data,
and the rule for them: use aggregate fields only, never echo the identifiers, never save them in notes
or the Entity Profile.

## 8. Quirks

Known behaviours that produce wrong numbers if ignored: sign conventions, consolidation boundaries,
tax-inclusive totals, fields that are null when a feature is off, metadata calls that fail, date formats,
fiscal calendars that vary by entity.

## 9. Tool Visibility Check

Connectors expose different tool subsets depending on version, plan, role permissions and client. State
how to recognise a partial session (which tools should exist, what their absence means, who can fix it)
so the analyst reports "cannot read X through this connector" instead of approximating.

## 10. Keep Organisation Facts Out

Do not record any organisation's own facts here (entities, calendars, books, account identifiers,
accepted reports, schema issues). Those belong in that organisation's Entity Profile, established by the
probes in section 6 and persisted per SKILL.md, so the skill stays usable by any company. No
credentials, tokens, client identifiers or callback URLs anywhere in a runbook.
