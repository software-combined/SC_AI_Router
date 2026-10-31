# Complete CI source comparison

This trial measures the Windows shortcut absence fix through the complete
continuous integration (CI) pipeline. Both paths keep the supported combined
native suite. A further job split is unnecessary unless measurements support it.
The earlier failed partition cohorts remain failed; their totals stay unopened.

## Sources and required work

The before source is `b815fe5262168f536f06f627714112a5bfbe6ab0`, tree
`132aa998f6b407c2ea6246cad6ce93dd766628f3`. The after source is the reviewed
commit that starts `ci-source-benchmark.yml`. Freeze both trees and the complete
diff before dispatch. Permitted changes are the absence fix, regression tests,
two bounded native fixture calls, diagnostic reporting, related documentation
and the required version entry. Keep production `check.yml` unchanged.

The caller invokes the same reusable diagnostic definition twice. Each call
checks out its requested source and runs all 17 production-shaped allocations:
scope, three installers, Windows core and native, full offline verification,
five desktop targets, both scheduler targets, both hook targets and final
acceptance with every static check. No results are shared between paths.
The three experimental split definitions are intentionally disabled. Every
applicable allocation must succeed; unexpected skips and missing reports fail.

Both paths retain suite order, real native assertions, standard accounts,
cleanup, installer opt-in, two offline workers and existing job timeouts.
Unittest invocations without reports use the existing single-worker observer
with the exact original arguments. Compare each invocation separately, including
duplicate cases, outcomes, subtest callbacks and fixture suppression.
Retain complete reports, failed reports and cache-state logs.

The after source adds six shortcut regressions and four harness contracts.
The original 17 native cases remain an ordered subset of its 23 native cases.
Preserve all original outcomes; declare additions by exact test ID before dispatch.
Count the added work in every duration and allocation where it executes.

## Inputs and acceptance authority

Both calls use Python 3.14.9, with 3.9.25 for its installer surface, and the
existing action, dependency and Rust pins. Every Windows verification role
uses the hash-verified PowerShell 7.6.9 archive. A post-selection assertion
checks the executing step host's path, version and binary hash. Native helpers
retain Windows PowerShell 5.1. Record actual source commits and trees, operating
system, architecture, CPU count, compilers, dependencies, shells and certificates.

Before opening timing totals, require matching effective inputs for paired
roles. The changed native role must also match its image and certificates.
Static tails must match final dependencies and certificates. Other image or
certificate differences remain visible and enter the conservative whole-job
model below; no exact environment-equivalence claim follows from that model.
Unchanged macOS roles may use the recorded three- or five-CPU runner profiles.
Disclose that difference and retain the whole-job minimum/maximum penalties.

The trigger is `cyril/ci-source-bench-*`, outside the legacy experiment prefix.
Both calls have read-only permissions and diagnostic acceptance names.
They cannot emit the required `Test` check or authorise publication.
The [reusable-workflow rules](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows)
bind the local called definition to the caller's commit; checkout readback
separately establishes the deliberately different application sources.

## Complete endpoints and conservative calculation

Observed elapsed starts at parent workflow creation and ends at each path's
final static-job completion. Allocation sums every complete job in that path,
including setup, reports and cleanup. Report runner classes separately.
Allocation is neither CPU time nor a bill. Count both paths once in experiment
totals; they are concurrent observations, not typical production measurements.

For unchanged roles, give before the minimum observed complete job duration,
and after the maximum. In the combined native role, separate unchanged runtime
cases `R`, original shortcut cases `S`, new cases `E` and residual job work `O`.
Compute runtime minima and maxima for each matched original occurrence:

```text
b[native] = sum(R_min) + S_before + min(O_before, O_after)
a[native] = sum(R_max) + S_after + E_after + max(O_before, O_after)
```

Residual work includes imports, fixtures, account work, reports and cleanup.
Require complete case-duration records, with finite nonnegative values and
residuals. Keep each source's changed shortcut durations; treating their
intended difference as noise would erase the optimisation under test.

Expand matrices into the actual dependency graph. Let `P[j]` be each role's
parents, `s[j]` and `e[j]` its timestamps, and `t0` workflow creation:

```text
q_after[j] = s_after[j] - max(t0, e_after[p] for p in P[j])
F_before[j] = max(0, F_before[p] for p in P[j]) + b[j]
F_after[j] = max(0, F_after[p] for p in P[j]) + q_after[j] + a[j]
```

Before receives immediate dispatch. After retains its actual dependency queues.
Sum modelled durations for allocation. Assert before estimates never exceed
observed before values and after estimates never fall below observed after.
Accept only when actual and modelled endpoints both save at least 90 seconds
and 20%, while both allocation increases remain at most 15%.

## Budget and correction

Allocate one paired workflow, with one replacement permitted only for input
drift found before totals are opened and only when both paths otherwise pass.
Keep identical sources and orchestration for that replacement. Retain every
attempt. A functional failure or disappointing timing is not a replacement.
If a required check fails, diagnose and fix it; corrected source starts a new
cohort. This stops the invalid comparison, not the authorised correctness work.

One successful pair supports an observed result and sensitivity analysis.
It does not prove typical savings, reliability or unobserved variation.
Only a positive result permits a measured skill example. Integration and
required production acceptance must cover the final combined candidate.
