# Plan 154: Catalogue size budget - a roster that can grow

> **Executor instructions**: Follow this plan step by step. If a STOP condition
> occurs, stop and report. When done, update this plan's status row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 0024a42..HEAD -- ai_router/catalogue.py ai_router/openrouter_base_instructions.txt ai_router/model_prompt.py tests/test_catalogue.py tests/test_subagent_instructions.py tests/test_packaging.py tests/test_model_projections.py docs/runtime-files.md docs/adding-a-model.md config/source-limits-baseline.json`
> `ai_router/catalogue.py` is contended: plans 135, 151 and 153 all edit it.
> Land 153 first, then this plan, and re-sync the baseline entry each time.
> Reconcile every cited line before editing.

## Status and first proof

- Priority P1; effort M; risk MED; confidence HIGH; category direction/scalability.
- Depends on plan 153 (same file). Serialize with plans 135 and 151.
  Supersedes nothing; plan 151 stages 3 to 5 stay open and untouched.
- Source: `plans/2026-09-12-architecture-scalability-review.md`, rows
  "The merged Codex catalogue is 629,869 bytes for 27 rows", "The roster line
  inside the instructions grows with visible rows", and "Subscription rows are
  served the routed-model instructions".
- First proof: a merge of a synthetic 200-row registry completes under a
  recorded byte budget and a recorded wall-clock budget, the budget is asserted
  by a test, and no ChatGPT subscription row is told it is running an
  OpenRouter model.

## Why this matters

`subscription_stub` (`ai_router/catalogue.py:133-145`) and `external_entry`
(`:181-201`) both embed the fully rendered instructions text into every
catalogue row, and `instructions_for` (`:152-161`) renders every visible slug
into that text. Measured at `0024a42`: the 19 external rows alone produce
443,606 bytes, and with the eight-row subscription roster the merged file is
629,869 bytes for 27 rows, of which 89.7% is the same 20,936-byte blob
repeated. Because the blob itself grows with the roster, the file grows with
the square of the row count: 100 rows projects to about 2.3 MB and 200 rows to
about 5.1 MB, parsed by Codex at every start.

There is a second, plainer problem in the same code. The instruction text
begins "You are Codex, a coding agent running the selected OpenRouter model"
(`ai_router/openrouter_base_instructions.txt:1`), and `subscription_stub`
serves it to the eight ChatGPT subscription rows. A `gpt-6-astra` session is
therefore told it is running an OpenRouter model. That predates plan 151 and is
not a regression from it, but it is wrong and it is the first thing a public
reader will notice.

`ai_router/model_refresh.py:35-36` already caps a refreshed registry at 200
models, so 200 is the ceiling this plan must make safe.

## Scope

**In scope**: the files named in the drift check, plus new tests.
**Out of scope**: removing the per-row `instructions_template` (it is how a
routed session learns the delegation roster, and plan 151 has live incident
evidence for it), plan 151's remaining stages, plan 099's hourly refresh
wiring, and any change to which models are visible.

## Steps

1. **Rename the instruction file and fix its first line.** Move
   `ai_router/openrouter_base_instructions.txt` to
   `ai_router/routed_base_instructions.txt` and update the read at
   `ai_router/catalogue.py:148`. Change the first line to name no provider, for
   example "You are Codex, a coding agent running the selected model." Update
   the deploy inventory in `tests/test_packaging.py` and the file list in
   `docs/runtime-files.md`. `packaging/release.py:53` globs `ai_router/*.txt`,
   so the bundle follows the rename with no further edit; confirm that in the
   release test rather than assuming it.

2. **Give subscription rows their own short preamble.** Add a second, small
   text asset `ai_router/subscription_base_instructions.txt` carrying the
   subscription-appropriate wording plus the same delegation rule paragraph
   that plan 151 added (`routed_base_instructions.txt` lines 8-16). Have
   `subscription_stub` render from that asset instead of the routed one. The
   rendered roster line stays identical between the two, because it is the same
   picker projection.

3. **Bound the roster line.** `instructions_for` currently joins every visible
   slug. Add a module constant `MAX_ROSTER_IDS = 40` and, above that count,
   render the first `MAX_ROSTER_IDS` ids in picker order followed by one
   sentence saying the full list is available from the router's own model
   listing. This is the term that makes growth quadratic; capping it makes the
   per-row blob constant above 40 rows. Keep the existing
   `SUBAGENT_MODEL_PLACEHOLDER` guard in `check` (`:336-339`) working.

4. **Record the budget as a test.** Add `tests/test_catalogue_scale.py`:
   build a synthetic registry of 200 valid rows through `registry.load`, swap
   it in with `model_refresh.apply` and restore it in `addCleanup` exactly as
   `tests/test_provider_swap.py:46-68` does, then assert that
   `catalogue.merge({'models': []}, roster=SUBSCRIPTION_SLUGS)` produces a
   document under a stated byte budget and that the merge completes under a
   stated wall-clock budget on the test host. Choose the byte budget from the
   measured post-change size plus 25% headroom, and write the measured number
   into the test as a comment so a future change that doubles it is visible in
   the diff.

5. **Report the size where an operator can see it.** `ai_router/catalogue.py`
   `merge_file` (`:310-318`) writes the file; have it return the merged
   document as it does today and have the `--merge` CLI branch (`:384-385`)
   print `rows=<n> bytes=<n>` on one line. `packaging/install.py` already
   prints install progress, so nothing there changes. No new state, no new
   file.

6. **Keep `check` honest.** `catalogue.check` (`:328-360`) compares each
   visible row against a freshly built entry. Add one assertion to
   `tests/test_catalogue.py` that a catalogue merged with a capped roster still
   passes `check`, so the cap cannot cause a permanent "differs in
   model_messages" report.

7. **Re-sync the source-limits baseline.** `ai_router/catalogue.py` is 390
   lines against a 400 hard cap, so this plan has almost no headroom. If the
   edits push it over, move `instructions_for`, the two asset reads and the
   roster cap into a new `ai_router/model_instructions.py` leaf that imports
   `registry` and `provider_defs` only, and record it in
   `tests/test_packaging.py`, `docs/runtime-files.md` and
   `docs/architecture.md`.

## Verification

| Purpose | Command | Expected |
|---|---|---|
| Focused | `python3.14 -B -m unittest tests.test_catalogue tests.test_catalogue_scale tests.test_subagent_instructions tests.test_catalogue_upgrade tests.test_packaging tests.test_release` | pass |
| Catalogue round trip | `python3.14 -m ai_router.catalogue --merge ./ci-catalogue.json && python3.14 -m ai_router.catalogue --check ./ci-catalogue.json` | merge prints `rows=` and `bytes=`; check prints `identical: 19 entries`, exit 0 |
| Full suite | `python3.14 -m unittest discover -s tests -t .` | exit 0 |
| Compile | `python3.14 -m compileall -q ai_router tools tests packaging` | exit 0 |
| Policy scans | `python3.14 tools/check_policy_scans.py` | exit 0 |
| Limits | `python3.14 tools/check_source_limits.py` | `failures=0`, `ai_router/catalogue.py` under 400 |

## STOP conditions

- The roster cap would drop an id a routed session needs for delegation: stop
  and report. Plan 151's incident is the reason the roster exists at all, and a
  cap that breaks it is worse than a large file.
- Capping the roster makes `catalogue --check` report a permanent difference:
  stop; `merge` and `check` must keep sharing one derivation
  (`_visible_rows`, `ai_router/catalogue.py:204-220`).
- `ai_router/catalogue.py` cannot stay under 400 lines even after the leaf
  extraction: stop and report the count rather than raising the cap.
- The 200-row merge exceeds the byte budget even after the cap: stop and report
  the measured size. The next lever is the shared base text itself, which is an
  owner decision about instruction content.

## Acceptance checklist

- [ ] No instruction asset or catalogue row names a specific provider in its
      opening sentence.
- [ ] Subscription rows render subscription wording; routed rows render routed
      wording; both carry the same delegation rule.
- [ ] The rendered roster is capped and the per-row blob is constant above the
      cap.
- [ ] `tests/test_catalogue_scale.py` asserts a recorded byte and time budget
      for a 200-row registry and restores the real registry on cleanup.
- [ ] `catalogue --merge` prints the row count and byte size.
- [ ] `catalogue --check` still reports `identical` for the real registry.
- [ ] Full suite, compile and limits pass; `plans/README.md` row updated.

## Maintenance notes

- Record the measured post-change size for 19, 27 and 200 rows in the plan
  status row so the next reviewer can compare without re-deriving it.
- A live Codex start against a 200-row catalogue is the only proof the client
  tolerates the size. That leg is owner-gated and belongs in the acceptance
  list plan 159 creates, not here.
