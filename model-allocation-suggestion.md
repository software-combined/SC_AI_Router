# Model allocation suggestion

**Software Combined | 11 September 2026 | Proposed configuration, not deployed**

**Objective:** minimise the total cost of correctly completed work, not just the price per token. Use inexpensive models for routine work and stronger models when complexity or consequence justifies them.

## 1. Recommended allocation

| Role | Default model and reasoning effort | Escalation or specialist |
|---|---|---|
| **Orchestrator** | **DeepSeek V4.1 Flash `max`** | **Opus 5 `xhigh`** for a focused plan or difficult decision, then return coordination to DeepSeek. |
| **Explorer** | **DeepSeek V4.1 Flash `high`** for bounded searches; **`max`** for dependency reasoning | **Gemini 3.8 Flash `high`** for time-sensitive or multimodal exploration. |
| **Executor: bounded, testable changes** | **GLM 5.3 Flash `max`** | **Muse Spark 1.3 standard `max`** when implementation is more demanding. |
| **Executor: difficult multi-file work** | **Muse Spark 1.3 standard `max`** | **GPT-6 Astra `max`** for complex terminal-based execution or difficult agentic work. |
| **Research** | **DeepSeek V4.1 Flash `high`/`max`** or **GLM 5.3 Flash `max`**, using actual search/repository tools | **Opus 5 `xhigh`** for difficult synthesis or conflicting evidence. |
| **Debugging** | **GLM 5.3 Flash `max`** for local, reproducible defects | **Opus 5 `xhigh`** for systemic diagnosis; **Astra `max`** when execution and experimentation are the bottleneck. |
| **Simplification** | **GLM 5.3 Flash `max`**, restricted to the staged scope | **Astra `xhigh`** for substantial or consequential refactoring. A no-change result is acceptable. |
| **Planner** | **GLM 5.3 Flash `max`** for routine plans | **Opus 5 `xhigh`** for architecture, migrations and multi-system decisions. |
| **Advisor** | **Opus 5 `xhigh`** for consequential technical decisions | **Astra `xhigh`** as an independent challenge for costly or difficult-to-reverse decisions. |
| **Pre-commit review** | The normal three-lane profile below | The elevated-risk profile below. |

**Escalation rule:** for routine work, seek stronger diagnosis after two substantively different, tested approaches fail to make progress. For security, permissions, money movement, destructive operations, migrations or production-consequential changes, escalate **before mutation**, not after repeated failures.

## 2. Pre-commit allocation

Simplification is a separate writing pass. Correctness, adversarial and quality are three read-only review lanes.

| Pass | Normal work on approved data routes | Elevated-risk work |
|---|---|---|
| **Simplification** | GLM 5.3 Flash `max` | Astra `xhigh`; no change unless behaviour preservation is clear |
| **Correctness** | Muse Spark 1.3 standard `max` | Opus 5 `xhigh` |
| **Adversarial** | GLM 5.3 Flash `max` | Astra `xhigh` |
| **Quality** | DeepSeek V4.1 Flash `max` | GLM 5.3 Flash `max` |

Preserve the existing staged-tree checks, lane ownership and selective re-review rules. This is a proposed policy change, not permission to bypass the currently required review configuration.

**Illustrative four-pass cost:** normal **US$0.1711 per commit**; elevated **US$2.7650 per commit**. These assume **80,000 uncached input tokens and 6,000 billable output tokens per pass**, with DeepSeek at the lower rate. They are fixed-token examples, not measured costs or a budget forecast.

## 3. Model prices

**All prices are USD per 1 million tokens.** Input means uncached input. Cached input is charged at the cache-read rate only when the selected provider actually records a cache hit.

**Pricing basis:** the rates below are reproduced from the 11 September 2026 analysis. They were **not refreshed for this summary** and are not contractual quotes. The underlying report notes cached source responses and unresolved provider/alias details.

| Model / rate scenario | Input / 1M | Output / 1M | Cache read / 1M | Allocation |
|---|---:|---:|---:|---|
| **DeepSeek V4.1 Flash: lower-rate scenario** | **$0.15** | **$0.60** | **$0.003** | Orchestration, exploration, research, quality review |
| DeepSeek V4.1 Flash: doubled-rate scenario | $0.30 | $1.20 | $0.006 | Same roles; budget for the applicable provider/time window |
| **GLM 5.3 Flash** | **$0.15** | **$0.50** | **$0.030** | Bounded execution, local debugging, simplification, routine planning, review |
| **Muse Spark 1.3 standard** | **$1.25** | **$4.25** | **$0.150** | Harder ordinary coding and correctness review |
| **Claude Opus 5** | **$5.00** | **$25.00** | **$0.500** | Difficult diagnosis, planning, advice, elevated correctness review |
| **GPT-6 Astra** | **$10.00** | **$50.00** | **$1.000** | Complex execution, substantial refactoring, elevated adversarial review |
| Gemini 3.8 Flash | $0.75 | $3.75 | $0.075 | Optional fast or multimodal exploration |
| Muse Spark 1.3 Contributor | $0.10 | $0.20 | $0.002 | Optional execution for public or explicitly data-contribution-approved work |

The DeepSeek scenarios preserve the source report's time-based pricing comparison; they do not establish that every provider follows that schedule. Output cost must include **all billable reasoning tokens**, not just the visible response. Taxes, gateway fees, cache writes, tools/search, context tiers, retries and human rework are additional where applicable.

## 4. Conditions before rollout

**Contributor is not the private-data default.** The full analysis records published terms allowing prompts and outputs to improve Meta products. For eligible public or explicitly approved work, use **Contributor `xhigh`** as the low-cost ordinary executor alternative. Do not assume Contributor and standard Muse have identical quality or effort access.

**Certify the exact route.** Confirm model version, provider approval, actual reasoning effort, tool calling and fallback policy. Do not remove Contributor's local `max` exclusion without validation. Use standard Muse `max` only where the route supports and honours it; otherwise use `xhigh` without assuming `max` performance.

**Pilot GLM Flash first.** Its cheap-executor assignment is provisional. The full analysis did not establish a directly comparable coding-agent result for GLM 5.3 Flash; results for GLM 5.3 are not interchangeable. Compare accepted outcomes, completion time and rework before group-wide deployment.

**Confidence carried over from the analysis:** 0.86 in the overall design; 0.66 in GLM Flash as the best cheap executor. This is a recommended starting configuration, not a workload-validated optimum.

## Basis and checking references

This summary preserves the recommendations and price scenarios in **`SCG_Optimal_Model_Routing_Analysis_2026-09-11.md`**, sections 3 to 5 and Appendix A. No new benchmark analysis or live configuration change was performed for this summary.

- [OpenRouter public model/pricing catalogue](https://openrouter.ai/api/v1/models): check the selected model, rate and provider before deployment.
- [Artificial Analysis model leaderboard](https://artificialanalysis.ai/leaderboards/models) and [coding-agent benchmarks](https://artificialanalysis.ai/agents/coding-agents): check the exact model, effort and harness rather than transferring scores between configurations.
- [SCG reviewer model policy at the reviewed commit](https://github.com/software-combined/SC_Agent_plugins/blob/c76fd886958fb417f039861f886010bf3bef76e6/plugins/scg-review/references/reviewer-models.md): the policy reviewed by the source analysis; repository access is required.
