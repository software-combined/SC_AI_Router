# Model allocation review process

**Software Combined | process version 1.0 | owner: Cyril Allart | cadence: monthly**

This process produces and maintains `plans/model-allocation/suggestion.md`. It fixes the
evidence, the calculation, the decision rules and the output format so that every
monthly review reaches the same conclusions from the same facts. A review produces a
written proposal only. Nothing in this process deploys a model, edits the router
catalogue, or changes any configuration.

## 1. Purpose and scope

In scope:

- Re-checking which models and reasoning efforts are the best value for each agent
  role we run. The canonical role list, used by sections 7, 8 and 8.1, is:
  **orchestrator; explorer; executor (bounded); executor (multi-file); research;
  debugging; simplification; correctness; adversarial; quality; planner; advisor.**
  Changing it is a process change under section 11.
- Recalculating model prices in USD and AUD on a fixed, published basis.
- Publishing one dated, reviewable suggestion with an explicit decision request.

Out of scope, and handled as separate owner-approved work:

- Router code, catalogue rows, effort exclusions, and client configuration.
- Provider commercial negotiation, subscriptions, and quota changes.
- Piloting, deploying, or rolling back an accepted allocation change.

## 2. Cadence and triggers

| Type | When | Output |
| --- | --- | --- |
| Scheduled review | The 1st of each month at 08:30 Australia/Sydney, run by the `Monthly model allocation review` Codex automation | Updated suggestion plus a PR to `develop` |
| Event review | Within 5 business days of a trigger | Updated suggestion, or a recorded no-change decision |

A weekend or public-holiday run is acceptable: the review is read-only, and every
figure carries its own evidence date.

The scheduled run is the guaranteed cadence. Event triggers have no watcher of their
own: they are raised by the owner, or by an automation that is separately created and
owned, so the monthly review is the backstop rather than a substitute. If a trigger is
known to be open when a review runs, the review handles it as part of that run and says
so in the review log.

While an event review is open, any row whose admissibility is in question is
**inadmissible for new work** until the review closes. If the question is still
unresolved when the review closes, the row stays inadmissible and the question is
carried as an open item with an owner and a next check.

Event triggers:

- A model is added to, or retired from, `ai_router/models.json`.
- A published price on a row we use moves by 20% or more.
- Artificial Analysis ships a new index version, or materially revises a score or a
  leaderboard position we rely on.
- A quality incident: rework, a missed defect, or a failed client outcome traced to a
  model choice.
- A provider changes its data-use terms in a way that affects private work.
- A new role, client, or route with materially different consequences.

## 3. Roles and authority

- **Prepared by**: the scheduled Codex review task, or Cyril manually. Record the
  preparer and the models used to prepare it in the suggestion.
- **Approved by**: Cyril. A recommendation becomes policy only after explicit
  approval. Until then it is a proposal with no effect on routing.
- **Consumed by**: whoever configures Codex, OpenCode, or Claude Code routes, the
  pre-commit review policy, and anyone asking "which model should I use for this".

Every suggestion states its status: `PROPOSED`, `APPROVED <date>`,
`SUPERSEDED <date>`, or `PARTIAL <reason>` when a load-bearing source could not be
read. `PARTIAL` never carries a fresh recommendation, only the gap record and the next
check.

**Load-bearing sources**, which abort the recommendation update when they fail, are:
the Artificial Analysis index scores for the rows in use, and the OpenRouter price for
the rows in use. Everything else degrades gracefully: an RBA failure uses the named
alternate and marks the conversion `Unverified` (section 6.3); a missing per-provider
`/endpoints` split is recorded as a gap and the row's price is marked `Unverified`.

## 4. Evidence sources

Every number in a suggestion carries a source and a date. A number without both is not
evidence.

| Source | What to take | Access notes |
| --- | --- | --- |
| [Artificial Analysis model leaderboard](https://artificialanalysis.ai/leaderboards/models) | Artificial Analysis Intelligence Index, cost per task, tokens/second, first-chunk latency and total response time, per model and effort | Server-rendered: a `curl` with a browser `User-Agent` returns the full table in the HTML, and Chrome renders the same table readably (both verified 2026-09-11). Table columns in order: Model, Context Window, Creator, Artificial Analysis Intelligence Index, Cost per Task USD, Median Tokens/s, Latency First Chunk (s), Total Response (s). Rows are effort-qualified (`GPT-6 Astra (max)`, `GPT-6 Astra (xhigh)`), and the page filter defaults to Status: Current. The page does **not** print the index version; take that from the methodology page and record the `Updated` marker beside the Intelligence section. |
| [Artificial Analysis coding agents](https://artificialanalysis.ai/agents/coding-agents) | Coding Agent Index, mean wall time per task, mean API cost per task, with `harness - model (effort)` configuration | Same fetch. The page embeds three `schema.org` JSON-LD datasets in the HTML: Coding Agent Index (`codingAgentsIndex`, 0 to 1; multiply by 100), Time per Task (`codingAgentsMeanAgentWallTimeSec`), and Cost per Task USD (`codingAgentsMeanCostUsd`). The version is inside the dataset description (for example "Coding Agent Index v1.5"), and scoring detail plus version history sit on the [coding-agents methodology page](https://artificialanalysis.ai/methodology/coding-agents-benchmarking). Scores are harness-coupled: record `harness - model (effort)` with every figure. |
| [Artificial Analysis methodology](https://artificialanalysis.ai/methodology) | Current index versions, scoring rules, recent changes | Use when a score drives a material recommendation, or when the leaderboard's `Updated` marker suggests a revision in the review window. |
| [OpenRouter model catalogue](https://openrouter.ai/api/v1/models) | Exact slug, per-token prices, context window, supported efforts, modality, provider set | Public endpoint. Record the fetch time. Check the exact slug and serving provider, not the marketing name. |
| [OpenRouter model endpoints](https://openrouter.ai/api/v1/models/`<slug>`/endpoints) | Per-provider price, context window, provider list and the serving provider's data policy for one slug | Public endpoint, no key (verified 2026-09-11). Use it to confirm that a cheap row is actually served at the modelled price by every provider in scope, and to see which providers differ. A row priced at the headline rate by one provider and a premium by another needs the split recorded. |
| `ai_router/models.json` | Rows the router actually serves: slug, vendor, allowed efforts, excluded efforts, tier | In this repository. The catalogue is the only thing we can route to today. |
| Published harness benchmarks | SWE-bench Verified, Terminal-Bench, SWE-Atlas-QnA, DeepSWE, and similar, when the harness matches our route | Use measured numbers only for the same model, effort, and harness. Label every cross-harness transfer `Inferred`. |
| Provider terms | Data-use and training clauses for any candidate used on private work | Check the provider's current terms page. Record what was read and when, and keep the open question visible when it is unresolved. |
| [RBA F11.1 exchange rates](https://www.rba.gov.au/statistics/tables/csv/f11.1-data.csv) | `A$1=USD` daily rate (series FXRUSD, WM/Reuters indicative, 4pm) | CSV download. Record the publication date shown in the file and the retrieval time. |
| Internal telemetry | `router.jsonl` counters, review-lane records, completion times, rework incidents | Owner-readable local runtime data. Used to calibrate the cost model, never as a benchmark score. |

**No single source decides anything.** The review is a triangulation: Artificial
Analysis supplies quality, the OpenRouter catalogue supplies the price we would
actually pay, the router catalogue supplies what we can actually route, provider terms
supply the admissibility test for private work, and internal telemetry supplies the
reality check on the modelled volumes. A recommendation that rests on one source is
`Unverified` by construction.

### 4.1 Artificial Analysis access paths

Three routes. Use route 1 for the numbers, route 2 to confirm them before a material
recommendation, and route 3 only if the owner buys a key.

1. **Page HTML (default, no key):** fetch with a browser `User-Agent` and parse the
   table rows or the JSON-LD datasets. `robots.txt` allows retrieval and the datasets
   are published under the site's
   [Terms of Use](https://artificialanalysis.ai/docs/legal/Terms-of-Use.pdf); keep to
   one retrieval per page per review and attribute Artificial Analysis whenever a
   figure leaves this repository.
2. **Browser, via computer use (verification and fallback):** open
   `https://artificialanalysis.ai/leaderboards/models` and
   `https://artificialanalysis.ai/agents/coding-agents` and read the rendered table
   (verified 2026-09-11 in both the in-app browser and Chrome). Prefer the **in-app
   browser**: it renders identically, needs no user session, and leaves the user's
   Chrome tabs and logins untouched. Use Chrome only when a read must happen in the
   user's own authenticated profile. On the leaderboard, type a model name into the
   search field and read across the row: creator, Intelligence Index, cost per task,
   output speed. Confirm the effort suffix in the row label, not just the model name.
   On the coding agents page, read the plotted values and the index version. Take a
   screenshot as the review's visual record. Use this route whenever HTML extraction
   fails or its numbers disagree with the previous review.
3. **Pro Data Platform API (only if the owner buys a key):**
   `https://artificialanalysis.ai/api/v2/data/llms/models` answers `401 API key is
   required` without one. That endpoint is **deprecated, sunset 2026-11-04**, with a
   migration note at `https://artificialanalysis.ai/data-api/migrate-v2-data`; the
   product entry point is `https://artificialanalysis.ai/data-api`. Re-check the
   current endpoint and terms before building anything on it.

The review must **verify extraction produced rows**: if a fetch returns no parseable
rows or datasets, treat it as a failed source. Verification means the Chrome readback
above, or a second independent extraction of the same figure. Do not carry a figure
forward as if it were re-read, and do not silently fall back to an older score.

Re-check these on every run, because a one-time verification does not survive a site
change and a changed source can still parse:

- `robots.txt` and the Terms of Use still permit the retrieval we perform.
- The table headers and column order match section 4; read the header row, do not
  assume it.
- The extracted index version matches the version the review claims.
- Every slug in use still resolves on OpenRouter.
- Attribution to Artificial Analysis is present in the suggestion.

### 4.2 Three different "cost" numbers

### 4.3 Evidence hygiene

The suggestion is committed to git, so its history is permanent and effectively public
to anyone with repository access.

- Aggregates only. Never record client names, project names, contract or commercial
  terms, prompt or response text, tool payloads, credentials, tokens, or keys. A
  quality incident is recorded as a category and a count, never as the case itself.
- Finance rates and any other commercially sensitive input are referenced, not pasted.
- Run the pre-commit secret scan before every review commit; it is the gate, not a
  formality.

They are not interchangeable and confusing them is the most likely way to get a wrong
recommendation:

| Measure | Source | What it means | When to use |
| --- | --- | --- | --- |
| Per-token price | OpenRouter catalogue | What we pay per million tokens, by token class | Always. This is the input to section 6. |
| Cost per task (model) | AA leaderboard, "Cost per Task USD" | AA's own task suite run against the model on AA's pricing basis | As a cross-check on token efficiency; it already embeds AA's token volumes |
| Cost per task (harness) | AA coding agents | Measured API cost inside one named agent harness | Only for the same harness and effort. It is the best evidence for agentic work, and the reason GPT-6 Astra beats some cheaper-per-token rows in practice |

Verify at least one row a second time from a second source. Verified 2026-09-11:
Muse Spark 1.3 (max) shows **$1.60** cost per task on the models leaderboard and
**$3.98** on the coding agents page in the Muse Code harness. Both are correct; they
answer different questions. Quote the measure, the harness and the date, or the number
is meaningless.


## 5. Definitions and units

- **Price**: USD per 1,000,000 tokens, uncached input unless labelled. Output price
  covers visible output plus all billable reasoning tokens.
- **Cache read**: applies only when the provider reports a cache hit. A modelled cache
  hit is an assumption, not a measured saving.
- **Effort**: reasoning effort changes both quality and token consumption. Never
  compare scores or prices across different efforts.
- **Harness coupling**: an index measured inside one agent harness does not transfer
  to another. Transfers are `Inferred` until measured on our own route.
- **Index point**: always name the index and version with the score, for example
  "Intelligence Index v4.3: 48".
- **AUD rate** (`rate`): USD per A$1 as published by the RBA.

## 6. Calculation

### 6.1 USD cost of a workload

```
cost_usd = (input_tokens        x input_rate
          + cached_input_tokens x cache_read_rate
          + output_tokens       x output_rate) / 1_000_000
```

All rates are USD per 1M tokens. `input_tokens` is the **uncached** portion and
`cached_input_tokens` is the cached portion; together they are the total input. The
cached portion is charged at the cache-read rate, never at the input rate, and must not
also be charged as uncached input.

### 6.2 Standard workload profiles

| Profile | Total input tokens | Cache hit | Output tokens | Used for |
| --- | ---: | ---: | ---: | --- |
| Review lane | 80,000 | 0% | 6,000 | One pre-commit pass over a staged diff |
| Orchestrator turn | 120,000 | 90% | 2,000 | One session turn with re-read context |
| One-shot | 100,000 | 0% | 8,000 | An advisor question or a plan |
| Agentic task | measured | - | - | Prefer the measured cost per task from the Coding Agent Index; if absent, use a synthetic profile (for example 300,000 input at 75% cache, 20,000 output) labelled `Inferred` |

Split the total before applying rates. An orchestrator turn at 120,000 total input and
a 90% cache hit is 12,000 uncached plus 108,000 cached, not 120,000 plus 108,000.

Worked example, DeepSeek V4.1 Flash at the lower-rate scenario ($0.15 in / $0.60 out /
$0.003 cache read), one orchestrator turn:

```
uncached  12,000 x 0.15  / 1e6 = US$0.00180
cached   108,000 x 0.003 / 1e6 = US$0.00032
output     2,000 x 0.60  / 1e6 = US$0.00120
                         total = US$0.00332  -> A$0.0046
```

These profiles are comparison assumptions, not measurements, and must not be quoted as
bills. Recalibrate them from router counters at least once a year, or when the numbers
stop matching observed spend.

### 6.3 Currency conversion (USD to AUD)

- **Source of truth**: RBA F11.1 `A$1=USD` (series FXRUSD, WM/Reuters indicative,
  4pm). Record the publication date and the retrieval timestamp.
- **Rule**: `aud = usd / rate`. Never multiply by the rate. If a source quotes the
  inverse convention (USD/AUD), label the convention before using it.
- **Date**: use the most recent business-day rate published on or before the review
  date. If the RBA data is unavailable, use one clearly named alternate source and
  mark the conversion `Unverified`.
- **Rounding**: A$0.10 and above to 2 decimal places; below A$0.10 to 4 decimal
  places. Always convert from the USD figure; never chain-round through an
  intermediate AUD value.

Worked example, A$1 = US$0.7220 (RBA, published 10 Sep 2026, retrieved 2026-09-11):

1. GLM 5.3 Flash, review lane: (80,000 x 0.15 + 6,000 x 0.50) / 1e6 = US$0.0150.
   A$0.0150 / 0.7220 = A$0.0208.
2. Claude Opus 5, review lane: (80,000 x 5.00 + 6,000 x 25.00) / 1e6 = US$0.5500.
   A$0.5500 / 0.7220 = A$0.7618, reported as A$0.76.

### 6.4 Monthly and annual cost model

```
monthly_aud = sum over roles (runs_per_month x cost_per_run_aud)
annual_aud  = 12 x monthly_aud
```

Baseline parameters. These are working assumptions the owner adjusts; recalibrate them
from router counters when the data is available.

| Parameter | Baseline |
| --- | ---: |
| Reviewed commits per month | 40 |
| Passes per reviewed commit | 4 (simplification, correctness, adversarial, quality) |
| Orchestrator turns per month | 2,000 |
| One-shot advisor or planning runs per month | 20 |

Worked example at the same FX basis: 40 commits on the normal four-pass profile
(A$0.24 per commit) is A$9.48 per month, about A$114 per year. The same 40 commits on
the elevated-risk profile (A$3.83 per commit) is A$153 per month, about A$1,838 per
year. Both figures exclude taxes, gateway and currency fees, and human rework.

### 6.5 Rework and human cost (optional)

When a model choice changes rework, add `rework_aud = minutes x loaded_rate_aud / 60`
using a loaded rate supplied by Finance. Where the rate is not available, record the
term as unquantified rather than guessing. Where rework volume is known, compare
`cost per accepted deliverable = (token cost + rework cost) / accepted deliverables`.

## 7. Decision rules

1. **Hard gates first**, disqualifying regardless of price: tool calling and patch
   support on our route, required context window, effort support the provider
   actually honours, modality, latency suitable for the role, and acceptable data
   terms for private work.
2. **Pareto screen**: drop any row that is both more expensive and weaker than
   another available row on the same harness and effort basis.
3. **Family diversity for ensembles**: the review lanes must not all sit on one model
   family. Three lanes on one model share one set of blind spots, so the third lane
   adds little. Buy diversity when it is cheap.
4. **Materiality thresholds**. Propose a change only when one holds on
   harness-matched evidence:
   - quality: at least 3 index points better at no more than 105% of the current cost;
   - cost: at least 20% cheaper at equal index (within 1 point);
   - a hard gate or a terms question changed.
5. **Default is no change.** A no-change review still refreshes prices, the FX rate,
   the timestamps, and the open items.
6. **Escalation rows stay explicit.** Record the trigger next to the escalation model
   (security, money, destructive operations, migrations, production-consequential
   change) so escalation is a decision, not a mood.
7. **Unverified inputs cannot carry a recommendation.** Resolve the question, or
   present the recommendation as conditional with a next check. This does not soften
   the abort rule: a load-bearing source failure (section 3) is an abort under section
   8 step 11, not a conditional recommendation.

### 7.1 The Pareto screen, and what it does not decide

The Pareto frontier answers "what is the best single pick on cost and quality". It does
not answer "what is the best ensemble", and it must never be applied to a whole
catalogue as if one row could serve every role.

**Procedure.** For every catalogue row that passed the hard gates, pair the
harness-matched Intelligence Index with the section 6 review-lane cost. A row is
**dominated** when another admissible row has an index at least as high *and* a cost at
least as low, with at least one of the two strict. Drop dominated rows; the survivors
are the frontier. On the frontier, cost buys quality at a measurable exchange rate, and
that rate is the number the decision turns on.

**Worked example, verified 2026-09-11** from Intelligence Index v4.3 and the OpenRouter
catalogue at the review-lane profile (80,000 input, 6,000 output):

| Frontier row | Effort | Index | Lane cost USD | Lane cost AUD |
| --- | --- | ---: | ---: | ---: |
| `meta/muse-spark-1.3-contributor` | xhigh (max not admissible, see note) | 48* | US$0.0092 | A$0.0127 |
| `~anthropic/claude-opus-latest` | max | 51 | US$0.5500 | A$0.76 |
| `~anthropic/claude-fable-latest` | max with fallback | 53 | US$1.1000 | A$1.52 |
| `openai/gpt-6-astra` | max | 53 | US$1.1000 | A$1.52 |

*The contributor row currently carries a local `excluded_efforts: ['max']` in
`ai_router/models.json`, so `max` is not routable today and the index shown is the
base-tier `max` measurement carried over from the source analysis. That carry-over is
the single load-bearing assumption in this example and it is `Unverified` until a
parity probe passes. Until then the admissible contributor effort is `xhigh`.

Thirteen of the seventeen joined rows were dominated. The two 53-index rows tie on both
axes, so the tiebreak is not cost or index: it is family, harness fit and measured
in-harness cost per task (Astra US$7.47 against Fable 5.1 US$12.39, Coding Agent Index
v1.5). Read that against the analysis' headline: buying the last index points costs
roughly 60x to 120x the contributor lane, which is why the frontier belongs in the
escalation rows and not in the default rows.

**Rules for using the frontier.**

- Rank by cost **within the admissible frontier** (hard gate 1 applied first), then
  place rows into roles: the cheapest admissible row is the default, the next is the
  escalation, the top is the last resort. Ranking never overrides a hard gate.
- A frontier of one row means the catalogue has a single sane choice; say so, and look
  for diversity *within* a role rather than across cost.
- Diversity is not a frontier property. Three review lanes on one frontier row share
  one set of blind spots, so the lanes are chosen by family, not by rank.
- Re-run the screen every review. A frontier is only valid for the index version, the
  price list and the catalogue it was computed from; all three drift.
- Record the drifted rows explicitly. On 2026-09-11 the re-read moved
  `deepseek/deepseek-v4.1-flash` (max) from index 35 in the source analysis to **40**
  under Intelligence Index v4.3, which strengthens rather than weakens its
  orchestration and quality-review case. Undetected drift in a used row is the most
  common way this process silently degrades.

**Ties and near-ties.** When two rows sit within 1 index point and 20% of each other on
cost, the process treats them as equivalent and decides on family diversity, provider
stability, context window, tool-calling behaviour and measured latency. Record the
reason, because the next reviewer will otherwise re-litigate it.

## 8. Review runbook

1. Copy the previous suggestion as the draft and record the review start time in
   Australia/Sydney.
2. List the rows actually available from `ai_router/models.json`, with allowed
   efforts and tiers.
3. Fetch the OpenRouter catalogue and the `/endpoints` record for each row in use.
   Record the fetch time, note any price, context, capability or serving-provider
   change, and record any per-provider price split.
4. Read Artificial Analysis by section 4.1 route 1, then confirm by route 2. Record
   the current index versions, the scores used, and the read date.
5. Check every candidate against the hard gates, including provider data terms.
   Record what was checked and when.
6. Recompute the standard profiles in USD for every row in scope.
7. Fetch the RBA F11.1 CSV, take the latest published rate, and record its
   publication date and retrieval time. Convert with the section 6.3 rule.
8. Apply the decision rules and write one outcome per role: keep, propose, or
   investigate. Use the canonical role list in section 1 and say explicitly if the
   role set changed.
9. Update the suggestion to the section 9 template: header block, price tables in USD
   and AUD, cost model, recommendation table, conditions, open items with owner and
   next check, sources, review log.
10. Verify the arithmetic independently (recompute the headline figures a second
    way) and confirm every number has a source and a date.
11. Abort the recommendation update if a load-bearing source failed: mark the
    suggestion `PARTIAL`, keep the previous figures under their original dates, record
    the gap and the next check, and change no recommendation.
12. Commit through the normal review gate and open a PR to `develop`. The suggestion
    keeps the status set in step 11 (`PROPOSED` after a normal run, `PARTIAL` after an
    abort) and stays in an open PR until the owner approves it. Only the owner merges
    a suggestion update, including a no-change refresh.
13. Report the outcome, the next review date, and the open items.

### 8.1 Per-role deep dives (subagent fan-out)

The parent review covers every role against one shared evidence pack, which is fast but
shallow per role. When a role is contested, or its cost is material, fan the analysis
out: **one read-only analyst subagent per role**, each charged with arguing that role's
case in depth. This is the mechanism that turns a table of index scores into a
defensible per-role recommendation.

| Item | Setting |
| --- | --- |
| Executor | `deepseek/deepseek-v4.1-flash` at `max`, on the owner's instruction. The host policy in `AGENTS.md` owns the executor default; where the two differ, `AGENTS.md` wins unless the owner says otherwise. Record the resolved model and effort for the run. |
| Roles fanned out | The canonical role list in section 1 |
| Concurrency | At most 8 children at once; batch the roles if more are in scope |
| Authority | Read-only. Children never edit the suggestion, never commit, and never spawn their own subagents |
| Evidence | The parent's extracted evidence pack (leaderboard rows, coding-agent datasets, OpenRouter prices, catalogue rows), passed as absolute paths or inline data, with the retrieval date |

If the fan-out executor is retired, repriced beyond the parent's own row, or blocked by
terms, use the cheapest admissible row instead and record the substitution. If no row
is admissible, skip the fan-out and mark the per-role picks `Unverified`; never present
a parent-only review as a fanned-out one.

One child per role, with a fixed report contract so the parent can compare them:

1. Role, and what the work actually consumes (input size, cache behaviour, harness,
   tools, output shape).
2. Every catalogue row that passes the hard gates for that role, with index score,
   index version, effort, and source date.
3. Cost for that role's workload profile, in USD and AUD, using section 6 and the
   review's stated FX basis.
4. Recommended default and escalation row, with the trigger for escalation.
5. Confidence (0 to 1), the weakest assumption, and what would falsify the pick.

Rules that stay with the parent, because no single child can see them:

- Family diversity across the review lanes is a cross-role property.
- The Pareto screen and the materiality thresholds are applied once, globally.
- Every child's arithmetic is spot-checked; a child's number is a claim until the
  parent reproduces it.
- The parent writes the suggestion. Children return findings, not prose.

Cost of the fan-out itself, at the lower-rate DeepSeek scenario and the one-shot
profile (100,000 input, 8,000 output, no cache): US$0.0198 per role, so roughly
**A$0.03 per role** and about **A$0.33 for a twelve-role review** at the FX basis in
this version. The fan-out is cheap enough to run every month, and it is the intended
shape when the owner asks "what is each role actually best served by?" rather than
"what is the cheapest row?".

## 9. The suggestion file

The canonical file is `plans/model-allocation/suggestion.md`, updated
in place. A dated snapshot copy (`plans/model-allocation/suggestion-YYYY-MM-DD.md`) is made
only when something outside git needs one; the canonical file stays canonical.

Required header block:

```
**Software Combined | <Month Year> | <status>**

Generated: <YYYY-MM-DDThh:mm+offset> (Australia/Sydney)
Evidence window: <YYYY-MM-DD> to <YYYY-MM-DD>
FX basis: A$1 = US$<rate> (RBA F11.1, published <date>, retrieved <date>)
Process: plans/model-allocation/review-process.md v<version>
Previous review: <date or none> | Next review due: <date>
```

Required sections:

1. Recommendation table by role, with model, effort, and AUD cost per unit of work.
2. Price table in USD with AUD equivalents and the conversion basis stated.
3. Cost model with the profile inputs actually used.
4. Conditions, confidence, and open items, each dated.
5. Sources with retrieval dates.
6. Review log: an append-only table of review date, preparer, FX basis, and outcome.

Timestamp rules:

- `Generated` is the time the review finished writing, not the time reading started.
- Never reuse, re-label, or backdate a timestamp, and never leave an old review's
  numbers under a new timestamp. Git history is the archive of past suggestions.
- Every external number carries its own read date.

## 10. Evidence and confidence

- `Verified`: read from the named source on the stated date in this cycle.
- `Inferred`: derived by calculation, or transferred across harnesses; state the
  assumption.
- `Unverified`: carried from an earlier cycle or a secondary source. Never
  load-bearing without a resolution plan.

Record a confidence value (0 to 1) for the allocation as a whole and for each
contested row, and keep unresolved contradictions in open items with a next check and
an owner.

## 11. Changing this process

Bump the version, write the change in the process log, and get owner approval. The
process changes on evidence, not preference.

## Appendix A: source links

- Artificial Analysis leaderboard: https://artificialanalysis.ai/leaderboards/models
- Artificial Analysis coding agents: https://artificialanalysis.ai/agents/coding-agents
- OpenRouter model catalogue: https://openrouter.ai/api/v1/models
- RBA F11.1 exchange rates: https://www.rba.gov.au/statistics/tables/csv/f11.1-data.csv
- Source analysis for version 1.0: KnowledgeVault
  `agent/Model Routing Cost Analysis 2026-09.md`, summarised in
  `plans/model-allocation/suggestion.md`.

## Appendix B: process log

| Version | Date | Change |
| --- | --- | --- |
| 1.0 | 2026-09-11 | First version: monthly cadence and triggers, evidence sources, USD and AUD calculation rules, decision rules, suggestion template, runbook. |
