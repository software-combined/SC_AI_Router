# Updating model recommendations

Refresh on a catalogue/model version change, material price change, client/router
upgrade, a relevant benchmark release, or repeated task failures. Recheck prices
before material spend; do not assume a dated promotion still applies. Plugin
auto-update distributes reviewed releases; it does not autonomously research,
rewrite policy or authorize paid evaluation runs.

## 1. Inventory and identity

Read the current router registry, active mixed catalogue and Codex model
catalogue. Record exact slug, snapshot/version, provider route, supported effort,
modality, context and tool compatibility. Include hidden/system rows as excluded,
and collapse runtime aliases of the same model into one selection entry. Verify availability through
the actual runtime; a public listing does not establish account permission.

Match benchmarks to exact model, version, reasoning effort and harness. Never
merge a dated snapshot into an alias, a Contributor tier into standard Muse, or
different harness results without evidence. Keep unknowns
null, not zero. User policy groups Muse 1.3 xhigh/max for selection, while their
measurements remain separate evidence rows; standard Muse has one prescribed
level, `max`. Assign every other model one prescribed level, preferably its
highest supported plain reasoning level. Preserve these levels across tasks;
reduce cost by choosing a cheaper model, not by quietly lowering effort.

## 2. Sources and benchmark choice

Prefer benchmark operators for measurements, provider/model cards for supported
features and terms, and the actual billing provider for prices. Blogs and social
posts can identify questions but do not establish a recommendation. Triangulate
material claims across independent evaluation methods, not several articles
repeating one release announcement.

- [Artificial Analysis methodology](https://artificialanalysis.ai/methodology/intelligence-benchmarking):
  record index version, task suite and harness. The 2026-09-12 snapshot uses v4.3,
  Terminal-Bench v4.0, GDPval-AA v2, AutomationBench-AA and AA-LCR v1.1. Old v4.1
  or v4.2 composite scores cannot be compared directly with v4.3.
- [Arena WebDev](https://arena.ai/leaderboard/code): useful for UI preference,
  not a replacement for repository correctness. Record date, exact model/effort,
  votes, confidence bounds and preliminary status. Inspect its Pareto view.
- [Arena Agent Code](https://arena.ai/leaderboard/agent/code): separate from
  WebDev; preserve its task definition, harness and cost basis.
- Terminal work: Terminal-Bench on a common version/harness, relevant SWE tasks
  where exact rows exist, and local regression results. Do not mix pass@1 with
  best-of-N, vendor scaffolds or results using different tool budgets.
- Documents/analysis: AA-Briefcase, GDPval, GDP.pdf, source citation accuracy,
  spreadsheet formula checks and rendered artifact inspection.
- Research: grounded-source correctness and abstention; Omniscience and LCR are
  supporting signals, not a guarantee of factuality.
- Vision/multimodal: modality-specific benchmarks such as MMMU-Pro plus actual
  input handling through the route. Text-only index rank cannot prove vision.
- Tools/automation: objective completion and side-effect correctness, with
  realistic permission and failure paths; do not reward success after an
  unauthorized action.

If extracting machine-readable page data, require an exact slug match and known
units. Check a sample against the rendered page. Multiple embedded rows, missing
fields or a changed schema require investigation; never choose the nearest name
or silently regenerate a misleading table. Keep minimal selected public values,
source URLs and retrieval dates; do not commit raw HTML, credentials or payloads.

## 3. Cost and Pareto comparisons

Read [OpenRouter models API](https://openrouter.ai/api/v1/models) and relevant
provider endpoints. Record input/output/cache prices, reasoning billing, request
and search/image fees, provider premiums, time-of-day/weekly discounts and long
context tiers. A catalogue's starting price is not a guaranteed invoice. Model
selection uses this common published-cost basis, independent of subscriptions,
quotas and account billing arrangements. Runtime identifiers are resolved later.

Estimate USD as `(uncached_input*input_rate + cached_input*cache_rate +
billed_output*output_rate)/1e6 + other_fees`. Include all child and parent calls,
failed attempts and verification. If usage includes reasoning inside output,
do not count it twice. Use actual usage records to verify spend after execution.

Pareto selection is a method, not a benchmark. A candidate is dominated only
when another eligible candidate is no more costly and at least as good on the
same workload metric, with a strict improvement in one. Filter for modality,
permissions, context and reliability first. Missing scores do not imply failure.
Keep separate frontiers for terminal work, documents, UI and other workloads;
an aggregate frontier cannot disqualify a specialist.

The script filters to the prescribed effort for each model and excludes unknown
or mismatched measured efforts. Keep those rows as supporting evidence only.
The script can compare AA index against AA benchmark cost/task, or a workload
score against an explicit fixed-token scenario. The latter is a price sensitivity
calculation, not measured cost per successful task. Do not compare AA's measured
benchmark bill directly with another harness's invoice. Recompute using current
route prices and observed token use when available. Show uncertainty, overlapping
confidence intervals and promotion sensitivity; do not optimize noise.

```sh
python3 scripts/pareto.py --metric intelligence --cost aa_task
python3 scripts/pareto.py --metric terminal --cost scenario --input-tokens 20000 --output-tokens 5000
python3 scripts/pareto.py --metric briefcase --cost scenario
python3 scripts/pareto.py --metric webdev --cost scenario
```

Run from this skill directory. The script excludes proxy identities, missing
values and unsupported metric/cost combinations, and prints exclusions.

## 4. Representative validation and promotion

Before changing a default, compare the current default and a small shortlist on
representative, bounded work: extraction with exact answers, a repository bug,
a tool workflow, a sourced synthesis, a document/table deliverable, and UI or
multimodal tasks when those capabilities matter. Use sanitized fixtures. Run
paid calls only within the user's authorized spend; no budget means no invented
benchmark spending allowance. Public research alone supports a provisional prior.

Use the same prompts, files, harness, acceptance checks and comparable effort.
Blind the evaluator where practical. Record completed/attempted tasks, actual
spend, tokens, latency, retries, review time and failed/malformed tool calls.
One success is a smoke test, not a success-rate estimate. Repeat stochastic cases
and report uncertainty; a new expensive default needs a demonstrated benefit.

Optimize total cost per accepted task under the required reliability and time
constraints. Promote only for observed savings or material capability gains;
keep a known fallback. Remove obsolete recommendations and explain the reason.
Do not silently weaken privacy, tool permissions or required review policy.

## 5. Publish and verify

Update `model-evidence.json`, regenerate/inspect the catalogue and workload
fallback orders, run the Pareto
script and its tests, and validate skill and plugin metadata. Review changed
recommendations and exact identity joins. If reviewer routing changes, synchronize
`references/reviews.md` into the review plugin's release copy and bump both
affected plugins; the repository equality test prevents policy drift. Bump the plugin version, document
changes, complete repository checks and pre-commit review, then publish.
Refresh and read back the local installed version. Start a new task and verify
skill discovery and tool use. Publication, scheduler configuration, successful
update and task pickup are separate facts. Do not change review procedure or
gates as a side effect of a model-evidence refresh.
