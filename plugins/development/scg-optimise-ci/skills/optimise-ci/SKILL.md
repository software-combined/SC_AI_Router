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
Use existing domains, packages, services, native checks or task dependencies where they help.
Affected selection is optional. A repository can improve full verification without inventing domains.

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
Measure complete commands, including normal cleanup.
Cache and temporary-file maintenance can change duration without changed tests.
Preserve cleanup, retention and provider pacing policies during comparison.

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

## Keep proof effort proportionate

Before implementation or custom benchmarking, estimate absolute savings per run,
run frequency and how long the improvement is likely to remain useful.
Include faster feedback and concrete reuse opportunities, alongside investigation,
implementation, benchmark execution and ongoing maintenance effort.
A large percentage on an infrequent short job can have little practical value.
Set a bounded proof budget and a success or stopping criterion before spending more.

Start with existing timing and execution reports and the smallest credible
comparison of equivalent workloads. Match the claim to the evidence available.
Add instrumentation or samples only when missing evidence, variability or risk
could change the decision. Stronger claims need stronger evidence.
Do not copy a worked example's harness or sample count into every repository.

Reassess when proof costs grow or expected gains shrink.
If further effort outweighs the likely benefit, stop and report the limit.
If the improvement remains unproven, retain the proven path and say so.
Do not keep rerunning to obtain a favourable result.

Proportionality limits optional optimisation and benchmarking effort.
It never waives required tests, assertions, coverage, checks, independent reviews,
security controls or release gates. Change the scope or strength of a performance
claim rather than weakening verification to fit the budget.

## If changing the job graph

Remove a dependency only after checking artifacts, generated inputs, services,
credentials, shared state and required execution order.
Independent jobs can overlap; build and test consumers must retain their producers.
Overlap only work with isolated writable state, keeping shared preparation before its consumers.
Require every branch to pass before downstream work starts.
Check runner capacity and contention before adding workers or jobs.
Where the test framework supports isolated workers, compare worker counts within an existing runner.
This can reduce job duration without duplicating runner setup.
Preserve fixture groups, ordering requirements and duplicate test executions.
Account for extra setup, artifact transfers and work performed before another check fails.
Splitting jobs changes timeout and retry boundaries; verify that required work can still complete.

Preserve required check names, event filters, path scope, branch rules and matrix coverage.
Check the provider's actual semantics for failed, cancelled, timed-out and skipped prerequisites.
An intentionally skipped job and missing required evidence need different treatment.
The final gate must require every applicable result and block incomplete or failed verification.
Diagnostic overrides and metadata-only events must not create passing acceptance evidence.
Establish acceptance authority from trusted provider events, check identity and permissions.
A report flag alone cannot establish that authority.

Validate the affected event and result paths, including failures and cancellation.
For local process orchestration, exercise real child processes in relevant completion orders,
each failure direction and cancellation. An interrupted child can exit successfully;
the parent must still return failure for an interrupted verification attempt.
Use realistic workflow tests where useful, then verify the authorised remote path.
Successful YAML parsing or a green aggregate label alone cannot prove complete verification.

## If reducing preparation or build work

Run cheap integrity checks first when dependencies permit.
Prove required failures block downstream work, and retain failed reports.
If results persist, invalidate stale success before an attempt while retaining prior reports.
Faster failure feedback does not prove a faster passing run.

Prepare shared outputs once per invocation when consumers can safely reuse them.
Keep standalone commands self-contained and verify changed inputs rebuild before their consumers.
Preserve test typechecking, required verification builds and target-configured final builds.
Remove only work that contributes neither required evidence nor the published artifact.
Keep final build configuration and required privacy or authentication guards in their existing order.

## If selecting affected checks

Use one verification policy for local and remote entry points where applicable.
Keep provider event context and reporting in small adapters.

- Map complete owned suites and runtime consumers, including authentication hidden inside feature folders.
- Include non-imported inputs: fixtures, assets, generated files, templates and dynamic loading.
- Combine changed scopes as a union. Run shared checks once and include affected consumers and integration checks.
- Preserve justified universal checks. Backend changes can affect packaging, migrations or infrastructure tests.
- Use full required verification for shared foundations, dependencies, policy changes, unknown ownership or unproven impact.
- Preserve ownership across deletions and moves using both revisions. Collect staged, unstaged and untracked inputs separately, then union their impact. Opposing edits must not cancel out of selection.
- Fail visibly when an expected suite is absent. Propagate command failures, interruption and invalid exit results.

Expose selected scopes, reasons and fallback decisions. Retain an explicit full mode.
Bind the plan to its candidate, baseline and local inputs, including file content and symbolic links.
Recheck before execution and refuse drift. Derive tool provisioning from the same execution plan.
Unknown requirements retain safe prerequisites or full verification.
Keep selection policy tests inside the required verification path.
Test realistic counterexamples: combined scopes, shared callers, hidden authentication,
filesystem inputs, deletes, unknown paths, missing history, absent tests and command failure.
Each test must catch a named defect.

## If updating plugin content

A small skill or guide update can use complete checks for its plugin
when repository policy permits. Derive the scope from package ownership and
runtime consumers; a small diff or a Markdown filename alone is insufficient.
Validate skill format and each supported client manifest. Keep checks for public
content, package contents, installation and delivery, plus applicable platform checks.

Use the same conservative selection policy locally and in CI.
Executable changes, shared dependencies, verification policy changes, mixed
scope, unknown impact or unreliable comparison history retain full checks.
Validate a changed selection policy with full verification before relying on it.
Then confirm a representative authorised plugin update takes the targeted path.
One confirmed execution establishes routing. Typical speed or reliability claims
need further evidence.

Do not repeat unrelated application suites solely because a content update is
committed, promoted or released. Retain required check names, secret scans,
independent reviews and release gates. A small text diff never waives them.

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

Separate verification selection from artifact rollout.
Exclude inputs from rebuild fingerprints only when their runtime irrelevance is explicit and proven.
Keep unknown fields and runtime build inputs. Test invalidation with the actual builder.
Where artifacts are reused, compare runtime content, configuration and startup before deployment.
Read back the authorised deployment's artifact identity, runtime health and published assets where applicable.
A stable fingerprint alone does not prove a correct deployment.

Cache keys must account for relevant sources, dependencies, toolchains and environments.
Reusing downloaded dependencies differs from reusing a passing test result.
Reuse results only when tested inputs and the relevant environment remain equivalent.

## Validate and benchmark

Freeze each candidate during measurement. Keep setup environments outside scanned source directories.
Compare equivalent workloads and disclose changed conditions, including added regression tests.
Freeze application code, tests and verification inputs independently of the execution layout.
A separate harness can vary orchestration while keeping inspected CI definitions identical.
Record the harness revision and actual checkout; diagnostic runs must not satisfy release acceptance.
Compare test identifiers, resolved suite selections, skips and platform matrices, not counts alone.
Distinguish discovery inventories from observed execution results and retain reported skips.
Compare execution outcomes, duplicate identifiers and individual pass/skip identities when available.
Distinguish fixture skips from cases that started. Retain their reasons and account for suppressed cases.
Refuse unexplained missing cases or reports; an absent result is not a skip.
Neither inventories nor summary counts establish line or branch coverage.

Set a finite sampling and replacement rule before execution. Interleave comparable runs when practical.
Record every warm-up, failed attempt and rerun.
Decide sample eligibility from declared input checks before comparing timing totals.
Diagnose test failures before using an infrastructure replacement allowance.
Keep assertions when correcting fixtures, apply the correction to both arms and restart the cohort.
Start a new comparison cohort after correcting measured source or execution inputs.
Pin relevant runtime versions for the comparison when practical; moving selectors can resolve differently across runner images.
Resolve relevant implicit runtime inputs, including those changed by setup tools.
When they affect verification, pin them or compare effective content fingerprints.
Check actual toolchain and runner-image versions. Matching labels do not establish equal environments.
Record logical CPU counts and architecture for each runner role.
Disclose changed conditions or analyse separate cohorts. Keep instrumentation from warming only one candidate.
Define elapsed time through the last relevant completion; dependency waiting is not pure queue time.
For affected verification, compare a full control with representative selections on the same candidate and runner profile.
Include a scope-union check when selection applies. Full-only verification needs no artificial selection experiment.
Record added safety-test overhead, including shared checks on affected paths.

Check local execution and the actual authorised remote path.
Confirm reports identify the intended candidate, expected suites, skips and completed results.
A simulation proves its model; it does not prove provider execution or deployment.
Verify the integrated tree matches the passing candidate before claiming integration complete.

Report elapsed time and aggregate execution separately, with every sample, medians, ranges and cache limitations as applicable.
Separate the changed job's duration from setup and unrelated-job variation.
Do not attribute the whole aggregate difference to the change when other durations vary.
Explain tradeoffs: overlap can reduce waiting while adding setup and runner use.
Report joined elapsed time separately from each concurrent branch's duration.
Individual branches can take longer while the joined wait shrinks; their wall times do not measure CPU use.
Label one successful pair as observed evidence, not typical savings or reliability proof.
Use additional comparable samples when variability could change the decision; avoid rerunning solely for reassurance.
Do not weaken assertions, timeouts or failure reporting to obtain a better number.

Stop when required checks pass and evidence addresses the chosen bottleneck.
Report the change, before/after measures, preserved gates, limitations and integration state.
Keep the existing full-verification path; add recurring controls only when justified and authorised.

For measured examples and pitfalls, consult the Router's
[job-graph benchmark](references/worked-example.md) or
[runner-time benchmark](references/runner-time-benchmark.md) when relevant.
Their provider, commands and layouts are examples, not requirements for another repository.
