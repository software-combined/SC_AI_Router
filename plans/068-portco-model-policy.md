# Plan 068: Per-portco (later per-department) model allowlists as resolved data

> Planning only. Amends 046 (model-data distribution), 064 (projection
> ownership) and 055 (grant schema). No AWS resource creation, Entra change,
> OpenRouter write, staff-machine install, release or publication is
> authorised by this document. Each is a separate owner gate listed below.

> Drift check: `git diff --stat ca8ac8d..HEAD -- codex_router/catalogue.py codex_router/clients/__init__.py codex_router/providers.py codex_router/protocols/responses.py codex_router/protocols/messages.py codex_router/claude.py codex_router/runtime.py codex_router/registry.py codex_router/models.py plans/046-codex-router-model-onboarding-at-scale.md plans/055-central-key-federation-and-first-use-key-window.md plans/064-model-facts-and-client-projections.md plans/README.md`
> Compare the "Verified current state" excerpts against live code first; on a
> mismatch, STOP.

## Status and outcome

- Priority P2; effort S-M; risk LOW-MED (picker + routing gate on local data;
  no new identity, network or credential machinery).
- Planned 2026-09-10. Depends on 064 (projection owner), 046 (refresh
  mechanism, still gated), 055 (grant row), 054 Stage 4 (per-install delivery
  authority).
- Outcome: a portco sees only its approved subset of the global model list in
  the picker, and non-listed OpenRouter slugs are rejected at routing time.
  Group membership lives centrally; the router holds only the resolved result.
- First proof: two synthetic policies over one registry, one picker diff plus
  one routing rejection, with no Entra read and no group object on the machine.

## Decision: no groups in the router

The router is a per-machine loopback with no identity authority. It cannot
prove who the user is; it holds a key and a catalogue. Group truth stays
central: Plan 054 Stage A Entra parent plus per-portco subgroups, with the
Entra `mail` value as the verified work email (the Codex login email is a
provisioned shared account, so it is reconciliation only). The Plan 055 grant
row resolves membership to a slug allowlist. The machine stores and enforces
that list, never the groups behind it.

Portco ships first. Department is an optional later narrowing, always a subset
of its portco list, resolved centrally. Do not build department support until
a real request names the department and its subset.

## Verified current state (2026-09-10, read-only)

| Check | Observed |
|---|---|
| Registry superset | `codex_router/models.json` is the full approved list; `registry.py` loads and validates it, exposing `MODELS`, `by_slug`, `openrouter_slugs` |
| Picker filter | `catalogue.merge(catalog, roster=(), client='codex')` (`catalogue.py:159`) emits `models_for(MODELS, client)` OpenRouter entries; `clients/__init__.py` owns `visible_for`/`models_for`; routing never consults this filter |
| Routing ownership | `providers.select(model, path, openai_models=(), openai_mode='subscription')` (`providers.py:342`); `OpenRouterProvider.owns` (`:171`) keys on `by_slug(model).provider == 'openrouter'`; `responses.py:13-15` threads `state.get('openai_models', [])`, `messages.py:13-15` threads subscription modes |
| State shape | `runtime.REQUIRED_STATE = {'port': int, 'token': str, 'openai_models': list}` (`runtime.py:13`); unknown models fail closed with `Model is not in the configured catalog` |
| Grant row | 055 records verified email, key id (never the secret), issued-at, install token id, Codex account email for reconciliation only |
| Refresh gate | 046 hourly `models.json` refresh is deferred pending authenticated-update acceptance; last-good cache, atomic swap and strict validation rules stand |
| Delivery authority | Shared Stage A token must never authorise issuance; per-install credential arrives with 054 Stage 4; until then the interim operator path writes the machine directly |
| Data-only rule | 046 maintenance notes: data selects among behaviours the code already has; it never adds hosts, headers, credentials or paths |

## Design

### 1. Grant row gains the resolved subset (055, central side)

Add to the 055 DynamoDB grant row: `portco` (required string), `department`
(nullable string), `allowed_models` (list of registry slugs). Validation is
central: every slug must exist in the current `models.json`; a department list
must be a subset of its portco list; an empty list means no OpenRouter rows
(subscription rows unaffected). Store the resolved list, not the rule that
produced it, so the machine never evaluates membership. Audit rows record
`portco`, `department`, list version and issuer, never the key secret.

### 2. Machine artifact: one resolved file beside the key

`<home>/model-policy.json`, mode 0600, atomic write (temp file plus
`os.replace`), alongside `openrouter.key`:

```json
{"portco": "acme", "department": null, "allowed_models": ["z-ai/glm-5.3-flash", "moonshotai/kimi-k3"], "version": 3, "updated_at": "2026-09-10T00:00:00Z"}
```

Absent file on a never-provisioned install means all approved models
(backwards compatible; unmanaged fresh installs behave as today). A malformed
file keeps the last-good policy and logs a token-free `model_policy_rejected`
event; malformed with no prior good policy, or a policy file deleted after one
was cached, fails closed to an empty OpenRouter set (subscription rows
unaffected) with the same event, never to the full registry. Slugs in the policy that are absent
from the registry are ignored for the picker and logged by count only; they
never break the merge.

### 3. Picker: one optional argument (064 owner)

`merge(catalog, roster=(), client='codex', allowed=None)`: `None` preserves
today's behaviour exactly. A list intersects after the existing
`models_for(client)` and tier ordering: visible OpenRouter rows not in
`allowed` are dropped like hidden rows (and a pre-existing catalogue row for a
now-disallowed slug is dropped on merge, mirroring the hidden-row repair).
Subscription roster rows are unaffected. `check()` gains the same optional
argument so CI can pin a portco subset. The CLI flag is `--allowed sluga,slugb`
(optional, repeatable or comma-separated; absent means all). The flag is
tool/CI-only for merge and check; it never widens the stored file policy at
runtime, where the effective set comes from `model-policy.json` alone.

### 4. Routing: hiding must not be cosmetic (064 rule)

Presentation never determines upstream ownership, so the same allowlist must
gate routing. Thread it the way `openai_models` already travels: state carries
the resolved list (loaded from `model-policy.json` at startup, refreshed with
it), `protocols/responses.py` and `messages.py` pass it through, and
`OpenRouterProvider.owns` (plus the Claude OpenRouter path in `claude.py`)
returns False for a disallowed OpenRouter slug. The existing closed end stands:
`select()` raises `Model is not in the configured catalog`. Subscription and
native-service paths are untouched; an empty `allowed_models` still routes
subscription rows.

### 5. Refresh and delivery (046 mechanism, 054 Stage 4 authority)

Policy refresh rides the 046 hourly mechanism with identical validation,
atomic swap and last-good behaviour, but policy delivery is authenticated by
the per-install credential from 054 Stage 4, never the shared Stage A token.
Until Stage 4 exists, the interim operator path writes `model-policy.json`
directly through the shared writer (055 Stage 1 pattern). No policy fetch may
block router startup: boot with the bundled registry plus the cached policy,
then refresh.

### 6. What this plan does not do

No Entra reads from the router, no group/OU tables on the machine, no per-user
catalogue file per portco shipped in the release, no OpenRouter workspace
reliance for picker enforcement (workspaces are accounting partitions, not
hard isolation), no new quirk types, no tier or capability promotion, no change
to key provisioning or billing separation.

## Steps

### 0. Capture subset contracts first (tests, no source change)

New `tests/test_model_policy.py` with a synthetic registry and two policies:
picker subset diff through `merge(..., allowed=[...])`; routing rejection of a
disallowed OpenRouter slug through `select()` with the allowlist threaded;
subscription rows unaffected in both; absent policy on a never-provisioned
install equals today's output; malformed with no prior good policy, and a
deleted-after-cached policy file, both fail closed to an empty OpenRouter set;
malformed with a cached policy keeps last-good; policy slug absent from the
registry is ignored, not fatal; department subset invariant (department list
minus portco list is empty) asserted on synthetic grant rows. The
routing-rejection case must fail before the fix.

**Verify**: new tests fail on current source; existing
`test_catalogue`, `test_apply_catalogue`, `test_model_projections`,
`test_model_roster` stay green.

### 1. Grant schema and central resolution (055 owner)

Extend the 055 operator provisioning path (fake Management API first, per 055
stages): grant create/update accepts `portco`, optional `department` and
`allowed_models`, validates slugs against the current `models.json` and the
department-subset rule, writes the audit row, and returns the resolved list
for machine delivery. No router change in this step.

**Verify**: fake-API tests show an unknown slug refused, a department
superset refused, and the audit row carrying list version without the secret.

### 2. Machine loader (pure, stdlib only)

New small loader (lives with `runtime.py` or a `model_policy.py` leaf; 064
dependency direction applies: it imports stdlib only, never clients,
providers or command modules): read `<home>/model-policy.json`, validate
shape, return `(portco, department, allowed_tuple_or_None)`, fail closed to
last-good on malformed input with a token-free event. `load_state` does not
gain a required key; absence stays `None`.

**Verify**: unit tests for absent/malformed/valid/unknown-slug files; POSIX
0600 expectation asserted the way `credentials.py` asserts the key file.

### 3. Picker subset (064 owner, one writer on shared files)

Implement the `allowed` parameter in `merge()`/`check()` plus the
`--allowed` CLI pass-through, serialised with 062/064 work on the same files.
Keep ordering, preview labelling and retired-slug behaviour unchanged.

**Verify**: `tests/test_model_policy.py` picker cases pass; full catalogue
and projection suites green; `git diff --check` clean.

### 4. Routing gate (same writer, same branch)

Thread the resolved allowlist through both protocol policies into
`providers.select`/`claude.select` and gate `owns()` for OpenRouter slugs.
Confirm the closed error string is unchanged.

**Verify**: routing-rejection cases pass; subscription and native-service
tests unchanged; full suite `OK`.

### 5. Refresh/delivery wiring after its gates

Only after 046 hourly refresh acceptance and 054 Stage 4 per-install
authority: policy polling with validation/atomic/last-good, plus the interim
operator-write runbook entry until Stage 4. Late or offline machines keep
enforcing their cached policy.

**Verify**: malformed/offline feed preserves last-good enforcement; a rotated
policy reaches the picker without a restart (same proof shape as 046).

### 6. Runbook and docs

Portco onboarding/offboarding entry in `docs/operations.md` (add user to
subgroup, resolve list, deliver policy, revoke key by id on leave), plus the
`--allowed` line in `docs/adding-a-model.md`. No new docs page.

**Verify**: `grep -n "model-policy" docs/operations.md docs/adding-a-model.md`
shows both.

## Test plan

`tests/test_model_policy.py` per Step 0; extend fake-API provisioning tests
per Step 1. Pattern: `tests/test_apply_catalogue.py` for temp homes,
`tests/test_handler.py` for routing. Verification: full suite `OK`,
`compileall` clean, `check_source_limits.py` `failures=0`.

## Done criteria

- [ ] Two synthetic policies over one registry produce the expected picker diff
  and the expected routing rejection; subscription rows unaffected.
- [ ] Absent policy equals today's catalogue byte-for-byte on the fixture.
- [ ] Malformed/offline policy preserves last-good enforcement with a
  token-free event and no exception into the request path.
- [ ] Department support, if built, enforces the central subset rule; otherwise
  the plan records portco-only as delivered.
- [ ] Full suite `OK`; source limits `failures=0`; `plans/README.md` row updated.

## STOP conditions

- A step requires the router to read Entra or resolve membership: stop, that
  resolution belongs centrally per the Decision above.
- A step requires the shared Stage A token to authorise policy or key
  issuance: stop, per-install authority (054 Stage 4) is the gate.
- Anyone proposes per-portco catalogue files in the release bundle: stop,
  one registry plus resolved data is the design.
- The same failed check twice, or an ownership collision on shared files with
  062/064: stop and reconcile before continuing.

## Maintenance notes

- Adding a portco is data: resolve its subset centrally, deliver the policy,
  never a code change or release.
- Reviewers should refuse any change that lets policy influence hosts,
  headers, credentials or paths. Policy selects a subset of approved models;
  it never adds behaviour.
- Department narrowing stays a central subset operation; the machine never
  merges portco and department lists itself.
