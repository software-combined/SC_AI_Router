# Xero Runbook

How to read Xero safely through the Xero connector for Claude (Xero's hosted MCP server at
`mcp.xero.com`) or an equivalent Xero MCP server. Read this before the first Xero call in a session.
The analysis method is in SKILL.md. Facts about a specific organisation belong in the Entity Profile,
not in this file.

Contents:

1. Connection and health check
2. Tool inventory
3. Read routing and parameters
4. Budgets and retries
5. Write policy
6. Quirks that produce wrong numbers
7. Discovery probes for the Entity Profile
8. Profile card, refresh and standing checks
9. Failure handling

## 1. Connection and Health Check

- Tools appear as `get_*` (for example `get_profit_and_loss`), sometimes with a connector prefix. A community or self-hosted Xero MCP server uses different names (`list-profit-and-loss`, `list-invoices`); map by purpose, not by name.
- Harmless connectivity check: `get_connected_organisations`. It returns every organisation the signed-in user connected, with an identifier, name and connection time. One Xero organisation is one legal entity and one ledger.
- If more than one organisation is connected, establish which one each call targets before quoting a figure. Responses carry the organisation's base currency; when a tool has no organisation parameter, state the organisation you believe answered and ask the user to switch the connector if it is not the one they meant.
- The Xero connector for Claude is read-only and session-only: it cannot edit invoices, post transactions or change anything, and retrieved data is not stored between sessions. Answers should carry Xero's links back to the source report, invoice or contact when the tool returns them.
- Tool visibility varies by connector version and by the client. Descriptions of one tool may name sibling tools that are not exposed in your session; check the tool list rather than assuming. Classify problems as: not connected (no Xero tools), partial (some tools missing; work with what is present and say what could not be read), reauthorisation required (authentication error), or degraded tool (one call fails while others work).

## 2. Tool Inventory

Xero connector for Claude, as observed in a live session (September 2026): fifteen tools, every one
read-only. All of the tools below except `show_invoices_summary` and `get_repeating_invoices` were
called successfully.

| Purpose | Tool | Notes |
| --- | --- | --- |
| Organisations connected | `get_connected_organisations` | no parameters; returns identifier, name and connection time per organisation |
| Organisation details | `get_organisation_info` | legal name, type, region, base currency, timezone, line of business, registration number |
| Financial year | `get_organisation_financial_year` | current financial year start and end dates |
| Income statement | `get_profit_and_loss` | `start_date`, `end_date`, optional `comparison_start_date` and `comparison_end_date`; totals, every account with provider-computed percentage change, accounting basis |
| Balance sheet | `get_financial_position` | snapshot as at today: current and non-current assets and liabilities, equity, cash, working capital |
| Cash | `get_cash_position` | cash balance, `amount_owed` (receivables) and `amount_due` (payables) as at today |
| Receivables ageing | `get_aged_receivables` | default tool for "who owes us", overdue and ageing buckets |
| Payables ageing | `get_aged_payables` | default tool for "who do we owe", unpaid, overdue, due soon |
| Sales invoices | `get_invoices`, `show_invoices_summary` | invoice-level detail and summary views |
| Supplier bills | `get_bills` | header or line-item detail, filters below |
| Repeating bills | `get_repeating_bills` | templates that regenerate bills on a schedule |
| Customers by revenue | `get_top_customers_by_revenue` | concentration baseline |
| Contacts | `get_contacts` | requires `contact_name` (substring search) or `contact_ids`; returns identifier, name, email |
| Repeating invoices | `get_repeating_invoices` | templates that regenerate sales invoices |
| Invoice summary view | `show_invoices_summary` | interactive summary for the client's user interface |

Xero's underlying Reports API (which these tools draw on) offers Profit and Loss, Balance Sheet, Trial
Balance, Aged Payables and Aged Receivables by Contact, Bank Summary, Budget Summary and Executive
Summary. A tool for Trial Balance, Budget Summary, manual journals, bank transactions or tracking
categories may not exist in the connector; when it does not, say the figure is unavailable through the
connector rather than approximating it from invoice lists.

## 3. Read Routing and Parameters

Use the smallest authoritative path:

1. Report tool for statement figures: `get_profit_and_loss`, `get_financial_position`, `get_cash_position`. These carry Xero's report logic (accrual versus cash basis, layout, base currency). Never rebuild a P&L by summing invoices.
2. Ageing tools for exposure: `get_aged_receivables`, `get_aged_payables`. Use them for any unqualified "unpaid", "overdue", "outstanding" or "due this month" question, even when phrased as a list.
3. Document tools for detail: `get_invoices`, `get_bills` scoped by contact, status or date window; `get_contacts` to resolve names to identifiers first. Pass every matched contact identifier in one call rather than one call per supplier.
4. Organisation tools for context: `get_organisation_info`, `get_organisation_financial_year`.

Parameter conventions observed in the live connector:

- Dates are ISO `YYYY-MM-DD`. Document tools filter on issued date (`issued_date_start`, `issued_date_end`) and due date (`due_date_start`, `due_date_end`) separately; ageing is by due date, revenue timing is by issue date.
- Report periods: `get_profit_and_loss` and `get_top_customers_by_revenue` default to the financial year to date on an accrual basis; pass `start_date` and `end_date` for another period and the comparison dates for a prior period. With an explicit period the P&L omits zero-balance accounts; with the default it lists every account, so filter to non-zero before presenting. `get_financial_position` and `get_cash_position` report as at today; an as-at date parameter was not accepted under the names tried, so for a historic balance sheet use the report link or the user's own export.
- Status filters: `get_invoices` takes a single value, `UNPAID` or `PAID`; `get_bills` accepted a list. The returned Xero status is finer (`DRAFT`, `SUBMITTED`, `AUTHORISED`, `PAID`, `VOIDED`, `DELETED`). Only `AUTHORISED` and `PAID` documents are in the ledger; drafts and submitted documents are not posted.
- Amounts come back as decimal strings with `amount_net`, `amount_tax` and `amount_total` separated, plus `currency_code` and `currency_rate`, and the response states `organisation_base_currency`. Use net amounts for P&L-consistent figures and totals for cash exposure.
- Pagination is one-based: `page`, with `requested_page_size` (30 observed), `page_item_count`, `total_page_count` and `total_item_count` in every response. Stop when `page` equals `total_page_count`.
- `include_line_items` on document tools enlarges responses considerably; request it only for line-level questions or attachment checks.
- Every report response carries `accounting_basis`, `last_refreshed`, `organisation_base_currency` and a `xero_report_link` (and the ageing tools a mobile link) to the source report; include the link when the user may want to verify. Percentage changes in the P&L are computed by Xero; quote them rather than recomputing.
- Xero's underlying reports can compare up to 12 periods, filter by one tracking category option and switch between accrual and cash basis; the connector exposes accrual by default. Ask which basis the user wants when cash and accrual would tell a different story; state the basis in the Scope line.

## 4. Budgets and Retries

Defaults an organisation can tighten in its Entity Profile:

- Up to 20 read calls per user request unless the user widens scope; page through document lists only when the question needs every row.
- The Xero API behind the connector enforces per-organisation limits (of the order of 60 calls per minute and a daily cap, with a small concurrency limit); a connector may add its own. Keep calls sequential and retry a read once, with back-off, only on a rate-limit or transient gateway error. Never retry authentication or validation failures.
- Prefer one report call over many document calls: a trailing-twelve-months P&L is one call; the same figure from invoices is many pages and still wrong (drafts, credit notes, tax).

## 5. Write Policy

The Xero connector for Claude has no write tools. If a different Xero MCP server with write tools
(create invoice, create payment, update contact) is connected, the generic guard in SKILL.md applies:
explicit user instruction naming the record and effect, organisation verified, duplicate check, one
mutation, read-back, no automatic retry. Payments, bank reconciliation, manual journals, lock-date changes
and bulk edits stay outside this skill's default boundary.

## 6. Quirks That Produce Wrong Numbers

- One organisation is one entity. There are no subsidiaries, eliminations or consolidation inside Xero. A group is several connected organisations; anything you add across them is a pre-elimination aggregate, possibly in different base currencies, and intercompany balances are not eliminated. Label it so.
- Tracking categories (at most two active) are the only dimensions. Department, class or location analysis depends on how the organisation uses them; a P&L filtered by one tracking option excludes transactions with no option set.
- No formal period close. Xero has a period lock date and an end-of-year lock date instead. Treat a period as "final" only when the lock date covers it and the user confirms the year-end adjustments are in; otherwise it is preliminary even for old months.
- The financial year end is an organisation setting (day and month), not a calendar year. Read it before any year-to-date or quarterly figure.
- Cash versus accrual: reports can be run on either basis and the numbers differ. Ageing and receivables questions are accrual by nature; cash position is cash by nature.
- Tax-inclusive documents: totals include GST or VAT; net amounts exclude it. Revenue is net.
- Multi-currency: document amounts are in the document currency with a `currency_rate`; reports are in base currency. Unrealised gains and losses on open foreign-currency documents move with revaluation.
- Draft and submitted documents look like invoices but are not in the ledger; repeating templates are not documents at all.
- A demo company can be connected; check the organisation's demo flag before treating figures as real.
- Bank balances in Xero reflect imported feeds and reconciliation status; unreconciled statement lines are not in the ledger, and the cash tool is a ledger view unless it says otherwise.
- Data freshness differs by tool. The P&L, balance sheet, cash position and top-customer tools come from Xero's analytics store and carry `last_refreshed`, observed about two days behind; the ageing, invoice, bill and contact tools are live. Put `last_refreshed` in the Scope line as the data-as-of time, and do not tie a live ageing total to a stale balance sheet without saying so.
- Balance sheet figures can carry floating-point artefacts (many trailing decimals); round to cents before presenting.
- Ageing detail rows and contact lookups include contact email addresses; leave them out of answers and notes.

## 7. Discovery Probes for the Entity Profile

Run when SKILL.md's Entity Profile triggers apply. All are single read calls.

| Probe | Fills | Call |
| --- | --- | --- |
| 1 Entities | organisations connected, which is in scope | `get_connected_organisations` |
| 2 Organisation facts | base currency, country, tax basis and period, lock dates, demo flag | `get_organisation_info` |
| 0 Fiscal calendar | year-end day and month, current fiscal year range, how years are named | `get_organisation_financial_year`; fallback: the year-end fields from probe 2; last resort: ask the user |
| 4 Revenue scale and tier | trailing twelve months revenue for the materiality tier | `get_profit_and_loss` for the trailing twelve months, accrual basis |
| 5 Concentration baseline | top customers and top-three share | `get_top_customers_by_revenue` for the trailing twelve months |
| 6 Exposure baseline | receivables and payables ageing profile at onboarding | `get_aged_receivables`, `get_aged_payables` |
| 7 Period status | latest locked period, months since lock | lock dates from probe 2; there is no open or closed flag |
| 10 User-stated context | primary user role, bookkeeping cadence, tracking category meaning, standing month-end analyses | four plain-English questions to the user |

Books and modules do not apply: Xero has a single ledger; fixed assets, payroll and projects are
separate modules whose figures reach the ledger through journals.

Materiality tier from probe 4: under 25 million small, 25 to 500 million midsize, over 500 million
enterprise, thresholds per SKILL.md Analysis Defaults, overridable in conversation. Most Xero
organisations sit in the small tier; say so and use the small-tier floor.

## 8. Profile Card, Refresh and Standing Checks

Render one card: organisation(s) in scope; base currency and country; financial year; tax basis; lock
dates and period status; materiality tier and threshold; tracking categories in use and their meaning;
concentration baseline; ageing baseline; standing checks; user-stated context; and a "could not verify"
section. End with:

> Does this match your understanding? Say "looks good" to lock it in, or tell me what to change.

Persist per SKILL.md. Session-start refresh, at most two calls: reread the profile; rerun probe 2 for
lock dates; rerun probe 4 if the tier is more than 30 days old.

Standing checks for a Xero organisation:

| Check | Surfaces |
| --- | --- |
| Overdue receivables | amounts over 30, 60 and 90 days against the ageing baseline; top three debtors |
| Payables due | bills due in the next 14 days versus cash position |
| Draft and submitted backlog | documents not yet approved that would change the month once posted |
| Lock status | months since the period lock date; results after it are preliminary |
| Customer concentration drift | top-three share versus baseline; drift over 5 points |
| Multi-currency exposure | open foreign-currency receivables and payables when more than one currency appears |
| Group aggregation | when several organisations are connected, remind that totals are pre-elimination |

## 9. Failure Handling

If a tool is missing or a call fails: say which figure could not be read and why, continue with what is
available, and offer the manual path (the user runs the report in Xero and pastes or uploads it, which
then follows SKILL.md's exported-files mode). Never approximate a statement figure from document lists
without labelling it an estimate.
