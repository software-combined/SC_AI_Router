# Complete CI source and layout comparison

This trial measures the shortcut absence fix and Windows job partitioning
through the complete continuous integration (CI) pipeline. Production `check.yml`
stays unchanged until this comparison passes the thresholds below.

The previous [source-only pair](https://github.com/software-combined/SC_AI_Router/actions/runs/41184590089)
passed all 34 allocations and its declared input and execution checks.
Its after source was `905bd5d60bc22e48ec5dbd2d59af7fd52cc0dade`.
It improved elapsed time, but missed both the 90-second and 20% thresholds:

| Measure | Before | After | Reduction |
| --- | ---: | ---: | ---: |
| Observed complete elapsed | 556 s | 475 s | 81 s (14.57%) |
| Conservative elapsed | 542.88 s | 480.12 s | 62.76 s (11.56%) |
| Observed allocated runner time | 2,411 s | 2,409 s | 2 s (0.08%) |

The after core and native jobs took 438 and 435 seconds. Both held up acceptance;
the macOS installer took 348 seconds. These measurements motivate partitioning
both Windows roles. They do not prove the new layout is faster.
Keep that valid below-threshold result. All earlier failed cohorts remain
failed, with their totals unopened.

The [first partitioned pair](https://github.com/software-combined/SC_AI_Router/actions/runs/41190256996)
passed all 37 allocations and workload checks. It failed eligibility because
the candidate native-runtime image and loaded certificates differed from control.
Its [permitted replacement](https://github.com/software-combined/SC_AI_Router/actions/runs/41191265012)
failed environment capture in `After / Desktop menu (darwin/x86_64)`.
After cold Python setup, the Swift version command exceeded its 15-second limit;
the compile step did not run. Both runs' comparison totals remain unopened.
The instrumentation correction below starts a new source/controller cohort.

## Sources and required work

The before source is `b815fe5262168f536f06f627714112a5bfbe6ab0`, tree
`132aa998f6b407c2ea6246cad6ce93dd766628f3`. The after source is the reviewed
commit that starts `ci-source-benchmark.yml`. Freeze both trees, the harness
and the complete diff before dispatch. The new delta adds bounded macOS
preparation, its workflow contract and a separate cohort trigger.
It retains the core selections, diagnostic layout routing and reviewed shortcut
fix. This CI-only delta does not change the Router version.

The caller invokes the same reusable diagnostic definition twice:

| Path | Layout | Windows core | Windows native | Allocations |
| --- | --- | --- | --- | ---: |
| Before | `combined` | `core` | `native` | 17 |
| After | `partitioned` | `core-first`, `core-second` | `native-runtime`, `native-shortcuts` | 20 |

Both paths independently run scope, three installers, full offline verification,
five desktop targets, both scheduler targets, both hook targets and final
acceptance with every static check. After also requires the native aggregate.
Only the selected path's final gate and native jobs apply to each call.
Every applicable allocation must succeed. Failed, cancelled, skipped, missing
or unexpected prerequisites fail the gate. No results are shared between calls.
The legacy `windows-ci-bench-*` experiment keeps its original default layout.

Both paths retain suite order, real native assertions, standard accounts,
cleanup, installer opt-in, two offline workers and existing job timeouts.
Each Windows partition has a separate runner and disposable standard account.
Core partitions reuse the existing unittest module boundary split. They retain
full discovery in both reports and record each partition's selected occurrences.
Require equal full inventories and ordered `first.selected + second.selected`
equal to full discovery, including duplicates. Each selected occurrence must
execute or have an exact declared fixture skip. Native groups permit no skips.
Unittest invocations without reports use the existing single-worker observer
with the exact original arguments. Compare each invocation separately, including
duplicate cases, outcomes, subtest callbacks and fixture suppression.
Retain complete reports, failed reports and cache-state logs.

Shortcut creation emits fixed phase markers before each native operation.
A timeout reports only the last recognised marker, or `script-entry-unobserved`.
Markers distinguish script entry, object creation, property assignments and saving.
Fixture construction has a 60-second limit; the original source had no limit.
Production shortcut operations retain their 30-second limits.
The markers do not establish an underlying timeout cause.

The source fix added six shortcut regressions, two shortcut diagnostic contracts
and four harness contracts. The original 17 native cases remain an ordered
subset of its 23 native cases. Declare all additional test IDs from both source
trees before dispatch, including the new core and layout contracts.
Preserve original invocation arguments, ordered cases, outcomes, callback counts,
skip reasons and fixture suppression. New test loops use new methods so existing
test callback multiplicity stays unchanged. Count all added work where it executes.

## Inputs and acceptance authority

Both calls use Python 3.14.9, with 3.9.25 for its installer surface, and the
existing action, dependency and Rust pins. Every Windows verification role
uses the hash-verified PowerShell 7.6.9 archive. A post-selection assertion
checks the executing step host's path, version and binary hash. Native helpers
retain Windows PowerShell 5.1. Record actual source commits and trees, operating
system, architecture, CPU count, compilers, dependencies, shells and certificates.

Both source paths prepare Swift before recording the environment in every macOS
role: the installer and both desktop targets. One shared step runs
`xcrun swiftc --version` once, requires a successful exit and allows 60 seconds.
The metadata observer keeps its 15-second limit. Build, test and account limits
stay unchanged. Complete job and setup durations include this preparation in
both paths. No Windows preparation or separate warm-up run is added.

Before opening timing totals, require matching effective inputs for paired roles.
The control core and both candidate core jobs must match their actual image,
certificates, CPU count, architecture, Python, shells and dependencies.
Apply the same requirement to control native and both candidate native jobs.
Static tails must match final dependencies and certificates. Other common-role
image or certificate differences remain visible and enter the conservative
whole-job model below; that model does not prove equal environments.
Unchanged macOS roles may use the recorded three- or five-CPU runner profiles.
Disclose that difference and retain the whole-job minimum/maximum penalties.

The new trigger is `cyril/ci-finish-ready-bench-*`, separate from prior cohort prefixes.
Both calls have read-only permissions and diagnostic acceptance names.
They cannot emit the required `Test` check or authorise publication.
Targeted `windows-ci-safety-shortcut-only-*-proof` refs run the isolated
shortcut diagnostic. They reuse unchanged passing launcher contracts; normal
proof refs and both complete source paths retain those contracts.
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
and after the maximum. Keep each changed core job's own complete actual duration.
For native work, separate original runtime cases `R`, original shortcut cases `S`,
new cases `E` and residual job work `O`. Compute runtime minima and maxima
for each matched original occurrence across control and candidate runtime:

```text
b[native] = sum(R_min) + S_before + min(O_before, O_runtime, O_shortcuts)
a[native-runtime] = sum(R_max) + E_runtime + max(O_before, O_runtime)
a[native-shortcuts] = S_after + E_shortcuts + max(O_before, O_shortcuts)
```

Residual work includes setup, imports, fixtures, account work, reports and cleanup.
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

Before receives immediate dispatch. After retains its actual dependency queues,
including the native aggregate's execution and waiting. Sum complete modelled
durations for allocation, with runner classes separate. Assert before estimates
never exceed observed before values and after estimates never fall below after.
Accept only when actual and modelled endpoints both save at least 90 seconds
and 20%, while both allocation increases remain at most 15%.

## Budget and correction

For this new cohort, allocate one paired workflow, with one replacement only for input
drift found before totals are opened and only when both paths otherwise pass.
Keep identical sources and orchestration for that replacement. Retain every
attempt. Do not add Windows warm-ups. A functional failure or disappointing
timing is not a replacement.
If a required check fails, diagnose and fix it; corrected source starts a new
cohort. This stops the invalid comparison, not the authorised correctness work.

One successful pair supports one observed bundled source/layout result and
measured sensitivity. It cannot isolate core-partition causality or prove typical
savings, reliability or unobserved variation. Only a positive result permits
production matrix promotion and a measured skill example. Integration and
required production acceptance must cover the final combined candidate.
