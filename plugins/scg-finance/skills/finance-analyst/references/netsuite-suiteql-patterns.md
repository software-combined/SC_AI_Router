# NetSuite SuiteQL Patterns

Starter patterns for when standard reports and saved searches cannot answer the question. The SuiteQL
tools are visible only to roles with REST Web Services permission; if `ns_runCustomSuiteQL` is absent,
none of this file applies and the runbook's report and saved-search paths are the whole toolkit. They are
templates, not tested production queries: replace placeholders, confirm tables with the metadata guard,
and label the output as an analytical view. Read [the NetSuite runbook](netsuite-runbook.md) first for
tool names, read order and call budgets.

Contents:

1. Conventions
2. Metadata guard
3. Subsidiary resolution
4. Period status
5. Pending approvals and unposted transactions
6. Variance patterns (budget, prior period)
7. Multi-subsidiary and consolidation patterns
8. Guardrails

## 1. Conventions

- Dates: always an explicit ISO mask, `TO_DATE('2026-07-01', 'YYYY-MM-DD')`. Never rely on the account's date preference and never use `MM/DD/YYYY` masks: an Australian user reading `01/07/2026` as 1 July gets 7 January.
- Placeholders such as `<START_DATE>` are ISO dates; `<SUBSIDIARY_ID>` comes from `ns_getSubsidiaries`.
- No `WITH` clauses. Some endpoints reject common table expressions, so every pattern below uses inline subqueries.
- The tool parameter is `sqlQuery`. Paging is the tool's job: 100 rows per page by default, with `numberOfPages` and `totalResults` in the response; stop after 10 pages unless the user widens scope.
- Date columns come back in the account's date preference. Wrap them: `TO_CHAR(ap.startdate, 'YYYY-MM-DD') AS startdate`.
- Never put `ROWNUM` in an aggregate (`GROUP BY`) query. It limits the input rows before they are summed and silently produces wrong totals. Use it only on row-level probes.
- `transactionline.amount` is in the transaction subsidiary's base currency, not the group's. Group by currency before summing across subsidiaries.
- Filter posted GL activity with `t.posting = 'T'` only. Do not add `approvalstatus = 2`: `approvalstatus` is null for record types without approval routing, so that filter drops valid posted rows. Use `approvalstatus` only when the question is about approvals.
- `NVL()` on nullable amounts and text.

## 2. Metadata Guard

Field and table availability varies by account configuration, enabled modules and role permissions.

Before the first use of a table in a session, call `ns_getSuiteQLMetadata(table)` once and cache the
result. If the metadata call errors (some accounts return HTTP 500 for `subsidiary` and `account` because
of a custom field the metadata service cannot resolve), that is not proof the table is unavailable. Run a
row-level probe instead:

```sql
SELECT id FROM <TABLE_NAME> WHERE ROWNUM <= 1
```

If the probe also fails, record the table as unavailable for this role and fall back one tier: SuiteQL to
saved search to standard report. Say what could not be verified; do not silently drop a column.

| Table | Used for | Common availability issue |
| --- | --- | --- |
| `accountingperiod` | period status, fiscal calendar | not queryable on every endpoint; fall back to `ns_runReport` date ranges and transaction-density inference |
| `budget` | budget variance | present only when budgets are loaded; some roles cannot read it even then, so an empty result is not "no budget" |
| `subsidiary` | entity resolution | OneWorld accounts only; prefer `ns_getSubsidiaries` |
| `transactionaccountingline` | book-specific amounts | present with Multi-Book Accounting; prefer `ns_getAccountingBooks` for the book list |
| `accountingbook` | book filtering | often not directly queryable; use `ns_getAccountingBooks` |
| `budgetcategory` | budget category filtering | often not directly queryable; filter `budget.category` by name |

## 3. Subsidiary Resolution

Call `ns_getSubsidiaries` and use the returned identifiers directly. Only if that tool is unavailable:

```sql
SELECT s.id, s.name, s.country, s.currency, s.iselimination, s.parent
FROM subsidiary s
WHERE s.isinactive = 'F'
ORDER BY s.name ASC
```

Never assume or hard-code subsidiary identifiers.

## 4. Period Status

```sql
SELECT ap.id, ap.periodname,
       TO_CHAR(ap.startdate, 'YYYY-MM-DD') AS startdate,
       TO_CHAR(ap.enddate, 'YYYY-MM-DD') AS enddate,
       ap.closed, ap.alllocked, ap.arlocked, ap.aplocked, ap.isadjust
FROM accountingperiod ap
WHERE ap.isquarter = 'F'
  AND ap.isyear = 'F'
  AND ap.startdate >= TO_DATE('<FROM_DATE>', 'YYYY-MM-DD')
ORDER BY ap.startdate DESC
```

Fiscal-year rows (`isyear = 'T'`) give the fiscal calendar. Accounts can hold several fiscal calendars
(different `startdate` for the same fiscal year name); pick the one attached to the subsidiary's fiscal
calendar, not the earliest match. `closed = 'F'` with `alllocked = 'T'` is a locked, unclosed period;
`isadjust = 'T'` marks an adjustment period.

## 5. Pending Approvals and Unposted Transactions

Pending approval (approval routing on, not yet approved):

```sql
SELECT t.recordtype, t.trandate, t.tranid, NVL(t.memo, 'No memo') AS memo,
       NVL(e.entityid, 'N/A') AS created_by, NVL(t.foreigntotal, 0) AS transaction_amount
FROM transaction t
LEFT JOIN employee e ON e.id = t.createdby
WHERE t.approvalstatus = 1
  AND t.posting = 'F'
  AND t.trandate >= TO_DATE('<START_DATE>', 'YYYY-MM-DD')
  AND t.trandate <= TO_DATE('<END_DATE>', 'YYYY-MM-DD')
ORDER BY t.foreigntotal DESC
```

Unposted in period (any reason):

```sql
SELECT t.recordtype, t.trandate, t.tranid, NVL(t.memo, 'No memo') AS memo,
       NVL(t.approvalstatus, 0) AS approval_status, NVL(t.foreigntotal, 0) AS transaction_amount
FROM transaction t
WHERE t.posting = 'F'
  AND t.void = 'F'
  AND t.trandate >= TO_DATE('<START_DATE>', 'YYYY-MM-DD')
  AND t.trandate <= TO_DATE('<END_DATE>', 'YYYY-MM-DD')
ORDER BY t.foreigntotal DESC
```

`foreigntotal` is the transaction total in transaction currency; present it as approximate exposure.

## 6. Variance Patterns

Prefer the Budget vs. Actual standard report or an existing budget saved search: they apply NetSuite's
budget matching and period roll-ups. Use these only when neither exists.

| Comparison basis | Use when | Pattern |
| --- | --- | --- |
| Budget table | budgets are loaded in NetSuite | A |
| Prior period actuals | no budget, or a period-over-period view | B |
| Saved search | a budget versus actual search exists | `ns_listSavedSearches` with keyword `budget`, then `ns_runSavedSearch` |

### Pattern A: Actuals vs Budget

```sql
SELECT
  act.account,
  act.account_type,
  act.actual_amount,
  NVL(pln.budget_amount, 0) AS budget_amount,
  act.actual_amount - NVL(pln.budget_amount, 0) AS variance_amount,
  CASE WHEN NVL(pln.budget_amount, 0) = 0 THEN NULL
       ELSE ROUND((act.actual_amount - NVL(pln.budget_amount, 0)) / ABS(pln.budget_amount) * 100, 1)
  END AS variance_pct
FROM (
  SELECT a.id AS account_id, a.fullname AS account, a.accttype AS account_type,
         NVL(SUM(tl.amount), 0) AS actual_amount
  FROM account a
  LEFT JOIN transactionline tl ON tl.account = a.id
  LEFT JOIN transaction t ON t.id = tl.transaction
    AND t.posting = 'T'
    AND t.trandate >= TO_DATE('<START_DATE>', 'YYYY-MM-DD')
    AND t.trandate <= TO_DATE('<END_DATE>', 'YYYY-MM-DD')
    -- Optional: AND t.subsidiary = <SUBSIDIARY_ID>
  WHERE a.accttype IN ('Income', 'Expense', 'CostOfGoodsSold')
    AND a.isinactive = 'F'
  GROUP BY a.id, a.fullname, a.accttype
) act
LEFT JOIN (
  SELECT b.account AS account_id, NVL(SUM(b.amount), 0) AS budget_amount
  FROM budget b
  JOIN accountingperiod ap ON ap.id = b.period
  WHERE ap.startdate >= TO_DATE('<START_DATE>', 'YYYY-MM-DD')
    AND ap.enddate <= TO_DATE('<END_DATE>', 'YYYY-MM-DD')
    -- Optional: AND b.subsidiary = <SUBSIDIARY_ID>
    -- Optional: AND b.category = <BUDGET_CATEGORY_ID>
  GROUP BY b.account
) pln ON pln.account_id = act.account_id
ORDER BY ABS(act.actual_amount - NVL(pln.budget_amount, 0)) DESC
```

Notes:

- Zero rows from the budget subquery means no budget rows matched the period, subsidiary or category, or the role cannot read `budget`. Say which before concluding there is no budget; fall back to Pattern B.
- `variance_pct` is NULL when budget is zero; present it as "n/a, no budget".
- Sign: for income accounts a positive variance means revenue beat plan; for expense accounts it means spend exceeded plan. Apply the favourable or unfavourable label before presenting.
- Apply the same subsidiary filter to both subqueries or the comparison is meaningless.

### Pattern B: Actuals vs Prior Period

```sql
SELECT
  cur.account,
  cur.account_type,
  cur.current_amount,
  NVL(pri.prior_amount, 0) AS prior_amount,
  cur.current_amount - NVL(pri.prior_amount, 0) AS variance_amount,
  CASE WHEN NVL(pri.prior_amount, 0) = 0 THEN NULL
       ELSE ROUND((cur.current_amount - NVL(pri.prior_amount, 0)) / ABS(pri.prior_amount) * 100, 1)
  END AS variance_pct
FROM (
  SELECT a.id AS account_id, a.fullname AS account, a.accttype AS account_type,
         NVL(SUM(tl.amount), 0) AS current_amount
  FROM account a
  LEFT JOIN transactionline tl ON tl.account = a.id
  LEFT JOIN transaction t ON t.id = tl.transaction
    AND t.posting = 'T'
    AND t.trandate >= TO_DATE('<CURRENT_START>', 'YYYY-MM-DD')
    AND t.trandate <= TO_DATE('<CURRENT_END>', 'YYYY-MM-DD')
  WHERE a.accttype IN ('Income', 'Expense', 'CostOfGoodsSold')
    AND a.isinactive = 'F'
  GROUP BY a.id, a.fullname, a.accttype
) cur
LEFT JOIN (
  SELECT a.id AS account_id, NVL(SUM(tl.amount), 0) AS prior_amount
  FROM account a
  LEFT JOIN transactionline tl ON tl.account = a.id
  LEFT JOIN transaction t ON t.id = tl.transaction
    AND t.posting = 'T'
    AND t.trandate >= TO_DATE('<PRIOR_START>', 'YYYY-MM-DD')
    AND t.trandate <= TO_DATE('<PRIOR_END>', 'YYYY-MM-DD')
  WHERE a.accttype IN ('Income', 'Expense', 'CostOfGoodsSold')
    AND a.isinactive = 'F'
  GROUP BY a.id
) pri ON pri.account_id = cur.account_id
ORDER BY ABS(cur.current_amount - NVL(pri.prior_amount, 0)) DESC
```

Notes: for prior-year same period shift both prior dates back twelve months; for prior month shift one
month. Label the output "current period vs prior period" so nobody reads it as a budget comparison. If
the two periods span different fiscal years for an entity, say so.

## 7. Multi-Subsidiary and Consolidation Patterns

SuiteQL cannot replicate NetSuite's consolidation engine. A SuiteQL sum across subsidiaries is a
pre-elimination aggregate in each subsidiary's own base currency, before currency translation and
minority interest. Label it "pre-elimination aggregate", never "consolidated".

| Need | Use |
| --- | --- |
| Consolidated P&L or balance sheet with eliminations | standard report at the parent (consolidated) subsidiary |
| Operational breakdown by subsidiary without elimination logic | breakdown pattern below |
| Intercompany AR and AP tie-out | tie-out pattern below |
| Which elimination entries posted in a period | elimination detection pattern below |
| Consolidated cash flow | standard Cash Flow report at parent level only |

### Breakdown by Subsidiary (Pre-Elimination Aggregate)

```sql
SELECT s.name AS subsidiary, s.country, c.symbol AS currency,
       NVL(SUM(tl.amount), 0) AS base_amount,
       NVL(SUM(tl.foreignamount), 0) AS foreign_amount
FROM transactionline tl
JOIN transaction t ON t.id = tl.transaction
JOIN subsidiary s ON s.id = t.subsidiary
JOIN currency c ON c.id = s.currency
WHERE t.recordtype = '<RECORD_TYPE>'
  AND t.posting = 'T'
  AND s.iselimination = 'F'
  AND t.trandate >= TO_DATE('<START_DATE>', 'YYYY-MM-DD')
  AND t.trandate <= TO_DATE('<END_DATE>', 'YYYY-MM-DD')
GROUP BY s.name, s.country, c.symbol
ORDER BY base_amount DESC
```

`base_amount` is in each subsidiary's currency; do not add rows with different currency symbols.

### Elimination Entry Detection

```sql
SELECT s.name AS elimination_subsidiary, a.fullname AS account, a.accttype AS account_type,
       t.tranid AS transaction_id, t.trandate AS post_date, NVL(t.memo, 'No memo') AS memo,
       NVL(SUM(tl.amount), 0) AS elimination_amount
FROM transactionline tl
JOIN transaction t ON t.id = tl.transaction
JOIN subsidiary s ON s.id = t.subsidiary
JOIN account a ON a.id = tl.account
WHERE s.iselimination = 'T'
  AND t.posting = 'T'
  AND t.trandate >= TO_DATE('<START_DATE>', 'YYYY-MM-DD')
  AND t.trandate <= TO_DATE('<END_DATE>', 'YYYY-MM-DD')
GROUP BY s.name, a.fullname, a.accttype, t.tranid, t.trandate, t.memo
ORDER BY t.trandate DESC
```

Zero rows for a period with known intercompany activity: `FLAG: Elimination entries not detected for
this period. Consolidated output may overstate intercompany revenue and expense.`

### Intercompany AR and AP Tie-Out

```sql
SELECT s.name AS subsidiary, c.symbol AS currency, a.accttype AS account_type, a.fullname AS account,
       NVL(SUM(tl.amount), 0) AS balance
FROM transactionline tl
JOIN transaction t ON t.id = tl.transaction
JOIN subsidiary s ON s.id = t.subsidiary
JOIN currency c ON c.id = s.currency
JOIN account a ON a.id = tl.account
WHERE t.posting = 'T'
  AND s.iselimination = 'F'
  AND t.trandate <= TO_DATE('<END_DATE>', 'YYYY-MM-DD')
  AND (LOWER(a.fullname) LIKE '%intercompany%'
       OR LOWER(a.fullname) LIKE '%due to%'
       OR LOWER(a.fullname) LIKE '%due from%')
GROUP BY s.name, c.symbol, a.accttype, a.fullname
ORDER BY s.name, a.accttype
```

Net the balances within each currency. A non-zero net is the intercompany gap: small means timing or FX
rounding (verify with both entities, check unposted revaluation); material means a missing intercompany
invoice, unapplied payment or booking error (escalate to the controller; do not close the period until
resolved). Across currencies, compare against the consolidated report rather than netting raw amounts.

For "consolidated with eliminations" requests: run the standard report at the parent, run the tie-out
and elimination detection first, and direct questions about cumulative translation adjustment to the
equity section of the standard balance sheet rather than deriving it in SuiteQL.

## 8. Guardrails

- No record mutation from a query workflow.
- Resolve identifiers to names before presenting.
- If report logic and query logic disagree, say so and explain which is authoritative (the report, for statement figures).
- State when a query is a best-effort analytical view rather than a tied report.
