# Plan 042: Rewrite the documentation for staff and operators and retire the manual release artefacts

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. Do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 749a6b8d..HEAD -- <ROUTER_ROOT>`
> On any in-scope change, compare the "Current state" excerpts against the
> live code first; on a mismatch, STOP.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: Plans 035, 038, 039, 040, 041 (documents what they built); can be drafted in parallel and finalised last
- **Category**: docs
- **Planned at**: commit `749a6b8d`, 2026-09-07

## Path convention

Repository root post-Plan 034. Pre-034, the same files live under `domains/ai-platform/codex-model-router/`.

## Why this matters

The current README is a dense operator note written for one machine: it hardcodes `/opt/homebrew/bin/python3` and `/Users/cyrilallart/...`, says OpenRouter compaction is unavailable although the code now implements it with a summariser, calls the models "the six", and documents a release process based on a hash file (`compatibility-release.json`) and dated backup folders that Plan 041 makes obsolete. The KnowledgeVault note "Codex Mixed Model Picker" still names the deployed directory as the canonical source. Staff who install the product need a README that answers what it is, how to install, update, add a model, verify after a Codex upgrade, rotate a key and uninstall, in plain language.

## Current state

- `README.md` (33 lines). Line 3 names `Compatibility release 2`, `codex-cli 0.153.4`, `compatibility-release.json` and `before-compatibility-v2/`. Line 7 says "The six". Line 14 and 20 to 22 hardcode `/opt/homebrew/bin/python3 ... /Users/cyrilallart/.codex/mixed-model-router/...`. Line 31: "OpenRouter compaction remains unavailable."
- `compaction.py` and the router's `/responses/compact` branch implement compaction for OpenRouter models through a billable summariser call (`summarize_for_compact`, or `OpenRouterProvider.compact` after Plan 037).
- Deployed-only artefacts on the author's machine that will be obsolete after Plan 041: `compatibility-release.json`, `before-compatibility-v2/`, `before-slice2-20260907-155328/`, `before-slice2-deploy-20260907-212550/`, `config-before.toml`, `stdout.log`, `stderr.log`, `mixed-models.json` and `.bak` (moved to `retired/` by Plan 039).
- KnowledgeVault note: `~/KnowledgeVault/agent/Codex Mixed Model Picker.md`, front matter `source_paths` lists the deployed directory as `local-only` canonical source; body says compaction is blocked and the picker has six OpenRouter additions. Vault rules: edit in place, keep `last_verified` scoped, run `node ~/KnowledgeVault/tools/validate-vault.mjs` after changes, never store secrets or the configuration URL.
- `packaging/SOURCES.txt` says `Canonical source: domains/ai-platform/codex-model-router`.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Link and path check | `grep -nE "/Users/cyrilallart|/opt/homebrew" README.md docs/*.md` | no output |
| Vault validation | `node ~/KnowledgeVault/tools/validate-vault.mjs` | exit 0 |
| Tests (docs must not break them) | `python3.14 -m unittest discover -s tests -t .` | `OK` |

## Scope

**In scope**: `README.md`, new `CHANGELOG.md` (if Plan 041 did not create it), new `docs/operations.md`, new `docs/compatibility.md`, new `docs/adding-a-model.md`, `packaging/SOURCES.txt`, `docs/legacy-readme.md` (delete), the KnowledgeVault note named above (operator-approved edit), and an operator checklist for deleting the obsolete deployed artefacts.

**Out of scope**: any code; any file on machines other than the author's; Windows documentation beyond a "phase 2" note.

## Git workflow

- Branch `codex/router-docs-<yyyymmdd>`; commits `docs:`. Do not push unless instructed. The vault is not a git repository; edit it only with the operator's go-ahead and mention the change.

## Steps

### Step 1: README for staff

Rewrite `README.md` with these sections, in this order, each short and in plain English: What it does (one paragraph: a small program on your Mac that lets the Codex picker offer both your ChatGPT subscription models and approved OpenRouter models, keeping the two logins separate); Requirements (macOS, Codex desktop, Python 3.14 via Homebrew, an OpenRouter key); Install (the two commands from Plan 041, what the installer asks for, "restart Codex"); Updating (automatic daily at 10:00 when idle; manual `--check-update`); Choosing a model (start a fresh task when switching providers; reasoning levels differ per model); Costs (OpenAI models use the subscription; OpenRouter models bill the key; there is no local spend cap); Troubleshooting (where logs are, the health URL without the token, what a 400 or 409 from the router means, "restart at an idle moment"); Uninstall (`--uninstall`); Security (loopback only, per-install token, key file mode 600, nothing logged but metadata); Links to the docs below. Remove every machine-specific path.

**Verify**: `grep -nE "/Users/cyrilallart|/opt/homebrew|six|compaction remains unavailable" README.md` prints nothing.

### Step 2: Operations guide

`docs/operations.md` for Cyril and future maintainers: layout of `ROUTER_HOME` (`current`, `releases/`, `logs/`, `mixed-router-state.json`, `activation.json`, `openrouter.key`); release procedure (bump VERSION, CHANGELOG, tag, watch the Release workflow, test on `beta` channel first, promote); verification after a Codex upgrade (unit tests, then the two probe commands from the old README rewritten with `python3.14 tools/probe_codex_runtime.py <model> --installed ...`, and what a pass looks like: discovery, one exact callback, the marker in the final answer); key rotation (replace `openrouter.key`, no restart); incident steps (health, logs, `launchctl print`, rollback by re-running the installer with `--version <previous>`); and the decision log (request cap removed; catalogue live; compaction supported through a summariser call that is billable).

**Verify**: `test -s docs/operations.md`.

### Step 3: Compatibility matrix and adding a model

`docs/compatibility.md`: a table of Codex desktop versions tested (start with `0.153.4` on 2026-09-07) and a table of per-model quirks generated by hand from `codex_router/registry.py` (schema mode, max tools, excluded efforts, modalities). `docs/adding-a-model.md`: the exact sequence from Plan 038's README section, plus "run the probe once at low effort and record the result in compatibility.md".

**Verify**: every slug in `registry.py` appears in `docs/compatibility.md` (`for s in $(python3.14 -c "from codex_router.registry import MODELS;print(' '.join(m.slug for m in MODELS))"); do grep -q -- "$s" docs/compatibility.md || echo MISSING $s; done` prints nothing).

### Step 4: Retire manual release artefacts

- `packaging/SOURCES.txt`: replace with two lines naming the new repository as canonical and `ROUTER_HOME` as the deployed location.
- Delete `docs/legacy-readme.md`.
- Write the operator checklist into `docs/operations.md` under "One-time cleanup after 0.4.0": delete from `~/.codex/mixed-model-router/` the items listed in Current state (`compatibility-release.json`, the three `before-*` folders, `config-before.toml`, `stdout.log`, `stderr.log`, and `retired/` after one week), keeping `mixed-router-state.json`, `activation.json`, `openrouter.key`, `current`, `releases/`, `logs/`. This is an operator action on the author's machine, not something the executor runs.

**Verify**: `git grep -n "compatibility-release.json\|before-compatibility-v2" -- ':!plans' ':!docs/PROVENANCE.md'` prints nothing.

### Step 5: KnowledgeVault note (operator-approved)

With Cyril's go-ahead, edit `~/KnowledgeVault/agent/Codex Mixed Model Picker.md` in place: `source_paths` gains the new repository and names `ROUTER_HOME` as deployed state; `canonical_source` becomes the repository; the body replaces "six OpenRouter additions" with "the OpenRouter models listed in the repository registry", replaces "OpenRouter compaction is blocked" with "OpenRouter compaction runs through a billable summariser call", states that the catalogue is served live by the router (if Plan 039 landed), keeps the security lines about never printing the configuration URL or authentication storage, and updates `last_verified` only for what you verified. Run the vault validator.

**Verify**: `node ~/KnowledgeVault/tools/validate-vault.mjs` exits 0; `grep -c "six OpenRouter" "$HOME/KnowledgeVault/agent/Codex Mixed Model Picker.md"` prints `0`.

## Test plan

Documentation only; the suite must still pass (`OK`) because `tests/test_packaging.py` reads packaging files this plan edits.

## Done criteria

- [ ] README has the nine sections from Step 1 and no machine-specific paths.
- [ ] `docs/operations.md`, `docs/compatibility.md`, `docs/adding-a-model.md` exist and the compatibility table covers every registry slug.
- [ ] `docs/legacy-readme.md` deleted; `SOURCES.txt` updated.
- [ ] Vault note updated and validator exit 0 (or the report states the operator declined).
- [ ] Full suite `OK`.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- Plan 039 did not land: document the static catalogue and its weekly capture instead; do not describe a live catalogue that does not exist.
- The operator has not approved the vault edit: skip Step 5 and say so.

## Maintenance notes

- Each later release updates `CHANGELOG.md` and, after a Codex upgrade, `docs/compatibility.md`. Reviewers should refuse a release PR that bumps VERSION without a changelog line.
