# Cyber evidence ledger

Public sources checked **2026-09-12**. Primary means the evaluator or provider
published its own work; it does not imply independence or reproducibility.
Recommendations in [cybersecurity.md](cybersecurity.md) are our inferences.
Unknown effort never establishes the prescribed max/xhigh configuration.

## Matched reproduction and validation: Fireworks

[Supplier-run study, August 26](https://fireworks.ai/blog/DeepSeek-V4-Pro-Security).
On its common 697-task CyberGym-based cohort, Kimi K3 achieved 68.4% reward at
$4.914/reward; DeepSeek V4 Pro 0813 achieved 53.7% at $2.502/reward. GPT-5.5
was 47.6%/$9.641 and Opus 4.8 was 5.9%/$33.275. Kimi is the quality candidate;
DeepSeek is the value candidate within this experiment.

The supplier observed no DeepSeek refusals in 840 traced primary tasks, a
different denominator. Do not combine its standalone 920-task results with the
matched table. Its harness includes validation and patching; do not attribute
that entire sequence to every CyberGym implementation. Effort is undisclosed,
the serving route differs from ours, and commercial hosting interests apply.
Reported blocks for newer closed models concern this setup, not all defensive
uses. These dollar figures are benchmark costs, not our invoice.

## Source vulnerability rediscovery: Aikido

[Operator study, updated September 1](https://www.aikido.dev/blog/ai-model-benchmarks-aug-21-2026).
Thirty-two recent CVEs, three runs per model, a 30-turn limit and no internet:
DeepSeek V4 Pro 0813 found 28/32 across pooled runs but only 10 consistently;
Opus 5 found 26 pooled/19 consistently, Sol 25/19, Grok 4.6 26/21, Kimi K3
25 pooled, and final GLM 5.3 25/18. DeepSeek's strong pooled discovery came
with more false leads. This motivates validation and repeated-run scoring.

This is source rediscovery, not live pentesting. Effort is not established in
the article. Do not join older Flash results to V4.1 Flash, undated Qwen to
0902, or GLM preview to final. Astra/Fable 5.1/Muse 1.3 are not in the published
main comparison. The operator discloses prerelease GLM collaboration; treat it
as useful commercial evidence, not a neutral universal leaderboard.

## New Flash evidence: DeepSeek

[DeepSeek V4.1 Flash model card](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash)
reports CyberGym 88.1%, SECbench Pro 62.8% and ExploitGym 15.3%. These vendor
results justify a qualification run for a cheap new candidate. They do not
establish that it beats Kimi's 68.4% above: cohorts, harnesses and grading differ.
The card describes a Claude Code harness for SECbench Pro; exact comparable
CyberGym configuration is less clear. No independent exact-version replication
was established in this research pass. Keep provider effort mapping separate
from the card's numeric reasoning setting.

## Small web-lab evidence: HunterBench

[August 2026 results](https://www.hunterbench.com/) use two private labs and
three runs per lab. Reported high-effort scores include GLM 5.3 415/1000,
GLM Flash 328, Kimi K3 229 and DeepSeek V4 Pro 175. These are supporting
web-application task priors, not directly comparable with CyberGym or source
review. The dataset is small/private; prescribed max effort and the exact
DeepSeek snapshot are not established. Do not publish these as max rankings.

## Government cross-check: Kimi K3

[NIST/UK AISI preliminary assessment, July 23, updated August 28](https://www.nist.gov/news-events/news/2026/07/uk-aisi-caisi-preliminary-assessment-kimi-k3s-cyber-capabilities)
reports a 32% ExploitBench score, with arbitrary code execution reached on 0/41
samples. For The Last Ones, Kimi reached step 17 of a 32-step attack path on
average and completed the full path in 1/10 attempts within the 100M-token limit.
This is a simulated network with an intentional path and no active defenders.
Partial milestones are not full compromise success. These results support a
useful lab candidate, not reliable autonomous operation in production.

The [May DeepSeek assessment](https://www.nist.gov/news-events/news/2026/05/caisi-evaluation-deepseek-v4-pro)
predates 0813. It cannot establish the current snapshot's capability or rank.

## Precision and harness effects: Semgrep

[Operator IDOR study, July 22](https://semgrep.dev/blog/2026/kimi-k3s-code-security-results-lack-precision/)
reports guided-prompt precision/recall of .880/.250 for Sol and .684/.226 for
Kimi K3. Kimi's weaker precision increases analyst triage cost. In Semgrep's
own harness, Sol and Luna had near-equal F1 (.617/.616), while Kimi scored .400.
That makes Luna worth testing for bounded triage within an effective harness,
not a proven standalone security lead.
The vulnerability class is narrow, efforts vary, and the vendor's own harness
is part of the result. Do not transfer older GLM/Opus rows to our newer versions
or infer full pentest performance from these figures.

## Multi-stage reliability: Irregular and Enclave

[Irregular, August 19](https://www.irregular.com/research/assessing-kimi-k3-against-offensive-security-benchmarks)
tested self-hosted Kimi K3 on three suites. It recorded a verified CyScenarioBench
solve, but none on the harder FrontierCyber suite. This independently supports
its candidacy while showing the limit of extrapolating bounded technical ability
to sustained autonomous success. The article does not establish our route or
prescribed effort and does not provide a complete matched price comparison.

[Enclave, September 8](https://enclave.ai/blog/muse-spark-13-got-in-then-it-forgot-to-finish-the-task)
reports Muse Spark 1.3 verified none of 11 vulnerable runs, with zero false
positives on four patched controls and $42.95 total cost. The observed problem
was completing and verifying the task after partial progress. This is a small
operator-specific harness result, not proof that Muse is universally incapable.
The article does not establish our fixed effort. It is enough to avoid promoting
Muse from general synthesis to pentest lead without representative testing.

## Frontier capability versus served behaviour

[Astra launch](https://openai.com/index/gpt-6-astra/) reports ExploitGym 42.4%
for Astra, 30.3% Sol, 30.4% Fable 5.1 and 22% Opus 5. Its cyber table excludes
production safeguards and selects the maximum at any effort. This supports a
capability prior, not a production-route comparison at our fixed effort.

The [Astra system card](https://deploymentsafety.openai.com/gpt-6-astra/cybersecurity-safety-training-and-evaluation)
shows large completion differences between standard and adjusted safeguards.
Use the [current access documentation](https://help.openai.com/en/articles/20001258-trusted-access-for-cyber)
for actual product eligibility; experimental configuration labels do not grant
access. Anthropic's [Opus](https://www.anthropic.com/news/claude-opus-5) and
[Fable](https://www.anthropic.com/claude-fable-and-mythos-5-1) disclosures likewise
separate source review from restricted offensive workflows. Check current
[safeguards](https://support.claude.com/en/articles/14604842-real-time-cyber-safeguards-on-claude-opus-and-sonnet)
on the intended route before concluding a model will or will not complete a task.

## What remains unverified

No common independent cyber harness covers all 22 maintained models at their
prescribed efforts and our routes. No local cyber task success, account cyber
entitlement, real bill or production pentest outcome was measured. Public
token prices came from the [OpenRouter models API](https://openrouter.ai/api/v1/models);
they are refreshed selection inputs rather than a benchmark success metric.
The general AA/Pareto evidence remains useful context, but is not a substitute
for task-specific security evidence or representative local qualification.
