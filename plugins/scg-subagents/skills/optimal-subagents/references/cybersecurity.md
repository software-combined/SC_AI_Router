# Security model selection

Evidence checked **2026-09-12**. These are research-based starting choices for
authorised work, not a locally validated ranking. Security quality takes priority
over the cheapest model. Price still matters after accuracy, permitted use,
data handling and reliable completion meet the task's requirements.

## Choose by the actual security task

| Task | Starting choice | Why and when to change |
| --- | --- | --- |
| Critical defensive reasoning, threat modelling, incident interpretation, remediation design | GPT-6 Astra `max`; Opus 5 `max` for an independent difficult finding | Strong reasoning/security priors; retain human approval for consequential action. Neither is proved best for every SOC task. |
| Routine secure-code review, triage, detection engineering and patch validation | GPT-5.6 Sol `max` | Balanced candidate with encouraging source-review evidence. Escalate an unresolved high-impact question to Astra or Opus. |
| Difficult vulnerability reproduction or pentesting in an explicitly authorised isolated lab | Kimi K3 `max` | Quality-first candidate from a matched CyberGym-based study. Reliable production network pentesting is not established; qualify on the actual task first. |
| Broad source-vulnerability discovery within the agreed scope | DeepSeek V4 Pro 0813 `max` | Attractive cost per validated result; budget independent validation because false leads and run-to-run variability matter. Use Kimi for an unresolved hard reproduction. |
| Web application testing in an authorised lab | GLM 5.3 `max`, with Kimi as an alternative | Small web-lab evidence favours GLM at a different effort. This is a candidate for qualification, not a measured max-effort winner. |
| Emerging low-cost security worker | DeepSeek V4.1 Flash `max` | Strong new vendor scores, insufficient independent exact-version replication. Promote only after representative validation. |
| Log extraction, inventory formatting, source indexing and report assembly | GLM Flash or Luna `max`; Muse `max` for prose synthesis | Bounded support work only. Retain primary evidence and escalate ambiguous security judgments. No cheap worker issues the final all-clear. |

For an important investigation, start with one capable lead. Add one independent
validator only where the impact or uncertainty warrants it. A useful split is
DeepSeek/Kimi discovery followed by Sol/Opus/Astra review of a concrete finding
and proposed repair. Agreement between models is not validation: require source
evidence, a reproducible permitted check, and patch/negative-control results.
Do not automatically buy a second full investigation or parallelise every model.

## Production usability is part of eligibility

OpenAI's Astra launch cyber scores were measured without production safeguards
and report the best score at any effort. They cannot establish what our `max`
route will complete. Standard Astra remains useful for defensive review and
patching, while advanced reproduction can encounter restrictions.
[Astra launch](https://openai.com/index/gpt-6-astra/).

Current OpenAI help identifies Daybreak Blue with Sol, and Daybreak Red with
GPT-5.6 Cyber. Reduced Astra refusals currently require Red; Blue support is
planned. An adjusted Astra configuration in the system card is evaluation
evidence, not proof of our entitlement. Approved access does not automatically
include ZDR or customer-facing use. These cyber aliases are outside our current
catalogue and are not a silently available fallback.
[Current access rules](https://help.openai.com/en/articles/20001258-trusted-access-for-cyber),
[system card](https://deploymentsafety.openai.com/gpt-6-astra/cybersecurity-safety-training-and-evaluation).

Opus 5 supports source vulnerability discovery, but default restrictions cover
some pentesting, binary analysis and exploit generation. Fable 5.1 reduces some
interventions; that does not establish unrestricted completion. Some Claude
product flows can fall back to Opus 4.8, so record any reported served-model
change. Anthropic's Cyber Verification Program is a separate access path.
[Opus release](https://www.anthropic.com/news/claude-opus-5),
[Fable release](https://www.anthropic.com/claude-fable-and-mythos-5-1).

Verify the actual organisation, product surface, provider route and data terms
before relying on an approval. Do not assume OpenRouter inherits a first-party
cyber entitlement. Anthropic's current self-serve verification has ZDR eligibility
limits; sales-managed customers must resolve their account-specific arrangement.
Do not weaken retention/privacy requirements to gain access.
[Anthropic safeguards and access](https://support.claude.com/en/articles/14604842-real-time-cyber-safeguards-on-claude-opus-and-sonnet).

Open weights do not imply private hosting, zero retention, no refusals or safe
behaviour. Provider policy and the actual hosting route still apply. A study
observing no refusals is not a guarantee for future tasks or our serving route.

For an apparent false refusal on permitted work, make one truthful clarification
of ownership, scope and the defensive objective where useful. Then use the
provider's approved access/support path or continue a separately permitted part
of the task. Do not disguise intent, jailbreak, bypass an account restriction or
cycle models merely to evade a denial. A different route must independently be
authorised for the task and data. No eligible route means report the exact gap.

## Coverage of the maintained catalogue

Prices below are USD per million input/output tokens, rounded from the public
OpenRouter API on September 12, except legacy models from the general catalogue.
They are reference starting prices, not actual workload cost. Cache, context,
reasoning tokens, provider and discounts can change the bill. All prescribed
efforts are unchanged; supporting studies often used other/undisclosed efforts.

| Model | Effort | Input / output | Security role and evidence limit |
| --- | --- | ---: | --- |
| Claude Fable 5.1 | `max` | 10 / 50 | Premium defensive escalation; no comparable independent exact-version cyber result found in this pass. Production restrictions remain. |
| Claude Haiku 4.5 | `none` | 1 / 5 | Support extraction only; no exact strong cyber evidence found. |
| Claude Opus 5 | `max` | 5 / 25 | Strong source-review/validation candidate; default pentest restrictions can prevent completion. |
| Claude Sonnet 5 | `max` | 2 / 10 | Defensive alternative when locally validated; no clear cyber value advantage over Sol established. |
| DeepSeek V4 Pro 0813 | `max` | 0.578 / 1.734 | Value discovery candidate; exact snapshot evidence from two operators, effort not established. |
| DeepSeek V4.1 Flash | `max` | 0.15 / 0.60 | Promising inexpensive candidate; new vendor cyber scores need independent replication. |
| Gemini 3.1 Pro Preview | `high` | 2 / 12 | Supporting multimodal/context analysis; no exact compelling cyber result found. |
| Gemini 3.8 Flash | `high` | 0.75 / 3.75 | Supporting extraction/visual evidence; no exact compelling cyber result found. |
| Muse Spark 1.3 Contributor | `xhigh` | 0.10 / 0.20 | Not a sensitive security-data default: training-use terms and independent identity/evidence gaps. |
| Muse Spark 1.3 | `max` | 1.25 / 4.25 | Synthesis assistant; general reasoning strength does not establish pentest reliability. Keep xhigh/max as the same selection tier, not identical measurements. |
| Kimi K3 | `max` | 2.303 / 11.550 | Hard lab/reproduction candidate; strongest matched Fireworks result, but government/operator evidence shows major autonomous limits. |
| GPT-5.6 Luna | `max` | 0.20 / 1.20 | Bounded support; promising harness-specific IDOR results, insufficient evidence for final security acceptance. |
| GPT-5.6 Sol | `max` | 2 / 10 | Balanced defensive lead; standard access differs from approved Daybreak access. |
| GPT-5.6 Terra | `max` | 2 / 12 | IDOR evidence supports defensive use, but no advantage over Sol established here. |
| GPT-6 Astra | `max` | 10 / 50 | High-consequence defensive reasoning; unsafeguarded benchmark scores do not prove production pentest completion. |
| Qwen3.8 Max 0902 | `xhigh` | 2 / 6 | Candidate only; undated Qwen cyber rows cannot be assigned to this snapshot. |
| Grok 4.6 | `xhigh` | 2 / 6 | Source-review alternative with repeatability evidence; measured effort unclear, no basis to call it the best pentester. |
| GLM 5.3 Flash | `max` | 0.075 / 0.25 | Cheap supporting worker; small high-effort web-lab result is not max-effort assurance. |
| GLM 5.3 | `max` | 1.4 / 4.4 | Web-lab/source-review candidate; distinguish final model from preview and high from max. |
| GPT-5.5 | `xhigh` | 5 / 30 | Older reproduction baseline; Fireworks measured a different/unspecified effort, not automatic better value than current choices. |
| GPT-5.4 Mini | `xhigh` | 0.75 / 4.5 | Supporting legacy option only; no exact compelling cyber evidence found. |
| GPT-5.3 Codex Spark | `xhigh` | Unverified | Latency/compatibility support only; price and exact cyber evidence remain unverified. |

Exact callable IDs and complete pricing conditions are in [catalogue.md](catalogue.md).
Missing evidence means unranked for that task, not incapable.

## Qualify before making a model the security default

Read [the cyber evidence ledger](cybersecurity-evidence.md) and the general
[refresh method](refresh.md). Refresh exact versions, prescribed effort support,
production policies and route terms as well as scores. Keep source review,
vulnerability reproduction, web/network pentesting, SOC triage and patching as
separate evaluations. Never merge different benchmarks into one cyber score.

Within an explicitly authorised evaluation budget, use a small frozen set of
sanitised, isolated fixtures: known vulnerable examples, patched controls and
representative clean inputs. Fix tools, context, steps, time, access and scoring;
use the prescribed effort and record requested/served identity. Include repeated
runs on the same cases. Do not test against live targets as a side effect of
model selection or acquire broader access to complete a benchmark.

Set the acceptance floor before seeing results: actionable recall and precision,
validated completion, patch correctness, scope adherence, data handling and
failure recovery. Measure false refusals on permitted tasks separately from
correct refusals. Count confident false positives, missed known flaws, fabricated
evidence, incomplete tool sequences and unsupported all-clears as failures.

For cost, count all attempts, reasoning, tools, validation and analyst time.
Use cost per validated finding or correctly resolved case, alongside recall,
precision and completion. Zero validated outcomes has no finite cost per success.
Choose a cost/quality Pareto candidate only within a comparable task cohort and
after the security floor passes. Preserve uncertainty for small samples; a
cheaper model cannot compensate for unacceptable missed findings.

Promote from candidate to operational default only after these checks pass on
the intended serving route. This research release ran no paid cyber evaluations,
target scans or pentests and certifies no autonomous agent for production use.
The separate installed pre-commit reviewer routing remains authoritative.
