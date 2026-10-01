# Catalogue analysis — 2026-09-12

Coverage: **19 external entries + 7 Codex entries + 1 excluded hidden
system row** (`codex-auto-review`). Standard Muse has two measured effort rows.
The router registry and active mixed catalogue were read locally. No paid local
model evaluation completed: research subagents failed before inference. These
recommendations are public-evidence priors, not measured local success rates.

The Grok row was refreshed on 22 September 2026 from the live OpenRouter
listing and [Artificial Analysis](https://artificialanalysis.ai/models/grok-4-7)
(`grok-4-7`, `xhigh`) when the router roster moved to 4.7; every other row keeps
its 2026-09-12 retrieval.

Selection covers **22 distinct models**, with one prescribed effort each.
The 26 visible catalogue entries include runtime aliases of the same GPT models;
those aliases do not create different cost or quality tiers. Select the model
first, then resolve the identifier accepted by the current tool.

## Prescribed effort, reference price and role

USD per million input/output tokens from the [OpenRouter public API](https://openrouter.ai/api/v1/models).
These are comparison prices, independent of account plans or subscriptions,
and advertised starting rates subject to provider routing, discounts,
cache/search fees and context tiers. GLM Flash was visibly 50% off; DeepSeek Flash
includes schedule overrides. Kimi and DeepSeek Pro figures are provider-specific.
GPT-5.5 and GPT-5.4 Mini use published AA reference prices; Spark has no verified
comparable price. Contributor permits prompts/outputs to improve Meta products per its
[listing](https://openrouter.ai/meta/muse-spark-1.3-contributor).

| Model identifier | Prescribed effort | Input / output USD | Role and limitations |
| --- | --- | --- | --- |
| `anthropic/claude-fable-5.1` | `max` | 10 / 50 | Premium analysis/document and UI ceiling; expensive, reserve for a demonstrated gap. |
| `anthropic/claude-haiku-4.5` | `none` | 1 / 5 | Older fast lightweight option; sparse current task evidence and poor cost advantage here. |
| `anthropic/claude-opus-5` | `max` | 5 / 25 | Strong document quality and terminal work; use focused escalation, not blanket delegation. |
| `anthropic/claude-sonnet-5` | `max` | 2 / 10 | Provider/ecosystem fit or explicit choice; current general value weaker than cheaper options. |
| `deepseek/deepseek-v4-pro-0813` | `max` | 0.57816 / 1.73448 | Snapshot matched through AA display name 0813; Flash beats it on the current aggregate and terminal evidence. |
| `deepseek/deepseek-v4.1-flash` | `max` | 0.15 / 0.6 | Very economical tool/repository worker; strong automation score; cheap cache reads. Rates may vary by schedule. |
| `google/gemini-3.1-pro-preview` | `high` | 2 / 12 | Legacy specialist/compatibility option; scientific and multimodal signals, weak current agentic aggregate. |
| `google/gemini-3.8-flash` | `high` | 0.75 / 3.75 | Multimodal candidate with strong MMMU-Pro; not the cheapest text worker. |
| `meta/muse-spark-1.3-contributor` | `xhigh` | 0.1 / 0.2 | Promising low-price route, but no independent tier-specific score; training-use terms and local qualification gate. |
| `meta/muse-spark-1.3` | `max` | 1.25 / 4.25 | Strong reasoning/document synthesis tier. xhigh/max grouped for routing only; scores stay separate. |
| `moonshotai/kimi-k3` | `max` | 2.3027 / 11.5502 | UI specialist and strongest LCR in this measured set; comparatively expensive output and weak terminal v4 score. |
| `openai/gpt-5.6-luna` | `max` | 0.2 / 1.2 | Cheap general candidate for bounded work; Good PDF/LCR for price. |
| `openai/gpt-5.6-sol` | `max` | 2 / 10 | Balanced harder coding/automation candidate; refreshed reference price. |
| `openai/gpt-6-astra` | `max` | 10 / 50 | Strongest measured terminal score and WebDev ceiling here; use focused high-consequence reasoning, mindful of API price. |
| `openai/gpt-6.1-sol` | `high` | Unverified | Preferred pre-commit reviewer; lane-specific availability fallbacks are in [review routing](reviews.md). No independent benchmark row in this snapshot. Not a general-work pick. |
| `qwen/qwen3.8-max-0902` | `xhigh` | 2 / 6 | Exact Arena UI evidence, preliminary and overlapping Kimi/Opus intervals. AA undated row is a proxy and excluded from AA frontiers. |
| `x-ai/grok-4.7` | `xhigh` | 1.6 / 4.8 | Automation/document alternative; no blanket cost advantage. Search capability requires tool/route verification. |
| `z-ai/glm-5.3-flash` | `max` | 0.075 / 0.25 | Lowest token-price general starting point; discounted rate, so refresh. Local task qualification still needed. |
| `z-ai/glm-5.3` | `max` | 1.4 / 4.4 | Stronger terminal capability than Flash with much higher cost; useful targeted escalation. |
| `gpt-5.5` | `xhigh` | 5 / 30 | Legacy compatibility/reproduction; no automatic advantage over newer models. |
| `gpt-5.4-mini` | `xhigh` | 0.75 / 4.5 | Lightweight legacy option; weak current terminal score; verify runtime availability. |
| `gpt-5.3-codex-spark` | `xhigh` | Unverified | Latency-oriented candidate; no exact independent benchmark row found. Do not invent a ranking. |
| `xiaomi/mimo-v2.6-pro` | `xhigh` | Unverified | No independent benchmark row found. |

## Comparable benchmark evidence

Each linked row points to its exact AA page. II = Intelligence Index **v4.3**;
TB = Terminal-Bench **v4.0** pass rate; Auto = AutomationBench-AA; PDF = GDP.pdf
all-pass; LCR = AA-LCR v1.1; BC = Briefcase Elo. Percentages are multiplied by 100.
AA cost/task is its benchmark cost, not your invoice or cost per accepted task.
Dashes mean missing, never zero. Qwen AA figures are deliberately marked proxy.
Haiku's aggregate Intelligence Index is estimated by AA, not a complete measured
v4.3 suite result; its absent cost/task already excludes it from that frontier.

| Model / measured effort | II | AA $/task | TB % | Auto % | PDF % | LCR % | BC Elo |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| [claude-fable-5.1 / max](https://artificialanalysis.ai/models/claude-fable-5-1) | 53.37 | 7.63 | 52.02 | 59.38 | 26.20 | 85.33 | 1661.82 |
| [claude-haiku-4.5 / none](https://artificialanalysis.ai/models/claude-4-5-haiku) | 15.41 | — | — | — | — | 49.67 | — |
| [claude-opus-5 / max](https://artificialanalysis.ai/models/claude-opus-5) | 50.70 | 5.86 | 48.99 | 56.57 | 21.60 | 79.33 | 1644.90 |
| [claude-sonnet-5 / max](https://artificialanalysis.ai/models/claude-sonnet-5) | 38.36 | 5.09 | 14.14 | 36.51 | 13.20 | 82.00 | 1355.19 |
| [deepseek-v4-pro-0813 / max](https://artificialanalysis.ai/models/deepseek-v4-pro) | 36.28 | 0.67 | 14.14 | 56.71 | 11.40 | 80.33 | 1264.67 |
| [deepseek-v4.1-flash / max](https://artificialanalysis.ai/models/deepseek-v4-1-flash) | 39.55 | 0.27 | 26.77 | 68.89 | 12.80 | 84.00 | 1423.72 |
| [gemini-3.1-pro-preview / not specified](https://artificialanalysis.ai/models/gemini-3-1-pro-preview) | 30.36 | 0.67 | 4.04 | 35.43 | 17.80 | 82.00 | 458.83 |
| [gemini-3.8-flash / high](https://artificialanalysis.ai/models/gemini-3-8-flash) | 41.19 | 1.24 | 19.70 | 59.93 | 21.00 | 81.33 | 1201.59 |
| muse-spark-1.3-contributor / not specified | — | — | — | — | — | — | — |
| [muse-spark-1.3 / max](https://artificialanalysis.ai/models/muse-spark-1-3) | 48.17 | 1.60 | 33.33 | 57.85 | 26.60 | 83.00 | 1589.18 |
| [kimi-k3 / max](https://artificialanalysis.ai/models/kimi-k3) | 43.78 | 2.00 | 12.63 | 58.27 | 22.00 | 88.67 | 1492.58 |
| [gpt-5.6-luna / max](https://artificialanalysis.ai/models/gpt-5-6-luna) | 37.50 | 0.18 | 11.62 | 50.21 | 24.00 | 83.67 | 1339.38 |
| [gpt-5.6-sol / max](https://artificialanalysis.ai/models/gpt-5-6-sol) | 47.06 | 1.99 | 39.90 | 60.08 | 27.20 | 84.00 | 1475.00 |
| [gpt-6-astra / max](https://artificialanalysis.ai/models/gpt-6-astra) | 52.81 | 3.26 | 59.09 | 68.49 | 31.00 | 80.67 | 1562.01 |
| [PROXY qwen3.8-max-0902 / not specified](https://artificialanalysis.ai/models/qwen3-8-max) | 40.30 | 2.67 | 18.69 | 49.23 | 20.20 | 78.33 | 1387.89 |
| [grok-4.6 / high](https://artificialanalysis.ai/models/grok-4-6) | 44.41 | 1.86 | 21.21 | 66.68 | 17.00 | 80.33 | 1534.13 |
| [grok-4.7 / xhigh](https://artificialanalysis.ai/models/grok-4-7) | 46.45 | 3.74 | 25.76 | 65.56 | 20.00 | 76.67 | — |
| [glm-5.3-flash / max](https://artificialanalysis.ai/models/glm-5-3-flash) | 41.91 | 0.25 | 32.83 | 60.37 | 15.40 | 80.00 | 1449.23 |
| [glm-5.3 / max](https://artificialanalysis.ai/models/glm-5-3) | 44.86 | 2.01 | 41.92 | 62.20 | 11.20 | 79.67 | 1512.51 |
| [muse-spark-1.3 / xhigh](https://artificialanalysis.ai/models/muse-spark-1-3-xhigh) | 45.16 | 1.37 | 16.67 | 56.84 | 24.20 | 83.00 | 1483.22 |
| [gpt-5.5 / xhigh](https://artificialanalysis.ai/models/gpt-5-5) | 38.63 | 2.63 | 14.65 | 47.30 | 21.20 | 84.33 | 1135.79 |
| [gpt-5.4-mini / xhigh](https://artificialanalysis.ai/models/gpt-5-4-mini) | 24.58 | 0.41 | 2.02 | 26.20 | 13.40 | 77.00 | 719.24 |
| gpt-5.3-codex-spark / not specified | — | — | — | — | — | — | — |

The prescribed level is the highest supported plain reasoning level, except
GPT-6.1 Sol at `high`, which is the owner's exact pre-commit reviewer setting.
Astra and GPT-5.6 Sol use `max`; `ultra` adds automatic delegation and is
excluded from bounded child assignments. Haiku supports only `none`; this is
not an omitted setting. Gemini uses `high`; Qwen 0902, Grok and Contributor use
`xhigh`.

The benchmark table retains measurements at other or unspecified efforts for
transparency. They do not certify the prescribed configuration: in particular,
Qwen's WebDev effort is unspecified and the Gemini Pro AA effort is
unspecified, so both stay supporting evidence excluded from the calculator's
prescribed-effort frontiers. Grok is the exception: the 4.7 AA row is measured
at the prescribed `xhigh`, so it is compared on the AA frontier instead of
being excluded from it, and its Arena WebDev row has no 4.7 measurement yet.
The `grok-4.6 / high` row is kept as the superseded version's measurement.
Standard Muse `xhigh` stays in the evidence but only `max` is selected.

The JSON also preserves SciCode, Omniscience, MMMU-Pro, Briefcase confidence
intervals, cache pricing and source identity. Do not infer support from missing
vision scores. OpenRouter modality declarations still need route-level checks.

## Independent cross-check: Arena WebDev

[WebDev rankings](https://arena.ai/leaderboard/code), published September 11,
retrieved September 12: Astra max 1800 ±16; Fable 5.1 max 1758 ±14; Opus 5 max
1687 ±7; Qwen 0902 1681 ±15 (preliminary); Kimi K3 max 1674 ±11; Muse max
1652 ±12 and xhigh 1623 ±14; GLM Flash 1607 ±12. These support UI specialist
choices but overlapping intervals do not establish a reliable ordering among
Opus, Qwen and Kimi. Frontend preference is different from terminal debugging.
The JSON records exact rows, effort, vote counts and uncertainty. Other rows
preserved in the evidence include GLM 5.3, DeepSeek Flash, Grok and Gemini Flash;
the calculator admits only rows matching the prescribed effort.

## Interpretation and boundaries

- GLM Flash and DeepSeek Flash are strong low-cost candidates. Cheap tokens do
  not make every task cheap: include reasoning, tool loops and failed retries.
- Muse is a good synthesis/document prior; its standard xhigh/max distinction
  stays in evidence even though user policy treats them as one selection tier.
- Astra leads terminal v4 in this set; Fable/Opus have strong document results.
  Their reference costs justify narrow escalation, not automatic whole-task fanout.
- Kimi's long-context score and Qwen's exact UI row justify specialist use even
  when an aggregate cost frontier would remove them.
- Contributor is unranked without its own evidence. Low price is not proof that
  standard Muse's benchmark performance transfers to it.
- Older models remain useful for reproduction, latency, compatibility or explicit
  requests; model age or a global score alone is not a reason to remove them.

See [refresh methodology](refresh.md) for source standards, harness comparability,
local validation and promotion. Pareto membership is computed from declared
axes and eligibility, not asserted as an intrinsic property of a model.
