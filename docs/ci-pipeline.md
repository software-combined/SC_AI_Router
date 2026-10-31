# Router verification pipeline

Main acceptance runs the full offline unit suite alongside native checks.
The required `Test` job waits for all of them before running static checks.
A failed or cancelled prerequisite fails that gate. Development keeps static
checks, with local verification still required before each commit.

The unit command and installer opt-in are unchanged. Native installer scope,
platform matrices, permissions, timeouts and tag publication rules are unchanged.
Title and body edits cannot create a successful required `Test` check.
No push to a branch publishes a router release; publication requires a tag.

## Windows standard-user acceptance

Core and native Windows suites use separate disposable runners and accounts.
This avoids adding their durations while keeping profile and process state isolated.
Both matrix entries reach the required `Test` gate. One failure does not cancel
the other entry; failed and cancelled results cannot satisfy acceptance.

`tools/run_windows_standard.ps1 -Python <interpreter> -Suite core` runs core
discovery. `-Suite native` runs the existing four native contract modules.
Omitting `-Suite` retains core followed by native. Every selected suite must
report positive test counts and success; native contracts permit no skips.
The launcher retains its standard-user identity checks and account cleanup.
Its default child timeout remains 20 minutes; tests can request a shorter timeout.

The split passed the bounded diagnostic comparison: two samples per layout
recorded 31.5% lower median complete-pipeline time and 6.7% more aggregate job
execution. Both paired candidates were faster, with matching Windows execution.
The [Windows comparison record](windows-ci-benchmark.md) retains every sample
and the acceptance decision for that historical four-run cohort.

Further native layout work follows the
[whole-CI experiment](ci-partition-experiment.md), which defines the current
shared-work comparison, launcher safety probes, input checks and conservative
timing model. Diagnostic runs cannot produce the required `Test` check.

## Why overlap these jobs

The [baseline main acceptance run](https://github.com/software-combined/SC_AI_Router/actions/runs/39897410359)
checked revision `4ada64b6c27946d0df80f52e35fa577628bd105a`.
It took 14m 18s on 23 October 2026. The offline suite took 8m 04s, after
waiting 5m 50s from workflow creation for native checks and runner startup.
These jobs consume no shared generated output, so they can run together.

This change adds one Ubuntu job setup. It targets elapsed waiting time;
it does not claim lower aggregate runner use or faster individual tests.

## Verification

`tests/test_ci_pipeline.py` checks that the full suite has no native dependency,
runs once with installer coverage enabled, and reaches the required gate.
`tests/test_workflows.py` retains main/development, text-edit and release guards.

Use the actual main pull-request or push workflow to measure the result.
Compare completed runs with equivalent source, coverage and runner classes.
Record queue time, individual steps, aggregate runner time and failures separately.
Historical timing alone does not prove a controlled improvement.
