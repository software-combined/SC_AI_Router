# Period Close and Controls

Use this reference for month-end, quarter-end or year-end close, reconciliation review, control health
and audit readiness. It is system-independent; the source runbook says how to check period status,
pending approvals and unposted items in a given system.

## Period Status Rule

Before presenting close-related numbers as final:

1. Confirm whether the accounting period is open or closed (and locked, where the system distinguishes).
2. Check pending approvals when they would affect reported results.
3. Check unposted transactions when the period is still moving.

Interpretation: closed means present as final unless later adjustments are known; open means say
preliminary; for pending approvals and unposted items quantify the count and approximate value where
available.

## Close Dependency Model

| Level | Tasks |
| --- | --- |
| 1 | Cash receipts and disbursements, payroll posting, depreciation and amortisation, routine AP accruals, intercompany posting |
| 2 | Bank reconciliation, revenue recognition, AR and AP subledger reconciliation, FX revaluation, remaining accruals |
| 3 | Balance sheet reconciliations, intercompany reconciliation, adjusting entries from reconciliations, preliminary trial balance |
| 4 | Tax provision, equity roll-forward, consolidation and eliminations, draft financial statements, preliminary flux analysis |
| 5 | Management review, final adjustments, hard close and period lock, reporting package distribution, forecast update |

A finding at one level usually blocks everything above it; say which level a blocker sits at.

## Standard Close Calendars

Five-day close:

- T+1: cash, payroll, AP accruals, depreciation, prepaid amortisation, intercompany
- T+2: revenue recognition, remaining accruals, subledger reconciliations, FX revaluation
- T+3: balance sheet reconciliations, intercompany reconciliation, eliminations, preliminary trial balance
- T+4: tax provision, equity roll-forward, draft financials, detailed flux, management review
- T+5: final adjustments, hard close, period lock, reporting package, forecast refresh

An accelerated three-day close only works when recurring entries, reconciliations and intercompany are
largely automated before period end. Use the organisation's own calendar from the Entity Profile when it
has one.

## Reconciliation Guidance

Reconciliation types: GL to subledger, bank, intercompany, roll-forward.

Classify reconciling items as timing difference, adjustment required, or requires investigation.

Escalation when no organisation policy exists (the same scale as SKILL.md):

- 31 to 60 days: monitor
- 61 to 90 days: root cause required
- over 90 days: stale item requiring management review

## Common Close Bottlenecks

- Late AP accrual inputs from departments
- Recurring manual journal entries
- Reconciliations started too late
- Delayed intercompany confirmation
- Management review happening only at the end of the process

## Internal Control and Audit-Readiness Checks

Apply whether or not the organisation is subject to a formal regime such as SOX; the checks are the same.

- Inactive users retaining system access
- Large round-number journal entries with weak support
- Stale reconciling items
- Suspense or clearing balances at period end
- Uncategorised or incompletely coded transactions
- Close tasks not completed before lock
- Approval workflows bypassed or approvals recorded after posting

When an issue repeats across periods, frame it as a potential control deficiency, not a one-off clean-up.

## Clarifying Questions

When the request is ambiguous, offer at most two of these rather than a list:

- "Do you want a department (or entity) breakdown?"
- "Should I check whether this is recurring or one-time?"
- "Do you want cash impact as well as P&L?"
