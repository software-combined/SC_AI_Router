# Router verification pipeline

Main acceptance runs the full offline unit suite alongside native checks.
The required `Test` job waits for all of them before running static checks.
A failed or cancelled prerequisite fails that gate. Development keeps static
checks, with local verification still required before each commit.

The unit command and installer opt-in are unchanged. Native installer scope,
platform matrices, permissions, timeouts and tag publication rules are unchanged.
Title and body edits cannot create a successful required `Test` check.
No push to a branch publishes a router release; publication requires a tag.

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
