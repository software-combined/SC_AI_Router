# Airwallex Runbook

How to read Airwallex safely through the Airwallex AgentOS MCP connector (`mcp.airwallex.com`) or an
equivalent server. Airwallex is a treasury, payments, spend and billing platform, not a general ledger:
it is the source of truth for cash by currency, payouts, FX, card spend and Airwallex-issued invoices,
and its figures reconcile to bank, clearing and control accounts in the accounting system. Read this
before the first Airwallex call in a session. The analysis method is in SKILL.md. Facts about a specific
organisation belong in the Entity Profile, not in this file.

Contents:

1. Connection and health check
2. Tool inventory
3. Read routing and parameters
4. Budgets and retries
5. Write policy
6. Quirks that produce wrong numbers
7. Discovery probes for the Entity Profile
8. Standing checks
9. Failure handling

## 1. Connection and Health Check

- Tools appear as `get_*`, `list_*`, `retrieve_*` (reads) and `create_*`, `update_*`, `activate_*`, `finalize_*`, `mark_*`, `void_*`, `verify_*` (writes), sometimes with a connector prefix such as `airwallex-agentos`.
- Every tool takes a `_rationale` string (10 to 500 characters) explaining why it is being called; write it plainly, it is logged.
- Harmless connectivity check: `get_account_balances`. It returns one row per currency the account can hold, most of them zero; filter to non-zero rows before presenting.
- Production and sandbox are different connectors with different limits. AgentOS targets the production account; say so in the Scope line.
- Classify problems as: not connected (no Airwallex tools), reauthorisation required (authentication error), degraded tool (one call fails while balances work), or window error (HTTP 400 for a date range wider than the tool allows, see section 4; fix the window, do not retry as is).

## 2. Tool Inventory

Read tools relevant to finance analysis (schemas checked in a live session, September 2026):

| Area | Tool | What it answers |
| --- | --- | --- |
| Account | `get_account_details` | business identity, status, operating countries; includes personal data about business persons, so call it only when identity itself is the question |
| Cash | `get_account_balances` | available, pending, reserved, prepayment and total per currency, by account type (`cash`, `yield`, `credit`), in major units |
| Cash | `list_balance_history` | every balance movement in a window of at most 7 days, by currency and account type |
| Cash | `list_global_accounts` | receiving accounts with local bank details (never echo the account numbers) |
| Payouts | `list_transfers` | outbound transfers in a window of at most 30 days, with status, funding status, fees, FX conversion and beneficiary |
| Payouts | `list_beneficiaries`, `get_beneficiary_schema` | beneficiary master data; contains bank details |
| FX | `get_fx_rate` | indicative rate for a pair and amount |
| FX | `list_fx_conversions`, `list_fx_conversion_amendments` | conversions with client rate, Airwallex rate and mid rate; statuses `SCHEDULED`, `OVERDUE`, `CANCELLED`, `SETTLED` |
| Spend (payables) | `list_spend_bills`, `retrieve_spend_bill` | supplier bills by status (`DRAFT`, `AWAITING_APPROVAL`, `AWAITING_PAYMENT`, `PAYMENT_IN_PROGRESS`, `PAID`, `REJECTED`, `SCHEDULED`) and accounting sync status |
| Spend (payables) | `list_spend_vendors`, `retrieve_spend_vendor` | vendor records and their sync status |
| Spend (cards) | `list_spend_card_expenses`, `list_issuing_transactions`, `list_cards`, `list_cardholders`, `retrieve_card`, `retrieve_card_limits` | card expenses (Spend product) or raw card transactions (Issuing) |
| Billing (receivables) | `list_billing_invoices`, `retrieve_billing_invoice`, `list_billing_invoice_line_items`, `list_billing_customers`, `list_billing_subscription_items`, `list_billing_transactions`, `list_billing_prices`, `list_billing_products` | invoices issued through Airwallex Billing (`DRAFT`, `FINALIZED`, `VOIDED`; payment status `UNPAID`, `PAID`), subscriptions, customers |
| Payments accepted | `list_payment_intents`, `list_payment_links`, `list_refunds` | card and online payments received, refunds |
| Documentation | `search_public_docs` | Airwallex documentation lookup; responses can be very large |

Write tools also exist (`create_beneficiary`, `verify_beneficiary_account`, `create_card`,
`create_cardholder`, `activate_card`, `update_card`, `create_payment_link`, and the
`create_billing_*`, `update_billing_*`, `finalize_billing_invoice`,
`mark_billing_invoice_as_paid`, `void_billing_invoice` family). This skill
never calls them; see section 5.

## 3. Read Routing and Parameters

Map the finance question to the platform area, then use the smallest call:

1. Cash position: `get_account_balances`, filtered to non-zero currencies. Present available and total separately; reserved and pending amounts are not spendable. For a cash movement narrative use `list_balance_history` in 7-day windows.
2. Payables and payment run: `list_spend_bills` by status (`AWAITING_APPROVAL`, `AWAITING_PAYMENT`, `SCHEDULED`) for the pipeline; `list_transfers` for what actually went out, in 30-day windows.
3. Receivables issued from Airwallex: `list_billing_invoices` with `status = FINALIZED` and `payment_status = UNPAID`; drafts are not receivables.
4. FX: `list_fx_conversions` for realised conversions; compare `client_rate` with `mid_rate` for the cost of conversion; `get_fx_rate` only for an indicative current rate, never as a booking rate.
5. Card spend: `list_spend_card_expenses` when the organisation uses Airwallex Spend, otherwise `list_issuing_transactions`; ask which before choosing.

Parameter conventions observed:

- Timestamps are ISO 8601 with time and zone (`2026-09-01T00:00:00Z`); `from_*` is inclusive and `to_*` exclusive on most tools. Prefer a midnight end.
- Amounts are decimal numbers in major units (dollars, not cents).
- Pagination is cursor-based: pass the response's `page_after` (or `page_before`) as `page`; FX conversions use `page_num` and `has_more`; balance history accepts either. Default page sizes vary (20 for billing invoices, 100 for FX and balance history, up to 2000 for transfers).
- Multi-entity accounts: spend tools accept `legal_entity_id`; balances are per account. Establish which legal entity a figure belongs to before consolidating.
- Status filters on `list_transfers` (`NEW`, `SETTLED`, `PENDING`, `SUSPENDED`, `FAILED`) do not match every status shown on records (`PAID`, `IN_APPROVAL` were observed). When a filter returns nothing unexpected, pull the window unfiltered and classify client-side.
- Transfers and beneficiaries return bank account numbers, routing codes, addresses and personal names and emails. Keep only aggregate fields (amount, currency, date, status, counterparty name when needed) in your working notes and never repeat bank details or personal contact data in an answer.

## 4. Budgets and Retries

- Hard window caps: balance history at most 7 days per call, transfers at most 30 days per call (a full calendar month or a `T23:59:59Z` end can exceed it), FX conversions default to 31 days. Split longer periods into consecutive windows and count each as a call; a quarter of balance history is about 13 calls.
- Default budget: 20 read calls per user request unless the user widens scope; prefer status-filtered lists over paging through everything.
- Airwallex production API limits (documentation, September 2026): 100 requests per second globally, 20 per second per endpoint, 50 concurrent. Sandbox is lower. On HTTP 429 wait and retry once; on a 400 window error fix the window, never retry as is; never retry authentication or validation errors.
- `search_public_docs` can return over a hundred thousand characters; ask a narrow question and read only the parts you need.

## 5. Write Policy

Airwallex AgentOS is production read and write. Its own guardrail is "no money-out actions by
default", but the write tools that exist (beneficiaries, cards, payment links, billing invoices) are
consequential: a new beneficiary or an activated card is a fraud vector, and finalising or voiding an
invoice changes receivables. This skill is read-only on Airwallex. If a user asks for any of these,
hand it back to them or to the organisation's payments approval process; do not perform it as part of
finance analysis, even with the generic write guard satisfied.

## 6. Quirks That Produce Wrong Numbers

- Airwallex is not the ledger. Its balances and transfers are cash facts; the accounting system decides how they are classified. Never combine an Airwallex balance with a general ledger cash figure without stating which is which and the timing difference.
- Sync status tells you what has already flowed to the accounting system (`SYNCED`, `NOT_SYNCED`, `SYNC_FAILED`, `READY_TO_SYNC`). Bills or card expenses that are `SYNCED` are already in the ledger as vendor bills or expenses; counting them again double-counts payables. `SYNC_FAILED` items are missing from the ledger until fixed; flag them.
- Automatic syncs can create vendor or supplier records in the accounting system with a platform prefix. Deactivating or merging those records can break the sync; treat them as system-owned.
- Balances are per currency with no group total. Convert with a stated rate and date if a total is needed, and label it indicative.
- Available versus total: reserved and pending amounts sit inside total but cannot be paid out. Runway and payment-run questions use available.
- A conversion's `client_rate` includes the margin; `mid_rate` does not. The difference times the amount is the FX cost; present it as such, not as a loss on the ledger.
- Transfer amounts appear twice: `amount_payer_pays` in source currency and `amount_beneficiary_receives` in transfer currency. Cash out is the payer amount.
- `funding.status` of `REQUIRES_FUNDING_CONFIRMATION` and transfer status `IN_APPROVAL` mean money has not left; only settled or paid transfers reduce cash.
- Billing invoice drafts are not receivables; voided invoices are not revenue.
- Balance history is a change log, not a statement; opening balance plus movements must be tied to `get_account_balances` before presenting a reconciliation.

## 7. Discovery Probes for the Entity Profile

Airwallex supplies the cash-side facts of the profile; the accounting-system runbook supplies the rest.

| Probe | Fills | Call |
| --- | --- | --- |
| A Currencies held | currencies with non-zero balances, account types in use | `get_account_balances` |
| B Products in use | spend (bills, card expenses), billing, payments accepted, FX | one call each to `list_spend_bills`, `list_spend_card_expenses`, `list_billing_invoices`, `list_payment_intents`, `list_fx_conversions` over the default window; an empty result means the product is unused or unused recently |
| C Legal entities | entities on the account | `legal_entity_id` values seen in spend results, or ask the user |
| D Accounting sync | which accounting system receives bills and expenses, and sync health | `sync_status` values from probe B; ask the user which system |
| E User-stated context | who approves payments, payment-run cadence, which ledger accounts Airwallex maps to | plain-English questions |

## 8. Standing Checks

| Check | Surfaces |
| --- | --- |
| Cash by currency | available versus total per currency; concentration in one currency |
| Payment pipeline | bills awaiting approval, awaiting payment and scheduled, against available cash in the paying currency |
| Sync failures | any `SYNC_FAILED` bill, vendor or card expense; these are missing from the ledger |
| Pending outflows | transfers `IN_APPROVAL` or awaiting funding; they are not yet in cash but are committed |
| FX cost | conversions in the period, client versus mid rate, total margin paid |
| Overdue Airwallex invoices | finalised, unpaid invoices past due date |
| Ledger tie-out | Airwallex total per currency versus the accounting system's Airwallex clearing or bank account at the same timestamp, difference explained |

## 9. Failure Handling

If a window or paging limit blocks a read, narrow the window rather than approximate. If a product area
returns nothing, say the product appears unused rather than reporting zero activity as a finding. If a
tool exposes more personal or bank data than the question needs, keep it out of the answer and out of
any saved notes.
