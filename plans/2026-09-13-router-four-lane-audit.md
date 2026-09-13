# Router four-lane audit: scalability, abstraction, cleanliness, security (2026-09-13)

> Read-only advisory. No source was changed by the audit. Remediation is
> planned in 161-167 (new) and as amendments to 131, 152, 155, 108 and 116
> (existing). Plans grant no implementation authority.

## Question

How does the router stand up on scalability, abstraction, cleanliness and
security, and what should change first?

## Provenance and method

- Audited revision: `main` at `c1ec415` (released 0.6.32), read in full by the
  main agent (every module under `ai_router/`, the update chain under
  `packaging/`, the workflows and `infra/feed.yaml`). Every finding was then
  re-verified against `origin/develop` at `c068368` (0.6.42), which is 58
  commits and about 14,000 changed lines ahead of `main`. Line references
  below are `develop` unless marked `main`.
- Four parallel read-only lanes (security, scalability, abstraction,
  cleanliness) ran with the `improve` audit playbook. Requested models:
  Claude Opus for the first three, Claude Sonnet for cleanliness; served
  identity unverified. Every lane claim that reached this report was re-read
  by the main agent; three lane claims were rejected after verification and
  are listed under "Considered and rejected".
- Verification runs (no source change): `python3.14 -m unittest discover -s
  tests -t .` under a socket guard that refuses every non-loopback connect
  and DNS lookup: `main` 1053 tests, exit 0, no guard hit; `develop` 1331
  tests, exit 0, no guard hit. `compileall`, `tools/check_source_limits.py`
  (208 files, 0 failures), ruff F401/F811 and `tools/check_policy_scans.py`
  pass on `develop`.
- Repository controls read through the GitHub API on 2026-09-13: the
  repository is private; rulesets "Protect main", "Protect develop" and
  "Protect tags and releases" are active; tag creation, update and deletion
  are blocked for everyone but the Admin role; `main` requires a pull request
  and the `Test` status check with zero required approvals.
- One reproduction was run locally: a 1,242-byte body nesting 600 arrays
  parses in `json.loads` and then raises `RecursionError` in
  `image_items.count_images`.
- Prior audits reconciled: `2026-09-09-domain-architecture-audit.md`,
  `2026-09-10-router-optimisation-audit.md`,
  `2026-09-11-router-external-security-audit.md`,
  `2026-09-12-architecture-scalability-review.md`,
  `2026-09-12-external-router-review.md`. Nothing they planned is re-reported
  as new; where a landed plan's stated outcome is not true in current code,
  the row says so.

## Verdict

**Security.** The request path holds. Credential separation is real in code,
the token compare is constant-time and byte-safe, bodies are bounded,
`Cookie` is dropped, logs carry codes not content, and on `develop` the Host
guard, token-strength check, in-flight cap, 415 guard and path redaction have
all landed. The risk has moved to the self-update chain, which the 2026-09-11
audit scoped out: the bundle checksum is skipped when the feed document omits
the field, origin pinning is checked before the first response only, and the
credentialed key check follows redirects with its bearer header. None of
these widens the trust root (the feed origin already is the root), but they
are fail-open shapes on the one path that executes code on every staff
machine, and each is a small fix.

**Scalability.** Adequate for the stated load, with measured evidence rather
than assumption: per-request normalisation is single-digit milliseconds even
on a 4 MiB body with 100 tool schemas, and the router contributes well under
one percent of turn latency. The first real ceiling is memory, not CPU: the
raw body, the parsed graph and the wire copy stay pinned for the whole relay
(about three times the body size per in-flight turn). The second is the
stdlib listen backlog of five, which nobody chose. Roster and catalogue
growth are already owned by plans 099, 153 and 154.

**Abstraction.** About right for a 7,700-line stdlib router, with one layer
built and one half-built. The provider table earns its keep: a second
external provider is one table entry plus registry rows plus the dialect
gates plan 152 already owns. The weak spot is one misplaced function:
`runtime.py` is both the logging leaf and the boot composition root, which
creates the package's only import cycle and makes "pure policy" modules
transitively import the key-window machinery. The architecture map places
`transport` and `upstream` on the wrong side and omits `runtime`.

**Cleanliness.** Genuinely well kept where it counts: small modules, an
offline suite of 1,331 tests with real assertions, a shared harness, a
boundary test that proves its own detector works. The one systemic cost is
the source-limit gate: it pins exact line counts for files above the soft
cap, so the baseline file was edited in 73 of the last 200 commits and the
three largest modules now sit within six lines of the hard cap.

## The main versus develop gap

Released 0.6.32 (`main`) lacks hardening that has landed on `develop`. Fleet
machines run `main` until a tag is cut.

| Landed on develop, not released | Plan | Effect on the fleet today |
|---|---|---|
| Host header validation on loopback ingress | 137 | DNS-rebinding GETs still reach the handler |
| Token strength check at boot, 32-request cap, 415 guard, path redaction, OpenCode credential path confinement, ACL verdict TTL | 146 | An empty or short token still authorises `//health`; unbounded concurrent turns |
| Operator surface: `--doctor`, `--support`, read-only `--check-update`, `--update` | 147 | None on the router; operators lack the diagnostics |
| Context-limit stream refusals mapped to Codex's recognised code | 0.6.42 | Codex does not recover from streamed context-limit errors |
| Shared state reader and atomic writer, feed verifier moved, CI runs the suite on pull requests | 131, 134 | Repository-only |

Recommendation: cut the release once the AGENTS.md section 7 compatibility
probes pass. This is owner-gated and outside the plans below.

## Vetted findings

Ordered by leverage (impact over effort, discounted by confidence and fix
risk). "Main" says whether the released code has the same defect.

| # | Finding | Dimension | Impact | Effort | Risk | Confidence | Evidence (develop) | Main | Owner |
|---|---|---|---|---|---|---|---|---|---|
| F1 | Bundle checksum is optional and origin pinning stops at the first response; the credentialed key check follows redirects with its bearer header | Security | The fleet's code-execution path has a fail-open shape: a feed document without `sha256` installs an unverified tarball, the `MANIFEST.json` is read from the unverified archive, and a 3xx from any pinned host moves the fetch (and, for the key check, the OpenRouter key) to whatever host the redirect names | S | LOW | HIGH on mechanism; MED on exploitability (the feed origin is already the trust root) | `packaging/updater.py:304-308`; `packaging/install.py:322-327`; `packaging/service.py:96-107`; `packaging/feed.py:29-33`, `:67-72`; `ai_router/key_store.py:40-43` | Yes | New plan 161 |
| F2 | Upstream response reads are unbounded on the adapted SSE paths and on every whole-body read | Security, scalability | `sse.blocks` iterates `for line in response`, so one line with no newline is buffered whole before the 16 MiB frame cap can fire; the bounded `sse.lines()` exists but only `stream_errors.normalize` uses it. Six whole-body reads have no ceiling. A hostile or compromised upstream can grow the router without bound, once per in-flight turn | M | LOW-MED | HIGH | `ai_router/sse.py:7-18`, `:21-39`; `ai_router/tool_adapter.py:384`; `ai_router/agent_handoffs.py:297`, `:304`; `ai_router/relay.py:39`, `:50`; `ai_router/upstream.py:29`; `ai_router/providers.py:169`, `:235` | Yes | New plan 162 |
| F3 | Listener robustness: deep nesting escapes the handler's error mapping; the setup nonce is still compared as `str`; the drain flag is read outside the lock; the listen backlog is the stdlib default of 5; the setup URL (token plus nonce) is passed to the popup child in `argv` | Security, scalability | A 1.2 KB body nesting 600 arrays drops the connection with a traceback in the supervisor log (reproduced); a non-ASCII nonce during a live setup window does the same; a request admitted microseconds before a drain can be killed by `os._exit`; more than five simultaneous sub-agent connects stall for a SYN retransmit; on a shared machine another local user can read the path token from `ps` while the key window is open | S | LOW | HIGH (reproduced or read); MED for the backlog stall | `ai_router/router.py:103-104`, `:122-134`, `:191-192`, `:20-23`; `ai_router/setup.py:50`; `packaging/install.py:271-283`; `ai_router/key_prompt.py:155-172` | Yes | New plan 163 |
| F4 | Request body, parsed graph and wire copy stay pinned for the entire relay; an unconditional image walk runs on every POST for one Grok timeout hint; the 120 s upstream timeout is a bare literal in six places | Scalability | About three times the body size resident per in-flight turn for the whole stream (lane-measured: a 15 MiB body peaks near 47 MiB and holds about 32 MiB); eight parallel turns at the ceiling is roughly 375 MiB of dead data; the walk adds an unguarded recursion on the success path | S | LOW | HIGH on mechanism; MED on the measured figures | `ai_router/router.py:140-143`, `:212`; `ai_router/providers.py:160`; `ai_router/transport.py:27`; `ai_router/relay.py:30`, `:74`, `:143`; `ai_router/router.py:71`, `:138` | Yes | New plan 164 |
| F5 | `runtime.py` is both the logging leaf and the boot composition root: the package's only import cycle, four lazy imports that exist to hold it open, and modules that declare themselves pure but transitively import the key-window machinery; the architecture map omits `runtime` and places `transport`/`upstream` under `protocols` although `providers` and `claude` import `transport`; `default_home` is implemented twice | Abstraction | Every module that wants one log line inherits registry, credentials, setup and key_prompt (subprocess, webbrowser) or writes a function-local import; the boundary test's hand-written denylist permits exactly the edges the map forbids; a new module gets no enforcement | M | LOW | HIGH | `ai_router/runtime.py:9-11`, `:20`, `:104-106`; `ai_router/setup.py:206`; `ai_router/model_policy.py:30`; `ai_router/tool_aliases.py:209`; `ai_router/credentials.py:123`, `:127`; `ai_router/upstream.py:18`; `docs/architecture.md:9-30`; `tests/test_domain_boundaries.py:57-77`; `ai_router/credentials.py:20-22` versus `ai_router/discovered.py:22-23` | Yes | New plan 165 |
| F6 | The source-limit gate pins exact line counts for baselined files, so shrinking a file fails the gate until the baseline is re-synced | Cleanliness | The baseline was edited in 73 of the last 200 commits (the most-changed file in the repository); `compaction.py` 395, `tool_adapter.py` 394 and `catalogue.py` 393 sit within six lines of the 400 hard cap; the `router.py` entry (204) is inert below the soft cap; the gate rewards splitting over editing | S | LOW | HIGH | `tools/check_source_limits.py:23`; `config/source-limits-baseline.json` (44 entries, 11 under `ai_router/`) | Yes | New plan 166; reconcile with plan 156 step 4 |
| F7 | The feed publisher role can overwrite any object in the bucket; bundle immutability is enforced only by a `head-object` check inside the publishing script; no Object Lock | Security | The trust root for first install and every update can be rewritten by whoever holds the role; versioning makes it recoverable, not preventable. Compensating controls verified 2026-09-13: tag creation is Admin-only by ruleset, and `release.yml` runs only for two named actors and re-checks the tag SHA | M | MED | HIGH on the template; MED on residual exposure | `infra/feed.yaml:41-42`, `:140-160`; `tools/publish_feed.py:91-103`; `.github/workflows/release.yml:25-27`, `:75-78` | Yes | New plan 167 (owner-gated) |
| F8 | Provider residue after plan 141: four dialect gates in the relay (one added on 2026-09-13 after plan 152 was written), the refusal cache keyed on one provider id, `/backend-api/codex` stripped as a literal in ingress, popup copy and label defaults that name OpenRouter, and an unused `credentials.ENV_VAR` | Abstraction | A hypothetical second provider routes and bills correctly but loses the context-window frame, the key window on 401, the refusal cache and the stream-error normalisation, and its users read "Paste the OpenRouter key" | S | LOW-MED | HIGH | `ai_router/relay.py:20-21`, `:37`, `:55`, `:59`, `:109-113`; `ai_router/ingress.py:62`, `:66`; `ai_router/key_dialog.py:26`; `ai_router/key_prompt.py:74`, `:86`; `ai_router/credentials.py:13` | Yes | Plan 152 owns the gates and prose; amend it with `relay.py:109-113`, the ingress prefix, the popup copy and `ENV_VAR` |
| F9 | `errors.py` still classifies two exceptions by substring, and plan 126's record says the branches are gone | Cleanliness | Two of the three string branches are unreachable (the typed catches run first); the third is live but stringly typed through a `ValueError` raised for a non-API OpenCode credential; three messages are duplicated between exception classes and factory functions | S | LOW | HIGH | `ai_router/errors.py:252-258`, `:62-84` versus `:141-153`; `ai_router/credentials.py:89-90`; `ai_router/providers.py:143` (caught at `ai_router/router.py:177`) | Yes | Amend plan 152 step 5 (it already edits `errors.py`) |
| F10 | Protocol policy objects own almost nothing; `policy.name` equals `provider_defs.RESPONSES` by convention only; the `/v1/models` GET bypasses the dispatch table | Abstraction | Renaming a policy silently disables the terminal-failure and context-error frames with no test failure; a third protocol lands with silent feature loss | S (pin the constant and add a contract test) | LOW | HIGH | `ai_router/protocols/responses.py:11`; `ai_router/protocols/messages.py:11`; `ai_router/router.py:202`; `ai_router/transport.py:122`; `ai_router/relay.py:56`, `:61`, `:110`; `ai_router/ingress.py:118-119` | Yes | Amend plan 155 (it already touches `protocols/__init__.py`) |
| F11 | Three writers still bypass the shared atomic writer landed by plan 131 | Cleanliness | The restart notice is written through a deterministic temp with no cleanup and no mode; the support bundle is written with `O_TRUNC`; the catalogue apply path keeps its own temp-and-backup recipe | S | LOW | HIGH | `packaging/notice.py:89-92`; `packaging/operator_surface.py:383`; `ai_router/apply_catalogue.py:27-37` | notice: yes; others: develop only | Amend plan 131 (remaining scope) |
| F12 | Windows ACL parsing depends on the English `icacls` summary line | Security (fails closed), portability | On a non-English Windows the localised summary line is parsed as an account, the check raises, the key is unreadable and every routed request fails; the failure direction is safe, the outage is not | S | LOW | MED (logic read; not executed on a localised host) | `ai_router/winacl.py:61-73` | Yes | Fold into plan 116 acceptance |
| F13 | The port is frozen at first install; a second router on the same machine crash-loops under `KeepAlive` | Scalability | Two users who install at different times both get 18749; the second service exits with `EADDRINUSE` and is relaunched forever with no user-visible message | S | LOW-MED | MED | `packaging/service.py:496-510` (`ensure_state`); `ai_router/router.py:34-35`; `ai_router/__main__.py:15` | Yes | Fold into plan 108 (a clear refusal, not an automatic rebind) |
| F14 | The feed signature path is dead on the client | Security, cleanliness | `packaging/feed_verify.py` ships hand-rolled Ed25519 whose `checked_feed`/`verify_hex` have no non-test caller; `FEED_PUBLIC_KEY` is empty; `release.py --sign` writes a `.sig` that nothing publishes or verifies; the module docstring says the installer verifies feeds | Decision, S either way | LOW | HIGH | `packaging/feed_verify.py:127-147`; `packaging/feed.py:63`; `packaging/release.py:86-87`, `:148` | Yes | Owner decision: wire it (publish and verify the signature, key ceremony) or delete it and correct the docs. Neither is planned here |

Residual after plans 161 and 162 (F2): `ai_router/key_store.py:44`
(`json.load(response)`) still reads a whole response with no ceiling; plan 161
owns that file but changes only its opener.

### Direction: one option, not a defect

Plans 152 to 155 already carry the architecture direction. One further option
worth the owner's attention: the router's only outbound HTTP through
`http.client` (the relay and the summariser) ignores proxy environment
variables, while every `urllib` call (key check, catalogue refresh, feed
fetch) honours them. On a proxy-only corporate network the router can
validate a key but not relay a turn. This is consistent behaviour to decide
on, not a bug: either document "no proxy support" or route both through one
opener policy.

## Findings already owned elsewhere (not re-reported)

- Dialect string compares, OpenRouter-shaped failure parsing and key-info
  body, `.gitignore` for one key file, "use an OpenRouter model" prose: plan
  152 (from the 2026-09-12 review). F8 and F9 above are amendments to it.
- Client visibility split between `clients.visible_for` and
  `claude.models_listing`, the client enum in four places: plan 155.
- Catalogue growth with the square of the roster: plan 154. Slug versus
  upstream id: plan 153. Hourly refresh with no caller: plan 099.
- Plan-number comments pointing at removed plans (53 under `ai_router/`, 42
  under `packaging/`, 107 under `tests/` on `develop`): plan 157.
- Single-OS CI and grammar-only Python 3.9 gate: plan 156.
- AWS identifiers in tracked source: plan 160. Repository controls and the
  visibility flip: plan 144.
- Service split, diagnostics and key privacy: plan 131 remaining scope.

## Considered and rejected

- "relay.py is never imported by a test, so the mid-stream failure frame is
  untested" (cleanliness lane): false. `tests/test_stream_containment.py`
  drives the terminal frame, `transport_error` and the frame bound through
  the handler.
- "All three `errors.py` substring branches are unreachable" (abstraction
  lane): partly false. The `'api key'` branch is reachable through
  `ai_router/credentials.py:89-90`; F9 records the corrected picture.
- Renaming the `codex_router` logger: rejected by the repository's own record
  (`plans/README.md`, transitional shim section) so installed hosts keep
  their log name.
- Coalescing downstream SSE writes (lane-measured 277 times more write calls
  on adapted streams): unmeasured wall-clock benefit and a real risk of
  withholding bytes; measure `first_write_ms` before and after on a real
  client before any change.
- Splitting `prepare_tools` (127 lines) and `relay` (about 130 lines) into
  named helpers: not worth a plan on its own; the `names` dict is mutated
  across every phase and the extraction risk exceeds the reading benefit
  until a behaviour change needs the seam.
- ruff `target-version = "py39"` against a 3.14 runtime: note only; CI pins
  the rule set explicitly and only F401/F811 run.
- The weekly live-refresh workflow that opened registry pull requests from
  upstream data: deleted on `develop`.
- Empty or short token authorising `//health`: fixed on `develop` by plan
  146; F16 in the gap table.
- Upstream response-header CRLF injection, connection caps, trimming
  `/health`, path disclosure after auth: rejected by the 2026-09-11 audit;
  nothing new changes that.
- A `'wrapper'` key collision in `tool_merge.py:87` (a flat tool whose
  namespace is literally the word "wrapper"): theoretical; not planned.
- The CI "no request cap" grep versus `MAX_INFLIGHT`: the grep guards two
  identifier names and plan 146 chose a third; not a finding, but the guard
  now protects a name rather than a decision.

## Defences that held (verified in code on develop)

- Token first on every route, constant-time byte compare, uniform 403, Host
  guard ahead of the Origin exemption (`ai_router/ingress.py:46-79`).
- External requests build a fresh header dict carrying only the router key;
  the client's headers are accepted and deliberately unused
  (`ai_router/providers.py:157-160`; `ai_router/claude.py:132-136`). Bearer
  auth is structurally barred from a subscription upstream
  (`ai_router/router.py:152-153`). `Cookie` is a hop header
  (`ai_router/transport.py:14-16`).
- Bodies bounded at 16 MiB with `Transfer-Encoding` refused and zstd
  expansion capped (`ai_router/ingress.py:128-143`); `Content-Type` enforced
  (`ai_router/router.py:118-120`); 32 in-flight turns
  (`ai_router/router.py:17`, `:122-129`).
- Logs never carry token, key, header or body content; paths are redacted
  from error bodies (`ai_router/errors.py:11-33`); response descriptions
  collapse to fixed categories (`ai_router/transport.py:81-101`).
- Boot refuses a weak token (`ai_router/runtime.py:55-60`) and a missing
  key for every external provider (`:74-83`); the OpenCode credential path is
  confined to the client's own file (`ai_router/credentials.py:82-86`).
- Tarball extraction rejects absolute paths, `..`, symlinks and hard links
  and uses `filter='data'` (`packaging/service.py:207-215`); the state file
  and key file are minted `0600` inside a `0700` home; the key store uses
  the shared atomic writer under a lock (`ai_router/key_store.py:66-84`).
- Release actions are pinned by commit SHA, the workflow runs only for two
  named actors, re-checks the tag SHA and passes no persisted credentials
  (`.github/workflows/release.yml`); the OIDC trust is tag-scoped
  (`infra/feed.yaml:133-139`).
- Native dialogs quote every interpolated value on all three platforms
  (`ai_router/key_dialog.py:74-75`, `:119-122`, `:160-168`); the key travels
  on the dialog tool's stdout pipe, never in `argv`.

## Coverage limits and unverified

- No live install, log, AWS or deployed-stack inspection; the IAM finding is
  read from the template, not the account. No billed probe.
- The scalability memory figures are the lane's in-memory measurements on
  this Mac with `tracemalloc`, re-read for mechanism but not re-run by the
  main agent. The backlog stall and the two-user port collision are reasoned
  from code and stdlib source, not reproduced.
- Windows behaviour (`icacls` parsing, ACL protection) was read, not
  executed. Browser behaviour around the Origin exemption was reasoned about.
- Hotspot-weighted: `packaging/platforms/*.py`, `packaging/notice.py`,
  `packaging/operator_surface.py`, `tools/probe_*.py`, `tests/` internals and
  `docs/` beyond `architecture.md` and `operations.md` were sampled, not read
  line by line.
- The four lanes' served model identity was not verified.

## Plans created from this audit

New plans, numbered after the live range (099-160):

- `plans/161-update-chain-fetch-hardening.md` (F1)
- `plans/162-bounded-upstream-reads.md` (F2)
- `plans/163-listener-and-token-hygiene.md` (F3)
- `plans/164-request-memory-footprint.md` (F4)
- `plans/165-runtime-leaves-and-architecture-map.md` (F5)
- `plans/166-source-limit-gate-monotone-baseline.md` (F6)
- `plans/167-feed-bucket-write-scope.md` (F7, owner-gated)

Amendments recorded in `plans/README.md` for 152 (F8, F9), 155 (F10), 131
(F11), 116 (F12) and 108 (F13). F14 is an owner decision.

Recommended order: 166 first (it removes friction from every other plan's
baseline edit), then 163, 161, 162, 164, 165; 167 when the owner can deploy
the stack. 163 and 164 both edit `ai_router/router.py`: one writer at a
time, 163 first.
