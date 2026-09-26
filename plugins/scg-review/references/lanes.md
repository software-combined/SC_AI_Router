# Review lanes

The pre-commit review runs three read-only lanes in parallel on the same staged tree. Each lane owns one class of failure and does not report the others' findings. The main agent sends every lane the same brief from the [pre-commit-review skill](../skills/pre-commit-review/SKILL.md) (step 7). Each lane reads this whole guide and applies its own section; the reportability, severity and report-format rules apply to every lane. The main agent uses the same reportability and severity rules when it adjudicates the findings.

Before inspecting anything, every lane reads the bundled [ponytail](../skills/ponytail/SKILL.md) skill in full and applies it within its own lane. A lane that cannot confirm it read ponytail is incomplete, the same as a lane that did not inspect the whole staged scope.

## Correctness lane

Owns functional defects, broken contracts, blocking verification failures, and missing tests for changed high-consequence behaviour. It does not report naming, cleanup, optional refactors or generic hardening.

Ask: can the staged behaviour fail for common, edge, empty, malformed, stale or concurrent inputs? Does it preserve public contracts, schemas, file formats, workflow contracts and API behaviour? Are errors handled in the repo's established pattern? Are security, auth, secret handling, permissions and untrusted-input boundaries preserved? Would the new or changed tests catch the likely regression?

When the simplification pass replaced or consolidated code, trace the affected callers and compare the old and new inputs, outputs, exceptions, side effects and meaningful execution order. A standard-library or native replacement must still satisfy the existing contract. Report concrete regressions, not the choice to simplify.

## Quality lane

Owns only change-introduced maintainability defects with a concrete near-term correctness or operability consequence. It omits style, naming preferences, cleanup, soft line-count thresholds, possible future abstractions and optional simplification.

Ask: is this the smallest correct change that matches local patterns? Does it add a parallel path where a canonical path exists? Is the code easier to read, test and maintain after the change? Are comments useful and sparse? Are tests structured like the existing tests rather than as one-offs?

Treat reuse opportunities as clues, not automatic findings. Report duplicate logic, a parallel path or a wrapper only when the staged evidence shows a concrete near-term consequence; name the canonical path and the harmful divergence. Fewer lines, or a single caller, never justify a finding or another simplification pass.

## Adversarial lane

Owns trust-boundary abuse, destructive side effects, replay, rollback, concurrency, deployment and fail-open risks. It must prove a concrete failure path; it does not report hypothetical hardening or repeat a correctness finding.

Ask: what hidden regression would pass a casual review? What missing test would let this bug return? What race, replay, idempotency, rollback, deployment, migration or observability failure could happen? What happens if dependencies, schemas, credentials, permissions, live state or external services drift? What breaks if the change is partly deployed, retried or reverted?

When the simplification pass removed or consolidated a guard or wrapper, trace the reachable failure or abuse path it controlled, and check the validation, authorisation, idempotency and data-loss or recovery protections on the remaining path. Report only a concrete lost protection or fail-open behaviour.

## What is reportable

A finding is reportable only when all of these hold:

- the staged change introduced it or made it materially worse;
- you can name an executable or deterministic failure path, with exact staged evidence;
- it is realistic, not speculative (theoretical edge cases without a reachable path, defence-in-depth-only observations and completeness for its own sake are omitted, even when technically arguable);
- its impact is at least `MEDIUM`;
- your confidence is at least `0.80`.

Each finding recommends the smallest in-scope remedy, including narrowing or reverting the staged change. A real blocker with no safe in-scope remedy is still reported, as `❌ Block` with a request for scope or owner direction; never suppress it.

A missing test is reportable only at `HIGH` or `CRITICAL`: the change alters high-consequence behaviour, the test would prevent a named failure, and no equivalent deterministic check already covers it. Residual risks are for concrete, unavoidable runtime or verification uncertainty only, never a parking place for rejected findings or cleanup ideas.

## Severity

- `CRITICAL`: likely data loss, secret exposure, a serious security flaw, a destructive production action, or the commit would obviously break core behaviour.
- `HIGH`: a likely regression, broken contract, missing required safety gate, security or data-integrity exposure, required-operability failure, meaningful untested high-consequence risk, or the commit would fail expected verification.
- `MEDIUM`: a proven, change-caused defect whose impact is bounded and reversible, and which breaks no contract, safety boundary, data integrity or required operability. It proceeds only with an explicit acceptance reason and never triggers an automatic edit.
- `LOW`: not reportable.

## Lane report format

Write the report for a person, not a parser, in Markdown:

1. First line: exactly one verdict with its emoji (`✅ All Clear`, `📝 Proceed With Notes` or `❌ Block`), then the lane name, for example `✅ All Clear (quality lane)`. Never use snake_case or paraphrase the verdict.
2. Second line: `Model: <the model that ran this lane> at <effort>`. Write `unverified` for any part you cannot confirm from your own runtime information.
3. Confirm that you read ponytail in full (give its path) and inspected the full staged diff and every staged file (give the `git write-tree` id). If you ran a targeted check, give the command and its result.
4. `Inspected files:` the staged paths and context paths you read.
5. `Findings`, `Missing tests` and `Residual risks`, each left out when empty. For each finding give the severity, staged `file:line`, a one-sentence claim, the failure path, the evidence, the impact, the confidence (0.80 to 1.00) and the smallest remedy. For each missing test give the severity, `file:line`, the named failure it prevents, why no existing check covers it, and the test to add.

Use `❌ Block` when any finding or missing test is `CRITICAL` or `HIGH`. Use `✅ All Clear` only when findings, missing tests and residual risks are all empty. Otherwise use `📝 Proceed With Notes`. Do not include JSON, and stop after the report.
