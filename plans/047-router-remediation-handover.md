# Plan 047: Router remediation handover

> **Executor instructions**: This is a self-contained handover. You do not have
> the investigating session's context and should not need it. Follow the work
> order. Run every verification before moving on. If a STOP condition fires,
> stop and report rather than improvising.
>
> **Investigated**: 2026-09-08, at commit `f2000e8` on `main`.

---

## 1. What you are working on

`~/Documents/Github/SC_Codex_openRouter_adapter` is a loopback HTTP router that
lets the OpenAI Codex CLI and desktop app use OpenRouter models alongside (or
instead of) a ChatGPT subscription. Stdlib-only Python 3.14, no third-party
dependencies, no network in tests.

Codex is pointed at it through `~/.codex/config.toml`:

```toml
openai_base_url = "http://127.0.0.1:<port>/<token>/backend-api/codex"
model_catalog_json = "<home>/mixed-models.json"
```

**The goal Cyril is driving toward**: a non-technical colleague installs one
package on macOS, Windows or Linux, types their OpenRouter key into a window,
and has a working Codex with OpenRouter models. No terminal, no subscription
required, and pushing to `main` updates every installed machine.

---

## 2. Prime directive: the repo is not the deployment

This is the single most important fact and it invalidates the usual
assumptions. **Verified 2026-09-08.**

The running LaunchAgent executes the pre-restructure prototype, not this
package:

```
ProgramArguments = [ /opt/homebrew/bin/python3,
                     ~/.codex/mixed-model-router/mixed_router.py ]
```

`~/.codex/mixed-model-router/` contains loose `mixed_router.py`,
`tool_adapter.py`, `capabilities.py`, `compaction.py` and stray `test_*.py`.
There is **no `current/` symlink, no `releases/`, no `MANIFEST.json`, and no
`Sockets` key** in the plist. Plans 041 and 045 are written, tested, and never
deployed.

Re-verify before you touch anything:

```bash
plutil -p ~/Library/LaunchAgents/com.local.codex-mixed-model-router.plist
ls ~/.codex/mixed-model-router/
```

**Consequences you must hold in mind:**

- A change committed to this repo does **not** affect Cyril's running router.
  Never report a behaviour fix as done on the basis of a passing test alone.
- With no version gate, a file copy plus a restart is a silent production
  deploy. This is how a removed request cap kept reappearing from backup
  folders.
- The deployed prototype logs *more* than the repo does (`input_items`,
  `item_kinds`, `item_keys`) but has no `ts` field. Do not assume the repo's
  logging is the richer one.
- The OpenRouter key currently resolves via `opencode_auth` to
  `~/.local/share/opencode/auth.json`, so the router depends on OpenCode being
  installed. That dependency must not survive to other machines.

---

## 3. The delivery chain is dead in two independent places

**Verified 2026-09-08.**

```bash
gh repo view software-combined/SC_Codex_openRouter_adapter --json isPrivate
#   -> {"isPrivate": true}

curl -sL -o /dev/null -w "%{http_code}\n" \
  "https://github.com/software-combined/SC_Codex_openRouter_adapter/releases/latest/download/latest.json"
#   -> 404

ls ~/Library/LaunchAgents/com.local.codex-mixed-model-router.update.plist
#   -> No such file
```

1. The repo is private, so `FEED_URL` at `packaging/install.py:24` returns 404
   to an unauthenticated fetch, and `fetch()` sends no credentials.
2. The update LaunchAgent was never installed, so nothing polls anyway.

Nothing has ever auto-updated. Fixing this is Work Order A.

---

## 4. Rules of engagement

Read `AGENTS.md` in the repo root and `~/.codex/AGENTS.md`. The binding rules:

- **Worktree discipline.** One writable worktree per agent session. Never edit
  the primary checkout at `~/Documents/Github/SC_Codex_openRouter_adapter`.
  The session worktree is `~/Documents/Github/.worktrees/codex-isolated-install`
  (see section 5) — reuse it rather than creating a second.
- **Source limits.** Modules 250 soft / 400 hard lines, entrypoints and tools
  400 / 700, tests 300 / 500. Enforced by `tools/check_source_limits.py`.
- **Commit size.** Under 800 changed lines per staged commit, target under 500
  for complex logic. Split by real dependency, not to hit a number.
- **Before every commit** run the `pre-commit-review` skill. Commit subjects are
  `<type>: <short summary>` with type `feat|fix|refactor|test|chore|docs`.
- **Every user-visible change** updates `CHANGELOG.md` and `packaging/VERSION`.
- **No paid probes without asking.** `tools/probe_codex_runtime.py` and any live
  OpenRouter call bills Cyril's key. Ask first, every time.
- **Do not disturb the running router** except at the explicit gates below. It
  is serving Cyril's real work. Check `/health` before and after anything that
  touches `~/.codex/mixed-model-router/`.

Verification triad, run all three before any commit:

```bash
python3.14 -m unittest discover -s tests -t .
python3.14 -m compileall -q codex_router tools tests
python3.14 tools/check_source_limits.py
```

Baseline at handover: **182 tests pass, source limits clean.**

---

## 5. What has already been done

A now-removed worktree held uncommitted work (landed as `11475c6`, merged
to `main`; see the reconciliation note in section 4):

```
path:   ~/Documents/Github/.worktrees/router-cap-guard   (removed)
branch: chore/no-request-cap-guard   (from main @ f2000e8, merged)
```

Two files modified, committed as `11475c6`:

- `.github/workflows/check.yml` — a `No request cap` step that fails CI if
  `request_cap` or `DEFAULT_REQUEST_CAP` appears in `codex_router`, `tools`,
  `tests` or `packaging`. Tested both directions: passes clean, fails when the
  constant is reintroduced.
- `plans/035-...md` — a RESOLVED note at Step 5 so the historical cap snippet
  quoted there can no longer be read as an open decision.

Also done, outside the repo: the five `before-*` backup folders in
`~/.codex/mixed-model-router/` were moved to `retired/`. Four of them contained
capped copies of `mixed_router.py` and were the resurrection source. The live
router was verified clean and healthy afterwards.

**Reconciliation (2026-09-08)**: the cap-guard commit landed as `11475c6`
and its worktree/branch were removed after integration. The obsolete
`router-cap-guard` instructions above no longer apply; do not recreate that
worktree. The live session worktree is `~/Documents/Github/.worktrees/codex-isolated-install`
(branch `codex/isolated-install-state`, target `main`), owned by the audit-brief
goal thread and reused across its slices.

Per `docs/operations.md`, `retired/` may be deleted after a one-week hold, so
not before **2026-09-15**, and only once Work Order B has given the machine a
real rollback path.

---

## 6. Blocked on Cyril, do not stall

Three items need his money or a decision. **Do not wait on them and do not
improvise around them.** Do the unblocked work, and raise these once.

| Item | Cost | Blocks |
|---|---|---|
| Apple Developer Program | USD $99/yr | Work Order E entirely. No workaround exists since Sequoia removed the Control-click Gatekeeper bypass. |
| Azure Artifact Signing eligibility | USD ~$120/yr | Work Order F. Individual tier is US/Canada only; an Australian entity needs organisation validation, which takes 1 to 20 business days. Fallback is SSL.com at ~$309/yr. Start validation before writing Windows code. |
| AWS account and region for the release bucket | ~USD $1/mo | Work Order A. Needs an account, a region, and a decision on whether the signing key lives in a GitHub Environment secret (fast) or AWS KMS (better). |

**Do not spend money on**: an EV Windows certificate (Microsoft's own docs now
state EV no longer bypasses SmartScreen), Nuitka Commercial, Linux code
signing, or TUF.

---

## 7. Work order

Sequenced by dependency. Each item is independently shippable and must change
an operational outcome, not just add source files.

### A. Working delivery (do this first)

Nothing else matters until a push can reach a machine.

1. S3 bucket behind CloudFront with Origin Access Control. Not S3 website
   hosting, which cannot use OAC and would force a public bucket.
2. GitHub OIDC for CI. **Trap**: this repo was created 2026-09-07, after
   GitHub's July 2026 cutover to immutable subject claims, so the trust policy
   needs numeric IDs (owner `200868195`, repo `1360169840`), not the
   `repo:org/name` form. Use `StringEquals`, never `StringLike` with a trailing
   wildcard, and bind to `environment:release`.
3. Sign the feed. Today the SHA256 sits inside a feed served from the same
   origin as the bundle, so it stops corruption but not a bucket compromise.
   This is a remote code execution channel into every staff machine, so treat
   it as the highest-severity item in the plan. Ed25519 detached signature over
   the feed document, public key compiled into the installer. Python 3.14 has
   no asymmetric verification anywhere in the stdlib, so the verifier is about
   42 lines of RFC 8032 over `hashlib`. Verify **before** `safe_extract`.
4. Add a `serial` to the feed and refuse any feed whose serial is below the last
   accepted one. Without it an attacker who can write the bucket can freeze the
   fleet on a known-bad release by replaying an old, validly signed feed.
5. Cache-Control: feed `public, max-age=0, s-maxage=60,
   stale-while-revalidate=300, stale-if-error=86400`; versioned artefacts
   `public, max-age=31536000, immutable`. Never invalidate; version filenames
   instead. Keep the existing ETag logic, it already turns most polls into 304s.
6. Delete `resolve_beta_feed()`'s GitHub API call; beta becomes
   `beta/latest.json` on the same CDN.

**Proof of success**: push to `main`; within fifteen minutes Cyril's `/health`
reports the new version and `logs/update.log` records a verified signature.
Nothing below counts as done until this works.

### B. Cut over the live machine to versioned releases

Only after A. This is the fix for silent deploys and the reason the cap kept
returning.

Run the installer for real, confirm `current/`, `releases/` and `MANIFEST.json`
exist, confirm the plist gains its `Sockets` key, and confirm `/health` reports
the bundle version. Keep the previous prototype until a rollback has been
rehearsed once.

**Two blocking bugs to fix first, or the install will not work on any machine
other than Cyril's:**

- `packaging/install.py:372` always writes `model_catalog_json`, but
  `--static-catalogue` at `:483` is parsed and never read. Plan 041 Step 14
  says the line is conditional on that flag.
- **Nothing in the repo generates `mixed-models.json`.** The installer points
  Codex at a file it never creates. `catalogue.merge()` is called from one test
  and nowhere else, and `apply_catalogue.apply` skips slugs it does not already
  find, so `models add` writes a registry row that never reaches the picker.
  Wire `merge()` into the installer and `catalogue --check` into `check.yml`.
  This is invisible on Cyril's machine because the file exists from the manual
  trial.

**Proof of success**: a second machine, or a clean `ROUTER_HOME`, installs and
gets a working picker.

### C. Protocol correctness

Independent of packaging, safe to do in parallel with A once the worktree is
clean. Ordered by severity. Each needs a regression test that fails without the
fix.

1. **Discovered tools vanish after compaction.** `tool_adapter.py:60-71`
   recovers full definitions of searched-for tools *only* from
   `tool_search_output` items still in history, and `compaction.py:79` destroys
   those items. The model is then sent a history where it called
   `slack.send_message` alongside a tool list that no longer contains it, and
   correctly reports the capability does not exist. Persist discovered tool
   definitions per conversation instead of rederiving them each turn.
2. **A declared stub blocks its own full definition.** `tool_adapter.py:63-66`
   keys `declared` on `(namespace, name)` only, so when Codex ships a stub in
   `tools` and the real schema in `tool_search_output`, the `continue` discards
   the schema and `:106` leaves a function tool with no `parameters` at all.
   Merge on `(namespace, name)`, preferring whichever copy has `parameters`.
3. **Compaction transcript has a hole.** `compaction.py:128-134` uses `continue`
   where it needs `break`, so the oldest item survives while recent items in the
   middle are silently dropped. Also add the tool name to each line. The
   existing test uses two items and cannot catch this.
4. **Compaction runs full request preparation then discards it.**
   `router.py:143` calls `prepare()` for `/responses/compact` too, so
   `check_effort` and `prepare_tools` run and a thread carrying a rejected
   effort cannot even be compacted. Branch to `compact` before `prepare`.
5. **Compaction is invisible to metrics and the drain.** It returns at
   `router.py:152` before `inflight` is incremented at `:172`, so a release
   landing mid-compaction exits immediately and loses the work plus the billable
   summariser call.
6. **Summariser can emit nothing.** `providers.py:123-127` hard-codes
   `max_output_tokens: 2000` and sends no `reasoning`, so a model defaulting to
   high effort can spend the whole budget on reasoning tokens, raise, and 409.
   Both DeepSeek V4 models support only `high` and `xhigh`. Send the lowest
   supported effort explicitly and raise the cap.
7. **Strip `encrypted_content` from reasoning items bound for OpenRouter.**
   80,363 of them in the live log, none readable by a non-OpenAI model. Keep the
   plaintext `summary`. Note `compaction._item_text` already drops this field
   for summariser transcripts, so the intent is established — but
   `tests/test_mixed_router.py:59-68` currently asserts the opposite as a
   contract and must be updated deliberately, not quietly.
8. **Map upstream 429 to 503 with `Retry-After`.** Codex treats a bare 429 as
   non-retryable and turn-fatal.
9. **Normalise the transcript per target model** in `prepare`. Beyond effort,
   nothing is checked today: images reach text-only models (GLM 5.3, both
   DeepSeek V4), oversized context reaches `~x-ai/grok-latest` at 500k, and
   Grok's 350-tool ceiling produces a 409 telling the user to restart Codex,
   which does not reduce the count.

### D. The two visible annoyances

1. **Show which model actually served.** Capture `response.model` from the
   stream into the event log and `/health`. **Trap**: Codex reads the
   `openai-model` response header and, on any mismatch with the configured
   slug, emits a hardcoded warning claiming the account was flagged for
   high-risk cyber activity. The neutral `ModelReroute` event exists but the TUI
   discards it. So never surface a differing model through that header; use a
   sidecar channel.
2. **Tilde slugs.** `~` is OpenRouter's own alias convention, thirteen aliases
   exist live, and no non-tilde twin exists for any of them, so the prefix must
   reach the wire. But `/api/v1/models` already carries the resolution:
   `"alias_target": {"name": "SpaceXAI: Grok 4.6", "slug": "x-ai/grok-4.6"}`.
   Fold `alias_target.name` into the generated `display_name` at catalogue-build
   time. If you instead decouple the local slug from the upstream one,
   **`live_refresh.py:41` will silently stop refreshing that row forever** —
   that is the trap to design around.

### E. macOS one-click installer

Blocked on the Apple Developer Program. Ship an unpacked
`python-build-standalone` interpreter beside the source tree rather than
PyInstaller or Nuitka: it keeps the ~200 KB delta update intact, where a real
bundler makes every code change a 25 to 50 MB download for every machine.
Verify `compression.zstd` works in the chosen build — it is a hard requirement,
because Codex zstd-compresses request bodies.

Prerequisites that are not blocked and can be done now: split the 498-line
`packaging/install.py` into a package before two more service back-ends break
the 700-line hard limit; replace the `current` symlink with a pointer file,
since Windows symlinks need elevation; add an authenticated
`POST /<token>/shutdown`, since neither Windows nor Linux has
`launchctl kill TERM`.

De-risk in the first week: prove hardened runtime plus notarisation works
across `bin/python3` and the ~40 `lib-dynload/*.so` files before building
anything on top.

### F. Windows, then Linux

Windows: Inno Setup with `PrivilegesRequired=lowest`, plus a Scheduled Task
registered from XML with a logon trigger, a five-minute repetition and
`MultipleInstancesPolicy=IgnoreNew` as a dependency-free KeepAlive equivalent.
Use `pythonw.exe` or every logon flashes a console. Set an explicit ACL on the
key file, because `credentials.py:20` skips the mode check when `os.name ==
'nt'`. Check whether anything sets `ROUTER_OPENROUTER_KEY_<port>`, referenced at
`install.py:383` — nothing appears to.

Linux: systemd user units with socket activation via `LISTEN_FDS` (no ctypes
needed). `TimeoutStopSec` must exceed the 120-second drain deadline, and use
`WantedBy=default.target`, not `multi-user.target`. Boot start needs
`loginctl enable-linger`; detect and report, never silently escalate.

**Ask Cyril whether anyone actually runs Linux before building F's second
half.**

### G. First-run key window

Not tkinter, not native dialogs. The daemon is already an authenticated HTTP
server, so add `GET/POST /<token>/setup` and have the installer call
`webbrowser.open()`. One code path everywhere, no new dependencies, and it can
validate the key against OpenRouter and show remaining credit before writing
it, plus ask the subscription question that Plan 043 needs and no installer
currently asks.

Two details: `authorized_path()` rejects any request carrying an `Origin`
header, which is the correct DNS-rebinding defence and will block the setup
page's own POST, so add a narrow carve-out on that route only; and give the
setup URL a single-use short-lived nonce distinct from the long-lived path
token.

Keep the mode-600 key file. Keychain, DPAPI and libsecret each defend against
one thing — another local user reading the file — which the file mode already
handles, and none defends against malware running as the user.

### H. Instruction injection and housekeeping

- **Migrate `base_instructions` to `model_messages.instructions_template`.**
  OpenAI removed the legacy field from its bundled catalogue on 2026-09-07 and
  added a release-workflow filter to keep it out. All 25 entries still use it.
  It is duplicated into every entry and accounts for 61% of the 773 KB
  catalogue file. This is also where Cyril wants AGENTS.md guidance about tools
  and subagents injected, so do the migration before adding content.
- `pyproject.toml` says `0.3.0`, `packaging/VERSION` says `0.4`. Reconcile, and
  make `VERSION` semver as `AGENTS.md` requires.
- `plans/README.md` marks 041, 044, 045, 046 and 042 as TODO, but git history
  shows them implemented. Update the status table.
- `router.py:163` catches `AttributeError` and `TypeError` and reports them as a
  400 user error, which will hide genuine router bugs.
- `stdout.log` in the state directory is 7.3 MB and unrotated, separate from the
  rotating `logs/router.jsonl`.

---

## 8. Do not spend time on these

Checked and either correct or benign. Re-investigating them wastes the budget.

- **Header stripping is not why the served model is invisible.** `HOP_HEADERS`
  removes only hop-by-hop headers plus `set-cookie`. Every `x-*` header already
  reaches Codex. The gap is capture, not stripping.
- **Popping `defer_loading` is not the payload cause.** Measured at roughly
  neutral: it saves ~23 bytes per tool while namespace flattening adds ~30. The
  cause is that nothing filters the catalogue at all.
- **Empty `vendor` on `anthropic/claude-opus-5` is cosmetic.**
  `short.startswith('')` is always true, so no malformed prefix is produced.
- **Tool-search translation is correct** for the current upstream wire shape.
  Codex runs the search client-side with a local BM25 index; the router's
  rewrite to `codex_client_tool_search` is right and needs no change.
- **zstd request decode is required, not optional.** Codex compresses request
  bodies whenever ChatGPT-family auth is in use on a provider named `OpenAI`,
  which is your configuration.
- **`service_tier` stripping and `max_output_tokens` injection are both
  correct.** Codex never sends `max_output_tokens` itself.
- Also verified clean: credential isolation, loopback auth and constant-time
  comparison, body limits and zstd bomb protection, `safe_extract`, the drain
  lifecycle, registry validation, `integer_json`, `has_recursive_refs`, and
  wire-name collision resistance.

---

## 9. Latent, not yet biting

Codex's current default is remote compaction **V2**, which works inline over
`/responses` by appending a `compaction_trigger` item and requiring exactly one
`{"type":"compaction","encrypted_content":...}` output item back. Getting the
count wrong is fatal and not retryable, with no fallback to local
summarisation. **`compaction_trigger` appears nowhere in this repository.**

It has not fired yet: zero occurrences across 22,651 live requests, because
auto-compact triggers at 90% of the context window and the 1M-context models
sit around half that. But `~x-ai/grok-latest` has a 500k window, putting its
threshold near 450k tokens, and the largest observed request is already 1.95 MB.
**The first long Grok thread is the one that breaks.**

The proven pattern is opencodex's `ocx1:` envelope: base64 the summary behind a
sentinel prefix in `encrypted_content`, decode on replay. MIT licensed. This
repo's `compaction.py` already knows the prefix and can decode it; nothing
produces it.

---

## 10. Measured baseline

From the live event log, ~12,000 completed requests, 2026-09-08. Use these to
judge whether a change actually improved anything.

| Metric | p50 | p90 | p99 | max |
|---|---|---|---|---|
| Request bytes | 237 KB | 1.51 MB | 1.84 MB | 1.95 MB |
| Input items | 83 | 862 | 1,763 | 1,796 |
| Tool definitions | 58 | 81 | — | 94 |
| Total latency | 6.1 s | 17.1 s | 75.5 s | 901 s |
| First chunk | 3.5 s | 5.7 s | 10.3 s | 11.6 s |

`request_bytes ≈ 929 × input_items + 1950 × tool_definitions − 34813`, so each
exposed tool costs ~1.95 KB on every request. At p90 the split is 72% history,
17% tool schemas.

Status codes: 200 ×11,632, 429 ×258, 400 ×9, 520 ×2. Of the 429s, 251 were
`gpt-5.6-luna` on the ChatGPT subscription, not OpenRouter.

---

## 11. STOP conditions

Stop and report rather than continuing if any of these occur.

- Cyril's router fails `/health` after any change you made, and a single
  restart does not restore it.
- `plutil -p` shows the LaunchAgent pointing somewhere you did not intend.
- The verification triad fails and the cause is not obviously your own change.
- A step requires a paid OpenRouter or Codex probe that has not been approved.
- A step requires spending money, or credentials you have not been given.
- You find a second writer active in the repo or in
  `~/.codex/mixed-model-router/` — two concurrent agents editing the live
  router is what caused the original cap regression.
- A staged diff would exceed 800 changed lines and you cannot split it along a
  real dependency boundary.
- Anything in `retired/` needs to be restored. Ask first; those are the only
  rollback path until Work Order B lands.

---

## 12. Reporting

Report progress as operational outcomes, not file counts. "Feed signed and
verified on Cyril's machine, `/health` reports 0.4.124" is progress. "Added
`verify.py` and six tests" is not, on its own.

When you finish a work order, state plainly what is deployed versus merely
committed. Those are different, and conflating them is the specific failure
mode this whole plan exists to correct.
