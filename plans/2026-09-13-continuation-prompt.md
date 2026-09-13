# Continuation prompt: take on the 2026-09-13 audit wave (161-167) alongside the 2026-09-12 backlog

Hand this file to the agent that is executing the 2026-09-12 architecture and
scalability backlog (`plans/2026-09-12-continuation-prompt.md`), or to an agent
with no other context. Everything either needs to start is below; the
2026-09-12 brief still governs the rules it states, and this brief only adds
to it.

---

## What changed

A four-lane audit (scalability, abstraction, cleanliness, security) ran on
2026-09-13. Its report is `plans/2026-09-13-router-four-lane-audit.md`. It
found the request path sound and moved seven items into new plans 161-167,
plus amendments to plans 152, 155, 131, 116 and 108 that are recorded in
`plans/README.md` under "Router four-lane audit wave (161-167)". Nothing in
the audit changes the rules you already work under.

Read, in this order, before you touch anything:

1. `AGENTS.md` (binding rules), `docs/architecture.md`, `plans/README.md`.
2. `plans/2026-09-12-continuation-prompt.md` in full: worktree and branch
   discipline, verification gates, owner gates, the report format.
3. `plans/2026-09-13-router-four-lane-audit.md`, at least "Vetted findings",
   "Considered and rejected" and "Defences that held", so you do not re-open
   a rejected item or weaken a defence while fixing something next to it.
4. The plan you are about to execute, in full, including its STOP conditions.

## Where you are

- Plans 161-167 pin their drift checks at `c068368` (`origin/develop` when
  they were written). Run each plan's drift check first and reconcile every
  cited line before editing.
- Baseline at `c068368`: `python3.14 -m unittest discover -s tests -t .` runs
  1331 tests in about 240 seconds and exits 0 with no network access;
  `python3.14 tools/check_source_limits.py` reports `checked=208 failures=0`;
  `python3.14 tools/check_policy_scans.py` passes. If your change reduces the
  test count, something was deleted and you need to explain it.
- `ai_router/compaction.py` (395), `ai_router/tool_adapter.py` (394) and
  `ai_router/catalogue.py` (393) are within six lines of the 400 hard cap.
  Plan 166 makes the baseline a ceiling so shrinking is free; it does not
  lift the cap. Plan 162 adds one line to `tool_adapter.py` and says what to
  do if that crosses 400.

## Merged execution order

Work top to bottom. The 2026-09-13 plans are small and mostly independent;
they slot in before the 2026-09-12 wave because 166 removes friction from
every later baseline edit and 161-163 are security hardening.

| Order | Plan | Gate | Note |
|---|---|---|---|
| 1 | 166 Source-limit baseline becomes a ceiling | local | First: every later plan re-syncs the baseline |
| 2 | 163 Listener robustness and token hygiene | local | Edits `ai_router/router.py`; before 164 |
| 3 | 161 Update chain: mandatory checksum, pinned redirects | local | Independent; before 167's deploy |
| 4 | 162 Bounded upstream reads | local | Edits `ai_router/relay.py`; before 164 |
| 5 | 164 Release request buffers before the relay | local | After 162 and 163 (shared files) |
| 6 | 165 Runtime leaves and the architecture map | local | Coordinate with 131 on `ai_router/runtime.py`; 152 and 155 cite `docs/architecture.md` |
| 7 | 167 Feed publisher role scope | source local, deploy owner-gated | Stop at the deploy step and report |
| 8 onward | 156, 152, 153, 154, 155, 160, 131, 135, 151, then 159, 157, 158 | as the 2026-09-12 brief says | Apply the amendments below when you reach 152, 155, 131 |

One writer per file at a time: 163 then 164 on `ai_router/router.py`; 162
then 164 on `ai_router/relay.py`; 165 and 131 on `ai_router/runtime.py`.

## Amendments to carry into existing plans

When you execute these plans, include the audit's additions; they are
recorded in `plans/README.md` and repeated here so they are not missed.

- **152**: also replace the `dialect == 'openrouter'` gate at
  `ai_router/relay.py:109-113` (added after 152 was written); strip
  `provider_defs.OPENAI.responses_path` in `ai_router/ingress.py:62,66`
  instead of the literal; make the popup copy (`ai_router/key_dialog.py:26`)
  and the `label='OpenRouter'` defaults (`ai_router/key_prompt.py:74,86`)
  read the provider label; delete `credentials.ENV_VAR`; in step 5 delete
  the two dead substring branches at `ai_router/errors.py:255-256` and type
  the `'api key'` `ValueError` raised at `ai_router/credentials.py:90`.
- **155**: pin `protocols/*._Policy.name` to the `provider_defs` protocol
  constants with a contract test; route the `/v1/models` GET through the
  dispatch table.
- **131**: route `packaging/notice.py:89-92`, `packaging/operator_surface.py:383`
  and `ai_router/apply_catalogue.py:27-37` through the shared atomic writer.
- **116**: acceptance includes a non-English Windows locale, or
  `ai_router/winacl.py:61-73` stops depending on the English `icacls`
  summary line.
- **108**: a second router on one machine exits with `EADDRINUSE` and is
  relaunched forever; add a clear, non-looping refusal.

## Owner decisions you must not make

- **F14 in the audit**: `packaging/feed_verify.py` is dead on the client.
  Wire it (publish and verify the signature, key ceremony) or delete it and
  correct the docs. Ask; do not choose.
- **Cutting a release.** `main` (0.6.32) lacks hardening that is on
  `develop`; the audit recommends a release after the AGENTS.md section 7
  probes. Owner-gated.
- Everything the 2026-09-12 brief lists: repository controls, billed probes,
  a real second provider, machine acceptance, the deploy step of 167.

## Things that will bite you (in addition to the 2026-09-12 list)

- `tools/check_policy_scans.py` greps Markdown too. Do not spell out the two
  retired request-cap identifiers or anything shaped like a bearer token in a
  plan, comment or changelog line; the scan fails the commit.
- Plan 161 changes how `urlopen` is called in `packaging/`; the installer
  surface must stay Python 3.9 compatible, and `tests/test_packaging.py`
  parses it with `feature_version=(3, 9)`.
- Plan 163's nested-body test must fail before the fix; run it once unfixed.
- Plan 165 moves `setup_pending` and `default_home`; keep the old names
  resolving (`setup.setup_pending`, `credentials.default_home`,
  `runtime.log_event`) because tests patch them.
- The audit report's line references are `develop` at `c068368`; they will
  drift as you land plans. Trust the plan's drift check, not the report.

## What to report back

Use the nine-point report format from `plans/2026-09-12-continuation-prompt.md`
for every plan, and add one line: which audit finding (F1-F13) the plan
closes, and whether the "Main" column in the report table changes once a
release is cut.
