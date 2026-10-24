# Analysis Playbook

Use this reference for financial statements, KPIs, variance analysis, cash interpretation and the
confidence language that goes with them. It is independent of the accounting system; report names
below are generic and the source runbook maps them to the system's actual reports.

## Statement Priority

- Income statement: revenue, cost of sales, gross profit, operating expenses, EBITDA, net profit
- Balance sheet: assets, liabilities, equity, working capital, liquidity
- Cash flow: operating, investing, financing, free cash flow
- Budget versus actual: variance amount, variance percent, favourable or unfavourable
- AR or AP ageing: buckets, DSO, DPO, overdue exposure

## Report Selection

| Question is about | Start with | Then |
| --- | --- | --- |
| P&L, revenue, expenses, margins | income statement report | department, class or entity breakdown |
| Assets, liabilities, equity, working capital | balance sheet report | account detail for the lines that moved |
| Cash, burn, liquidity, runway | cash flow report | balance sheet cash detail and bank registers |
| Budget, forecast or plan versus actual | budget versus actual report | saved variance views, then a query pattern |
| Overdue invoices, collections, DSO | AR ageing report | saved ageing views by customer or entity |
| Open bills, vendor exposure, payment timing | AP ageing report | saved views by vendor or due date |

Financial statement figures come from the system's report engine. Rebuilding them from transaction
lines misses consolidation, currency translation, eliminations and sign conventions; use line-level
queries for operational breakdowns and for explaining movements, not for the statement itself.

## Presentation Reminders

Follow the organisation's reporting framework (IFRS and AASB in Australia, US GAAP, or local GAAP);
label management or non-statutory measures (EBITDA, adjusted EBITDA, pro forma) and reconcile them to the
statutory figure.

- Income statement: revenue, cost of revenue, gross profit, operating expenses, operating profit, other income or expense, tax, net profit. No "extraordinary items" line.
- Balance sheet: receivables net of allowance; property and equipment net of depreciation; current and non-current split for debt, leases and deferred revenue; equity components distinct when material.
- Cash flow: indirect method unless the source provides another; tie net profit to operating cash flow; tie ending cash to the balance sheet before anything board-ready leaves your hands.
- Tax-inclusive versus exclusive: GST or VAT sits on the balance sheet, not in revenue or expense. Gross invoice totals are not revenue.

## KPI Defaults

Income statement:

- Gross margin percent = gross profit / revenue
- Operating margin percent = operating profit / revenue
- EBITDA margin percent = EBITDA / revenue
- Revenue growth percent = change in revenue / prior period revenue
- Function cost percent of revenue = function cost / revenue (R&D, sales and marketing, G&A)

Balance sheet:

- Current ratio = current assets / current liabilities
- Quick ratio = (cash + receivables) / current liabilities
- Working capital = current assets minus current liabilities
- DSO = receivables / (trailing three-month revenue / days in those months)
- DPO = payables / (trailing three-month cost of sales / days in those months)

Cash flow:

- Free cash flow = operating cash flow minus capital expenditure
- Burn rate = monthly net cash outflow
- Cash coverage (runway) = cash / monthly operating cash outflow
- Rule of 40 (software businesses) = revenue growth percent + free cash flow margin percent

State the formula inputs when a KPI is disputed or unusual.

## Variance Analysis Method

Classification:

- Favourable for revenue when actual exceeds plan; favourable for expense when actual is below plan.
- Material when the variance exceeds the configured percentage or amount threshold (see SKILL.md Analysis Defaults).
- Escalate below threshold when the pattern suggests churn, pricing pressure, a control break or repeated deterioration across periods.

Driver decomposition:

- Revenue or cost of sales: price effect versus volume effect where the data supports it; mix when segments are available.
- Compensation: headcount, rate, mix, timing and attrition effects.
- Other operating expenses: headcount-driven, volume-driven, discretionary, contractual, one-time, and timing or phasing.
- Foreign currency: separate translation effect from underlying movement when entities report in different currencies.

Present the top two or three drivers with amount and percentage each; the residual can be one line.

## Preliminary Data and Confidence

- Open period: say the result is preliminary and name what is still missing when known (payroll, revenue recognition, accruals, FX revaluation, intercompany).
- Confidence levels, always with the reason:
  - High: closed period, reconciled data, report-engine figures.
  - Medium: open period with known gaps, or figures from saved views rather than statements.
  - Low: missing, inconsistent or partial data, or user-supplied figures that cannot be verified.

## Anomaly Rules

Before escalating, check whether the anomaly is explained by known seasonality, a documented one-time
item, or a reclassification with an offset elsewhere.

Escalate when you find:

- revenue contraction beyond normal seasonality
- gross margin compression
- unusual expense spikes
- a worsening ageing profile
- low runway or liquidity stress
- unbalanced intercompany activity
- stale reconciling items
- large or round-number journal entries with weak support
- suspense or clearing balances, or transactions missing dimensional coding
- a gap between the balance sheet control account and the operational subledger view (unapplied payments, write-offs never taken, or a real reconciliation break)
