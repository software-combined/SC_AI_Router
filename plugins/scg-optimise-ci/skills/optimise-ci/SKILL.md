---
name: optimise-ci
description: Reduce local testing and continuous integration duration or compute use from measured bottlenecks, while preserving required verification and release gates. Use when designing or improving test execution, CI pipelines or deployment verification.
---

# Optimise CI

This skill ships with the SCG router; see [automatic updates](../../references/updates.md).
There is no per-plugin updater or schedule to configure.

Improve waiting time or compute use without losing evidence for correctness.
Derive commands, job names, paths and release rules from the target repository.
The method applies across languages, build tools and CI providers.

## Establish the baseline

Identify canonical local commands, required remote checks, deployment triggers,
ownership rules and release gates. Check whether a push deploys immediately.
Read repository instructions, task scripts, CI definitions and dependency locks.
If remote CI is absent, improve the local path and report that boundary.
Choose the outcome to improve: feedback latency, acceptance latency or compute use.
State the first observable proof, such as a complete required pipeline finishing sooner.

Inspect a representative successful run and its dependency graph.
Find the critical path: the dependent jobs that determine completion time.
Separate queue time, setup, verification, total pipeline elapsed and aggregate job execution.
Record failures, cancellations and retries separately from successful samples.

Save run links, event and target branch, source revisions or trees, dependencies,
runner classes, worker settings, cache conditions, commands, coverage, skips and sample count.
Record actual checkout revisions and trees, or artifact digests, alongside event head metadata.
For temporary merge commits, compare the tested tree with the reviewed and integrated trees.
Use precise timestamp boundaries. Summed job time is not a bill across different runner classes.
Historical statistics provide context; they do not establish a controlled improvement.

Choose the smallest change that addresses the measured bottleneck.
Consider dependency cleanup, correct caching, duplicate work, worker counts,
equivalent result reuse or affected checks. Reuse the existing task graph.
A longer individual job may be off the critical path; speeding it up may not help completion.

## If changing the job graph

Remove a dependency only after checking artifacts, generated inputs, services,
credentials, shared state and required execution order.
Independent jobs can overlap; build and test consumers must retain their producers.
Check runner capacity and contention before adding workers or jobs.
Account for extra setup, artifact transfers and work performed before another check fails.
Splitting jobs changes timeout and retry boundaries; verify that required work can still complete.

Preserve required check names, event filters, path scope, branch rules and matrix coverage.
Check the provider's actual semantics for failed, cancelled, timed-out and skipped prerequisites.
An intentionally skipped job and missing required evidence need different treatment.
The final gate must require every applicable result and block incomplete or failed verification.
Diagnostic overrides and metadata-only events must not create passing acceptance evidence.

Validate the affected event and result paths, including failures and cancellation.
Use realistic workflow tests where useful, then verify the authorised remote path.
Successful YAML parsing or a green aggregate label alone cannot prove complete verification.

## If selecting affected checks

Use one verification policy for local and remote entry points where applicable.
Keep provider event context and reporting in small adapters.

- Map complete owned suites and runtime consumers, including authentication hidden inside feature folders.
- Include non-imported inputs: fixtures, assets, generated files, templates and dynamic loading.
- Combine changed domains as a union. Run shared checks once and include affected consumers and integration checks.
- Preserve justified universal checks. Backend changes can affect packaging, migrations or infrastructure tests.
- Use full required verification for shared foundations, dependencies, policy changes, unknown ownership or unproven impact.
- Preserve ownership across deletions and moves using both revisions. Collect staged, unstaged and untracked inputs separately, then union their impact. Opposing edits must not cancel out of selection.
- Fail visibly when an expected suite is absent. Propagate command failures, interruption and invalid exit results.

Expose selected scopes, reasons and fallback decisions. Retain an explicit full mode.
Keep selection policy tests inside the required verification path.
Test realistic counterexamples: multiple domains, shared callers, hidden authentication,
filesystem inputs, deletes, unknown paths, missing history, absent tests and command failure.
Each test must catch a named defect.

## Preserve integration and release evidence

Use the correct comparison base for each event. Verify the final combined candidate.
Refresh the actual target revision when it advances; cached pull-request metadata may lag.

For deployment verification over accumulated changes, compare against the last proven deployment to that environment.
Prefer an authoritative deployed-revision receipt.
A skipped deployment or successful credentials check cannot advance this baseline.
Older runs can deploy later through reruns, so inspect enough history to establish completion order.
Incomplete history, ambiguous state or incompatible policy requires full verification.
Retain deployment approvals, identity checks, immutable artifacts and acceptance gates.
This skill grants no permission to deploy or bypass protection.

Cache keys must account for relevant sources, dependencies, toolchains and environments.
Reusing downloaded dependencies differs from reusing a passing test result.
Reuse results only when tested inputs and the relevant environment remain equivalent.

## Validate and benchmark

Freeze each candidate during measurement. Keep setup environments outside scanned source directories.
Compare equivalent workloads and disclose changed conditions, including added regression tests.
Record warm-up, failed attempts and reruns separately.
For affected verification, compare a full control with representative selections on the same candidate and runner profile.
Include a multi-domain selection check.

Check local execution and the actual authorised remote path.
Confirm reports identify the intended candidate, expected suites, skips and completed results.
A simulation proves its model; it does not prove provider execution or deployment.
Verify the integrated tree matches the passing candidate before claiming integration complete.

Report elapsed time and aggregate execution separately, with sample counts and cache limitations.
Explain tradeoffs: overlap can reduce waiting while adding setup and runner use.
Label one successful pair as observed evidence, not typical savings or reliability proof.
Use additional comparable samples when variability could change the decision; avoid rerunning solely for reassurance.
Do not weaken assertions, timeouts or failure reporting to obtain a better number.

Stop when required checks pass and evidence addresses the chosen bottleneck.
Report the change, before/after measures, preserved gates, limitations and integration state.
Keep the existing full-verification path; add recurring controls only when justified and authorised.

Read [the worked example](references/worked-example.md) for the Router's measured result and pitfalls.
Its provider, commands and job layout are examples, not requirements for another repository.
