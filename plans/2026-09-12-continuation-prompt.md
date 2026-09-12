# Continuation prompt: execute the 2026-09-12 architecture and scalability backlog

Hand this file to an agent with no other context. Everything it needs to start
is below.

---

## What you are working on

SC Router (repository `software-combined/SC_OpenRouter_adapter`) is a local
loopback HTTP router written in Python 3.14 with the standard library only and
no third-party dependencies. It serves two clients from one endpoint:

- **Codex** (desktop and CLI) over the OpenAI Responses protocol at
  `/responses`, plus a few native service paths.
- **Claude Code** over the Anthropic Messages protocol at `/v1/messages` and
  `/v1/messages/count_tokens`.

It keeps ChatGPT subscription traffic on OpenAI and Claude subscription traffic
on Anthropic, using the client's own login, while routing approved OpenRouter
models on a separate key that the router holds. Both kinds of model appear side
by side in the client's model picker. The router binds `127.0.0.1` only, and
every request is authenticated by a per-install token carried in the URL path.
Subscription headers never accompany an externally billed request, and the
router key never accompanies a subscription request.

The repository is being published under Apache-2.0. Treat everything you write
as public.

## Where the rules are

Read these before you touch anything, in this order:

1. `AGENTS.md` - the binding rules: standard library only, source size limits,
   the security invariants, the popup style rule, the verification gates, the
   release rule and the model naming convention.
2. `docs/architecture.md` - domain ownership and the allowed dependency
   direction. New modules go where that map says.
3. `plans/README.md` - the live backlog, its conventions and the executor
   rules that apply to every plan.
4. `plans/2026-09-12-architecture-scalability-review.md` - the review that
   produced plans 152 to 160, with the evidence behind each one.
5. The plan you are about to execute, in full, including its STOP conditions.

Three rules from `AGENTS.md` catch people out, so they are repeated here:

- **Standard library only.** No runtime dependency may be added, ever. CI
  inputs (ruff, cfn-lint) are the only pinned third-party tools and they are
  not runtime.
- **No network in tests.** The suite must pass offline. Upstream calls go
  through the fake in `tests/fakes.py`.
- **Source limits.** Modules 250 soft / 400 hard, entrypoints and tools
  400/700, tests 300/500, checked by `python3.14 tools/check_source_limits.py`
  against `config/source-limits-baseline.json`. Crossing a soft cap means
  adding a baseline entry; crossing a hard cap means splitting the module, not
  raising the cap.

## Worktree and branch discipline

- One writable worktree per session. Never edit the primary checkout and never
  share a worktree with another agent.
- Base every branch on `develop`. Target every pull request at `develop`.
  Never work off `main` and never push to `main`. The only exception is a
  release pull request from `develop` to `main`, which you are not doing.
- Branch naming follows the existing convention, for example
  `codex/router-provider-dialects-20260913`.
- Never run `git reset --hard` or `git checkout --` without explicit approval.
- Commit subjects are `<type>: <short summary>` with type `feat`, `fix`,
  `refactor`, `test`, `chore` or `docs`.
- Run the shared `pre-commit-review` skill before every commit.

Each plan's drift check pins `0024a42`. `origin/develop` had already advanced
to `4b9cdf4` when the review was written, so expect at least one commit of
drift and reconcile the cited lines before editing. If a cited line has moved
or changed meaning, that is a STOP condition in most plans: read the plan's own
wording.

## Verification gates

Every plan must pass all of these before its commit:

```
python3.14 -m unittest discover -s tests -t .
python3.14 -m compileall -q ai_router tools tests packaging
python3.14 tools/check_source_limits.py
python3.14 tools/check_policy_scans.py
```

Most plans also require:

```
python3.14 -m ruff check --select F401,F811 ai_router packaging tools tests
python3.14 -m ai_router.models check --offline
python3.14 -m ai_router.catalogue --merge ./ci-catalogue.json
python3.14 -m ai_router.catalogue --check ./ci-catalogue.json
```

Baseline at `0024a42`: the suite runs 1217 tests in about 137 seconds and exits
0; `check_source_limits.py` reports `checked=192 failures=0`. If your change
reduces the test count, something was deleted and you need to explain it.

Each plan carries its own focused command list. Run the focused set while
iterating and the full set before committing.

## Recommended execution order

Plans are independent unless a dependency is named. Work top to bottom.

| Order | Plan | Gate | Note |
|---|---|---|---|
| 1 | 156 CI and test hardening | local | Independent, and it raises the safety net for everything after it |
| 2 | 152 Provider dialects and key shapes | local | Foundation for 153 |
| 3 | 153 Model identity and upstream ids | local | Rebase on 152; serialize with 154 on `ai_router/catalogue.py` |
| 4 | 154 Catalogue size budget | local | After 153; also contended with plans 135 and 151 on the same file |
| 5 | 155 Client contract | local | After 153 and 154; coordinates with plans 113, 120, 121, 148 |
| 6 | 160 Publication identifiers | local | Source-only; feeds plan 144 Step 3 |
| 7 | 159 Backlog consolidation | local | **Wait** for the public-readiness backlog pass to merge first |
| 8 | 157 Source reference hygiene | local | **After 159**, which settles two plan filenames |
| 9 | 158 Changelog and docs restructure | local | **Wait** for the public-readiness documentation pass to merge first |

Owner gates you will meet and must not attempt yourself:

- **Plan 142** (Apache-2.0 relicence) needs owner approval and prompt-file
  provenance before merge.
- **Plan 144** (public repository controls and the visibility flip) is entirely
  owner-applied. Never change repository visibility, branch protection, tag
  protection, environments or secret scanning.
- **Plan 099**'s hourly registry refresh becomes possible only once the
  repository is public, because its own STOP condition names the private
  repository as the blocker.
- **Any billed probe.** `tools/probe_*.py` and the `--probe` leg of
  `models add` spend real money. Never run one without an explicit instruction
  in the current session, and never in CI or in a test.
- **Any real second provider.** Plans 152 and 153 make one possible and prove
  it with a synthetic fixture. Adding a real upstream needs an owner decision
  and a key.
- **Machine acceptance** on macOS, Windows and Linux hosts, and anything that
  installs, updates, rolls back or restarts a live service.

Plans already open that overlap yours, so read their status rows before you
edit a shared file: 135 and 151 (`ai_router/catalogue.py`), 137 and 146
(`ai_router/ingress.py` and the baseline), 148 (the Claude contract), 147
(the operator surface), 131 (the state and writer contract).

## Things that will bite you

- `ai_router/catalogue.py` is 390 lines against a 400 hard cap. Almost any
  edit needs a leaf extraction. Plan 154 says where.
- `ai_router/provider_defs.py` must import nothing at all; two tests enforce
  that (`tests/test_provider_defs.py:136-141` and
  `tests/test_domain_boundaries.py:57-62`).
- No provider host, key environment variable or key file name may appear
  anywhere under `ai_router/` except `provider_defs.py`. A scan enforces it
  (`tests/test_provider_defs.py:107-133`).
- `packaging/` runs on Python 3.9, not 3.14, and must never import the
  `ai_router` package. It spec-loads what it needs through
  `packaging/service.py:40`.
- Tests must never open a network connection, spawn a real dialog, or write
  outside a temp directory.
- Never log or print a key, token, URL, request body or tool content.

## What to report back

For each plan you execute, report:

1. The plan number and the branch name.
2. The drift check result: what had moved since `0024a42`, and how you
   reconciled it.
3. The files you changed, with a one-line reason each.
4. The tests you added, by name, and what each proves.
5. The exact output of the verification gates: the test count and result, the
   compile result, the source-limits line, and any plan-specific command.
6. Every acceptance checklist item, ticked or not, with the reason for any that
   is not.
7. Any STOP condition you hit, with the evidence, and what you did instead of
   improvising.
8. Anything you found that is out of scope for your plan: file, line, what you
   saw, and which existing plan should own it. Do not fix it.
9. The updated status row you wrote into `plans/README.md`.

If you cannot finish a plan in one session, report what landed, what did not,
and write the remainder into the plan's status row as PARTIAL with the exact
remaining steps. Do not leave a half-finished change uncommitted and
unexplained.
