# Router acceptance example

SC AI Router overlapped independent acceptance jobs in
[PR 488](https://github.com/software-combined/SC_AI_Router/pull/488).
The full offline suite previously waited for all native checks before starting.
It now starts alongside them. The required `Test` gate still waits for every
result before running static checks.

## Equivalent workload

The [before run](https://github.com/software-combined/SC_AI_Router/actions/runs/39897410359)
checked `4ada64b6c27946d0df80f52e35fa577628bd105a`.
The [after run](https://github.com/software-combined/SC_AI_Router/actions/runs/39900288385)
checked `6d309210e2bc3a041cb0bb5f8b3a7b2f02f19aac`.
Both completed on 23 October 2026, on their first attempt.

Application code, installer code, tools, dependencies, the unit command and
installer opt-in stayed unchanged. Only the workflow, workflow tests and
documentation changed. Two new tests protect overlap and gate coverage.

Both full suites used CPython 3.14.8 on `ubuntu-latest`, with serial unittest
execution and `SCG_RUN_INSTALLER_TESTS=1`. Native runner labels stayed unchanged.
The command remained `python -m unittest discover -s tests -t .`.

## Observed results

Each column is one successful sample.

| Measure | Before | After |
| --- | ---: | ---: |
| Total workflow elapsed | 14m 18s | 9m 27s |
| Aggregate job execution | 24m 10s | 25m 06s |
| Offline suite step | 8m 04s | 8m 35s |
| Discovered tests | 3562 | 3564 |
| Existing skips | 21 | 21 |
| Successful jobs | 14 | 15 |

Elapsed time fell 33.9%, including queues, setup and cleanup.
Aggregate job execution rose 3.9%; it excludes queues and does not weight
different runner classes. No cache configuration changed. Caches and host load
were not controlled, so these samples do not establish typical latency,
compute savings or improved reliability. Individual tests did not get faster.

## Retained evidence and boundaries

The required `Test` gate still fails on a failed or cancelled prerequisite.
Native scope, platform matrices, development checks, text-edit safeguards,
permissions, timeouts and publication rules stayed intact. The extra Ubuntu
setup is the deliberate tradeoff for overlap. No test selection policy was added.

The after run's tree, `4e360d977e9e85f1e7f0f6dae552da97bd7c0427`, matched the
reviewed and integrated development tree. Full remote acceptance passed all
configured jobs. No router tag or release publication was performed.

A new documentation page initially failed the bundle's index check.
After adding its link, affected documentation and bundle checks passed;
unchanged local results were reused. The final remote full suite passed too.

The portable lesson is to measure the critical path before narrowing coverage.
Independent jobs can overlap while a final required gate preserves their checks.
Another repository must derive its own dependencies, commands and acceptance rules.
