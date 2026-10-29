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

The split is a candidate until the bounded diagnostic comparison passes.
First use the separate safety workflow for Windows launch/cleanup contracts,
failure in each synthetic matrix entry, and cancellation of a waiting run.
These short probes do not execute the full acceptance workload.
The experiment uses identical source and tests for serial and split layouts,
retains all other acceptance jobs, and cannot produce the required `Test` check.
Run control, candidate, candidate, control, with at most four full runs.
Stop after the first pair if correctness fails or no useful improvement appears.
Accept only matching executed cases and outcomes, faster candidates in both pairs,
and at least 20% lower median workflow elapsed. Report aggregate runner time
separately; this experiment targets waiting time and makes no billing claim.

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
