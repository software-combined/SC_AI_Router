# Whole CI partition experiment

This experiment tests whether a different native test layout shortens complete
continuous integration (CI), while retaining every platform and required check.
No improvement is accepted yet. Production `check.yml` remains unchanged.

## Frozen comparison

The shared baseline is development commit
`5e01f9f96a714045dc7fc36b24a58322e154155a`.
Both arms include the diagnostic fixture correction and the same new safety tests.
Both run one immutable source commit through `windows-ci-benchmark.yml`:

- Control: existing `core` and combined `native` standard-user jobs.
- Candidate: `core`, `native-runtime` and `native-shortcuts`, with a native aggregate.

The runtime group retains lifecycle, access-control and task-recovery tests.
The shortcuts group retains shortcut-recovery tests. Their combined inventory
must match the original native suite, including order and duplicate occurrences.
Every native selection rejects skips. Each worker uses its own disposable runner
and standard account, with the existing identity, report and cleanup checks.

All macOS, Linux and Windows jobs remain. Both arms force complete offline
verification and installer scope. Static checks remain after the test branches
so the native layout is the only execution change.

## Safety and authority

Local contracts exercise the actual diagnostic gate against failed, cancelled,
unexpectedly skipped and missing prerequisites. Remote safety runs exercise
both native failure directions, cancellation, and real Windows launch/timeout cleanup.
Run those checks before the timed comparison.

Diagnostic refs use the `cyril/windows-ci-bench-` prefix and emit
`Diagnostic acceptance`, never the required `Test` name. They have read-only
repository permissions and no publication or deployment steps.
Stable releases require a successful `check.yml` push to `main` at the exact
tagged commit. A diagnostic branch run cannot supply that evidence.

## Predeclared decision

Start with one sequential control/candidate pair. Accept an observed improvement
only when every check passes with equivalent execution evidence, and:

- Complete elapsed time falls by at least 90 seconds and 20%.
- Aggregate allocated runner time rises by no more than 15%.

Allow one reversed second pair only when the first reduction is 15–25%, or an
unchanged branch or dispatch difference of at least 30 seconds could change the decision.
With two pairs, both candidates must finish sooner. Paired median savings and
runner-time ratios must meet the same limits.

The limit is four complete attempts, with no replacement allowance.
Stop for correctness failures, missing evidence, incompatible environments or
a clear result below the threshold. Keep every attempt and do not relax the rule.

## Evidence

Record actual checkout commits and trees, Python versions, runner images,
architectures, CPU counts, certificate fingerprints and cache conditions.
Compare exact Python builds, operating-system releases, architectures, OpenSSL,
loaded certificate sets and applicable shell/compiler identities by job role.
Capture Swift and pinned Rust versions, and the exact C# compiler binary hash.
Record installed distribution versions after lint setup, including dependencies.
Image identifiers alone may differ when these effective inputs match.
Cache misses remain eligible when dependencies and required work are unchanged.

Require matching CPU counts for potentially limiting Windows and Ubuntu roles.
An unchanged macOS role may receive three CPUs in one arm and five in the other.
Flag that difference before reading durations. It is eligible only if assigning
the larger observed duration to that role still leaves it off the critical path
in both arms. Add any apparent saving from the role to candidate aggregate time:
`adjusted = actual + max(0, control_role_time - candidate_role_time)`.
Sum this adjustment across allowed differences and apply the 15% limit to it.
Report actual and adjusted totals. Failed sensitivity checks do not permit replacements.

Retain observed Windows and offline case outcomes, identities, duplicate
multiplicities, skips and fixture skips. Retain every other platform's commands,
matrix identities, results and cleanup through job completion.

Elapsed time ends at the last relevant job, including reports and cleanup.
Report aggregate execution separately by runner class. Allocated job time is
not CPU consumption or a billing measure. Inspect the new critical path before
choosing another change. One pair establishes an observation, not typical speed
or improved reliability.

Only a positive comparison permits promotion of the production graph and a
new measured example in the CI optimisation skill.
