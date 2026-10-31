# Whole CI partition experiment

This historical protocol compares two complete continuous integration (CI)
acceptance paths with shared common results. It did not establish an accepted
improvement. The later [independent source and layout comparison](ci-source-comparison.md)
owns the current result and production promotion decision.

Two earlier cohorts passed functional checks but failed their declared environment
eligibility. The sequential cohort differed on three unchanged Windows roles.
The first paired cohort differed on one native worker's PowerShell and certificates.
Those cohorts are closed; their timing totals remain unopened. This new protocol
uses a fixed shell and a conservative model, rather than replacement allocations.

## Frozen workload and execution

The application baseline is development commit
`5e01f9f96a714045dc7fc36b24a58322e154155a`.
One immutable instrumented source commit runs through `windows-ci-benchmark.yml`:

- Common: every unchanged job, including Windows core, executes once.
- Control: the original combined native selection on one disposable runner.
- Candidate: native runtime and shortcut selections on separate disposable runners.
- Each arm retains its own static checks and strict diagnostic acceptance gate.

Both complete paths consume the exact same common results. Shared failures or
missing results block both paths. Neither arm waits for the other arm's native
workers or static tail. All Linux, macOS, Windows, installer, scheduler, hook,
desktop and complete offline verification remains.

The runtime group retains lifecycle, access-control and task-recovery cases.
The shortcut group retains shortcut recovery. Their union must match the original
inventory, order, duplicate occurrences, outcomes and fixture skips. Native
selections require positive counts and zero skips. Each worker retains its
standard-account identity validation, process ownership and cleanup checks.

Native launchers explicitly execute the self-contained PowerShell 7.6.9 archive
from its official release. Verify its frozen SHA-256 before extraction or execution.
Record that executable's version. The image's shell only dispatches this command;
its overhead remains in each complete job. Isolated native helpers retain their
existing Windows PowerShell 5.1 environment. A separate 5.1 outer-launcher proof
failed before evidence creation and is retained; it is not a supported substitute.
Use `windows-2025` for native workers and `ubuntu-26.04` for static tails.
These operating-system labels still receive rolling image builds.

Preserve each original `Program` invocation and fixture order. Retain every
native case duration from Python 3.14's existing `collectedDurations`, including
setup, teardown and case cleanup. Require matching case labels, order and counts.
Imports, module/class fixtures, account work, reports and final cleanup remain
inside the residual full-job duration; none is removed from accounting.

## Safety and acceptance authority

Local contracts execute both strict diagnostic gates with failed, cancelled,
skipped and missing prerequisites. Remote probes retain shared failure, control
failure, both candidate failure directions and cancellation checks. Validate the
launcher with the verified PowerShell 7.6.9 executable, including actual
standard accounts, failed starts, timeout cleanup and plain UTF-8 reports.
Complete those checks before timing the new cohort.

Diagnostic refs use `cyril/windows-ci-bench-` and emit diagnostic acceptance names,
never the required `Test` name. They have read-only repository permissions and
cannot publish or deploy. Stable release acceptance still requires the unchanged
release workflow's successful exact-commit `check.yml` push to `main`.

## Prospective budget and input checks

Run one final paired workflow, with no replacement or further sampling allowance.
Retain every earlier attempt. Stop for failed verification, missing evidence,
incompatible required inputs, or failure of either performance criterion below.

Before opening timing totals, verify actual checkout commits and trees, complete
job coverage, native case outcomes and duration-record identities. Separately
executed native workers must match Python, OS release, architecture, CPU count,
OpenSSL, C# compiler hash and both executed PowerShell versions. Both static
tails must also match actual PowerShell, installed dependencies and certificate
fingerprints. Retain toolchain and environment records for every common job.

Keep native certificate fingerprints and image builds visible. The selected
native cases perform local process, ACL, task, shortcut, registry and GUI work.
Their source has no explicit TLS path, but implicit operating-system certificate
processing is not excluded. Do not claim certificate equivalence or disable its
checks. The model below instead penalises all favourable native timing variation
within the observed ranges. It does not bound unobserved variation.

## Actual measures and conservative model

Elapsed time starts at workflow creation and ends at each arm's final static job
completion, including reports and cleanup. Per-arm allocation is common work plus
that arm's complete native, aggregate and static job durations. Report runner
classes separately. Report actual experiment elapsed and allocation separately,
counting shared work once. Derived path totals are not independent production
runs, CPU consumption or billing measures.

Let `C_R` and `C_S` be control runtime and shortcut case-duration sums. Let `P_R`
and `P_S` be their candidate sums. Each native job's overhead `O` is its complete
allocated duration minus its case-duration sum. Let `T_C` and `T_P` be complete
static-tail job durations. Use seconds from workflow creation:

```text
R_min = min(C_R, P_R)       R_max = max(C_R, P_R)
S_min = min(C_S, P_S)       S_max = max(C_S, P_S)
O_min = min(O_C, O_R, O_S)  O_max = max(O_C, O_R, O_S)
T_min = min(T_C, T_P)       T_max = max(T_C, T_P)

control_reference =
    max(common_end, changes_end + R_min + S_min + O_min) + T_min

native_penalty = max(R_max + O_max - (P_R + O_R),
                     S_max + O_max - (P_S + O_S))
candidate_reference = actual_candidate_finish + native_penalty + T_max - T_P

control_allocation_reference = common_work + R_min + S_min + O_min + T_min
candidate_allocation_reference =
    common_work + R_max + S_max + 2*O_max + candidate_aggregate_work + T_max
```

The reference gives the control the fastest observed components and overhead,
with immediate dispatch after its dependencies. It gives the candidate the
slowest observed components and overhead, retains its actual queues, and adds
its full penalty even if common work masks some native delay. Static variation
also favours the control. Record cache conditions and concurrent-arm contention.

Accept only when actual endpoints and modelled references both show at least
90 seconds and 20% less waiting, and both allocation comparisons rise by no more
than 15%. This supports an observed paired-path result with sensitivity analysis.
It establishes neither exact native environment equivalence nor typical production
savings or reliability. Inspect the new critical path before another optimisation.

Only a positive result permits production graph promotion and a measured skill
example. The failed fixture-performance comparison remains failed and separate.
