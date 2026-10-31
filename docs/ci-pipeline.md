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

Windows acceptance uses four selections: `core-first`, `core-second`,
`native-runtime` and `native-shortcuts`. Each has a separate disposable runner
and standard account, keeping profile and process state isolated.
All four matrix entries reach the required `Test` gate. One failure does not
cancel the others; failed and cancelled results cannot satisfy acceptance.

`tools/run_windows_standard.ps1 -Python <interpreter> -Suite core-first` runs
the first core partition; `core-second` runs the rest. Partitions preserve
module fixtures, discovery order and duplicate occurrences. `native-runtime`
runs the lifecycle, access-control and task-cohort modules; `native-shortcuts`
runs shortcut recovery. `-Suite core` and `-Suite native` retain complete selections.
Omitting `-Suite` retains core followed by native. Every selected suite must
report positive test counts and success; native contracts permit no skips.
The launcher retains its standard-user identity checks and account cleanup.
Its default child timeout remains 20 minutes; tests can request a shorter timeout.

The earlier core/native split passed its bounded diagnostic comparison: two samples per layout
recorded 31.5% lower median complete-pipeline time and 6.7% more aggregate job
execution. Both paired candidates were faster, with matching Windows execution.
The [Windows comparison record](windows-ci-benchmark.md) retains every sample
and the acceptance decision for that historical four-run cohort.

The current four-selection layout follows the
[complete source and layout comparison](ci-source-comparison.md). That trial
ran two independent complete paths with no shared results. One eligible pair
recorded 40.45% lower complete elapsed time and 1.43% more allocated runner time.
Its conservative model recorded 39.00% lower elapsed time and 8.38% more allocation.
Those results cover the shortcut fix and partitioning together; they do not
establish separate component savings, typical speed or production acceptance.

The earlier [shared-work experiment](ci-partition-experiment.md) retains its
own protocol and rejected attempts. Diagnostic runs cannot produce the required
`Test` check. The production matrix needs no diagnostic native aggregate:
the existing matrix dependency makes `Test` wait for all four selections.
Final-candidate production acceptance remains a separate gate.

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
