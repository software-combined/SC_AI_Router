# Whole CI partition experiment

This experiment tests whether a different native test layout shortens a complete
continuous integration (CI) acceptance path. Every platform and required check remains.
No improvement is accepted yet. Production `check.yml` remains unchanged.

The first sequential comparison passed functional checks but failed environment
eligibility. Three unchanged Windows roles received different PowerShell versions
and certificate sets. That cohort is closed and its timing totals remain unopened.
The paired design below is a new prospective comparison, not a replacement sample.

## Frozen comparison

The shared baseline is development commit
`5e01f9f96a714045dc7fc36b24a58322e154155a`.
Both arms include the diagnostic fixture correction and the same safety tests.
One immutable source commit runs through `windows-ci-benchmark.yml`:

- Common: every unchanged job, including the Windows `core` suite, executes once.
- Control: the existing combined `native` standard-user job.
- Candidate: isolated `native-runtime` and `native-shortcuts` jobs, with a native aggregate.
- Each arm retains its own static checks and strict diagnostic acceptance gate.

Both complete paths consume the exact same common execution results. This removes
environment differences between unchanged roles without altering trust stores or
pretending that a rolling operating-system label pins an image build.

The runtime group retains lifecycle, access-control and task-recovery tests.
The shortcuts group retains shortcut-recovery tests. Their combined inventory
must match the original native suite, including order and duplicate occurrences.
Every native selection rejects skips. Each worker uses its own disposable runner
and standard account, with the existing identity, report and cleanup checks.

All macOS, Linux and Windows jobs remain. Common work forces complete offline
verification and installer scope. Static checks remain after each arm's prerequisites,
so the native layout is the only execution change between the paths.

## Safety and authority

Local contracts exercise the actual diagnostic gate against failed, cancelled,
unexpectedly skipped and missing prerequisites. Remote safety runs exercise
both native failure directions, control failure, shared failure and cancellation.
Retain the passing real Windows launch, timeout and cleanup evidence for unchanged
launcher code. Run the changed graph's safety checks before the timed comparison.

Diagnostic refs use the `cyril/windows-ci-bench-` prefix and emit
`Diagnostic acceptance (control)` and `Diagnostic acceptance (candidate)`, never
the required `Test` name. They have read-only
repository permissions and no publication or deployment steps.
Stable releases require a successful `check.yml` push to `main` at the exact
tagged commit. A diagnostic branch run cannot supply that evidence.

## Predeclared decision

Start with one paired workflow. Accept an observed improvement
only when every check passes with equivalent execution evidence, and:

- Joined acceptance-path elapsed time falls by at least 90 seconds and 20%.
- Aggregate allocated runner time rises by no more than 15%.
- The elapsed limits also pass a conservative control-queue sensitivity check.

Allow one further paired workflow only when the conservative first reduction is 15–25%, or a
native-worker dispatch difference of at least 30 seconds could change the decision.
With two workflows, both candidate paths must finish sooner. Paired median savings and
runner-time ratios must meet the same limits.

The limit is two paired workflows, with no replacement allowance.
Stop for correctness failures, missing evidence, incompatible environments or
a clear result below the threshold. Keep every attempt and do not relax the rule.

## Evidence

Record actual checkout commits and trees, Python versions, runner images,
architectures, CPU counts, certificate fingerprints and cache conditions.
For the three isolated native workers and the two static tails, compare exact
Python builds, operating-system releases, architectures, CPU counts, OpenSSL,
loaded certificate sets and applicable shell/compiler identities by job role.
Record Ubuntu's `pwsh` version because both static tails execute its parser.
Native workers use `windows-2025`; static tails use `ubuntu-26.04`.
These explicit operating-system labels still receive rolling image builds.
Capture Swift and pinned Rust versions, and the exact C# compiler binary hash.
Record installed distribution versions after lint setup, including dependencies.
Image identifiers alone may differ when these effective inputs match.
Cache misses remain eligible when dependencies and required work are unchanged.

Common roles need no between-arm environment exception: each result is the same
execution. Check input and workload eligibility before reading timing totals.

Retain observed Windows and offline case outcomes, identities, duplicate
multiplicities, skips and fixture skips. Retain every other platform's commands,
matrix identities, results and cleanup through job completion.

Each path starts at the workflow creation timestamp and ends when its static
acceptance job completes, including reports and cleanup. Its allocated work is
common job duration plus that arm's native, aggregate and static job durations.
Report these derived per-arm totals by runner class, and the actual experiment's
elapsed and aggregate totals separately. Shared work is counted once in the
actual experiment. These are not two independent production runs or billing measures.

For the queue sensitivity check, give the control native job an immediate start
after change scope. Give its static job an immediate start after common work and
the control native job finish. Use observed job durations, including setup and
cleanup; retain the candidate's actual finish. The same 90-second and 20-percent
limits must hold against this earlier derived control finish.

Record actual dispatch differences and cache conditions. Concurrent arms can
affect hosted-pool scheduling. This conservative check limits a claim based on
extra control waiting; it does not establish typical production queue behaviour.
Inspect the new critical path before choosing another change. One paired workflow
establishes an observation, not typical speed or improved reliability.

Only a positive comparison permits promotion of the production graph and a
new measured example in the CI optimisation skill.
