---
name: optimise-ci
description: Reduce local testing and continuous integration duration or compute use from measured bottlenecks, while preserving required verification and release gates. Use when designing or improving test execution, CI pipelines or deployment verification.
---

# Optimise CI

This skill ships with the SCG router; see [automatic updates](../../references/updates.md).
There is no per-plugin updater or schedule to configure.

Improve waiting time or compute use without losing evidence for correctness. Choose the optimisation from measurements and repository boundaries.

## Establish the baseline

Identify the canonical local commands, required remote checks, deployment triggers, ownership rules and release gates. Check whether a push deploys immediately.

Measure the stages that dominate time. Separate queue time, setup, verification, total pipeline elapsed time and aggregate runner time. Record failures, cancellations and retries separately from successful samples.

Save revision or source tree, dependency state, runner class, worker settings, cache conditions, commands, selected coverage, exit status and sample count. Historical statistics provide context; they do not establish a controlled improvement.

Choose the smallest useful change: correct caching, remove duplicate work, tune concurrency, reuse equivalent passing results, or select affected checks. Reuse a reliable existing task graph. Avoid introducing a framework when a small policy or command change is sufficient.

## If selecting affected checks

Use one verification policy for local and remote entry points where applicable. Keep provider event context and reporting in small adapters.

- Map complete owned test suites and runtime consumers, including shared authentication hidden inside feature folders.
- Include non-imported inputs such as fixtures, assets, generated files, templates and dynamic loading.
- Combine multiple changed domains as a union. Run shared checks once. Include affected consumers and cross-boundary integration checks.
- Preserve universal checks justified by the repository. Backend changes can require packaging, migrations or infrastructure tests outside their domain.
- Use the full required suite for shared foundations, dependencies, verification policy, unknown ownership or unproven impact. Missing graphs or trusted baselines cannot narrow verification.
- Preserve ownership across deletions and moves using both revisions. Local selection must include staged, unstaged and untracked inputs.
- Fail visibly if a selected component has no expected tests. Propagate every selected command failure, interruption or invalid exit result.

Expose an inspectable plan with selected scopes, reasons and fallback decisions. Retain an explicit full mode. Keep selection policy tests inside the required verification path.

Test realistic counterexamples: multiple domains, shared callers, hidden authentication, filesystem inputs, deletes, unknown paths, missing history, absent tests and selected-command failure. Each test must catch a named defect.

## Preserve integration and release evidence

Use the correct comparison base for each event. Verify the final combined candidate before integration. Refresh the actual target revision when it advances; cached pull-request metadata may lag.

When deployment verification uses an accumulated change set, compare against the last proven actual deployment to that environment. Prefer an authoritative deployed-revision receipt. A skipped deployment or successful credentials check cannot advance this baseline.

If reconstructing deployment history, inspect enough history to prove the latest actual deployment completion. Older runs can deploy later through reruns. Incomplete history, ambiguous state or incompatible verification policy requires full verification. Retain existing deployment approvals, identity checks, immutable artifacts and acceptance gates.

Keep required status reporting stable. Diagnostic overrides must not satisfy required merge or release verification. Do not turn this skill into permission to deploy or bypass a gate.

Cache keys must account for relevant sources, dependencies, toolchains and environments. Reusing cached downloads is different from reusing a passing test result. Reuse results only when their tested inputs and relevant environment remain equivalent.

## Validate and benchmark the change

Freeze source and revision during measurement. Keep setup environments outside scanned source directories. Record warm-up and failed attempts separately.

For affected verification, run a full control and representative selections on the same candidate and runner profile. Include a multi-domain selection check. For other optimisations, compare equivalent workloads and disclose changed conditions.

More workers can increase contention and failures. Tune concurrency from observed evidence without weakening assertions, timeouts or failure reporting to obtain a better number.

Check local execution and the actual authorised remote CI path. A simulation validates policy decisions, not provider execution. Confirm retained reports show the intended source, selection, completed checks and success. Verify the integrated tree matches the passing candidate before claiming integration complete.

Report before and after metrics with clear denominators. Keep verification duration separate from total pipeline elapsed time and aggregate compute. Label single samples and cache limitations. Do not infer domain rankings, typical savings or failure-rate improvements without supporting samples.

Stop when required checks pass and the measured improvement addresses the bottleneck. Retain an easy full-verification path; add recurring controls only when justified and authorised.

For a concrete example and observed pitfalls, read [the worked example](references/worked-example.md). Its commands, provider and domain mapping are local to that repository.
