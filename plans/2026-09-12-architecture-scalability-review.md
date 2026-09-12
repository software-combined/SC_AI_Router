# Architecture and scalability review (2026-09-12)

Read-only review of this repository ahead of the Apache-2.0 public flip, run at
worktree HEAD `0024a42` on branch `cyril/public-readiness-20260912`. Method:
read `AGENTS.md`, `docs/architecture.md`, `plans/README.md` and every
non-DONE plan, then re-derive every claim from the source itself. The offline
suite was run once (`python3.14 -m unittest discover -s tests -t .`: 1217 tests,
exit 0, 137 s) and `python3.14 tools/check_source_limits.py` once
(`checked=192 failures=0`). No file was edited, no git state was changed, no
network call was made, and no billed probe was run.

`origin/develop` had already moved one commit ahead to `4b9cdf4` while this
review was being written. Every drift check in the new plans pins `0024a42`,
which is an ancestor of that head, so an executor reconciles one commit of
drift at most.

## Verdict

The architecture is sound and the hard part is already done: the provider
definition table is a genuine leaf, the request path is parameterised by that
table rather than by provider name, protocol dispatch is a small explicit
table, and a synthetic second provider already routes end to end in
`tests/test_provider_swap.py`. What is left is not structural, it is the last
few OpenRouter-shaped assumptions that sit outside the table: the failure
dialect is compared as the string `'openrouter'` in the relay, the key-info
check understands only OpenRouter's response body, live model metadata has
exactly one shape, and the registry keys rows on a bare slug so two providers
can never serve the same upstream model id. Model onboarding is already a
single probe-gated command, but the merged catalogue duplicates a 20,936-byte
instruction blob into every row, so a 27-row catalogue is already 629,869
bytes and the file grows with the square of the roster. Client attachment is
cleanly separated from protocol, yet the client set is an enum repeated in
four places and the two Claude visibility projections currently disagree with
each other. The test suite is genuinely good and genuinely offline; CI is the
weak link, because it runs the suite only on `pull_request`, only on Ubuntu,
and never on a real Python 3.9 interpreter even though half of `packaging/`
must run there. None of this blocks publication. The publication blockers are
smaller and dumber: two duplicated plan numbers, 84 source lines pointing at
plan numbers that no longer exist, and an AWS account id in four tracked
files.

## Evidence table

| Claim | Evidence | What it means |
|---|---|---|
| The provider table is a real leaf with no imports and one entry per upstream | `ai_router/provider_defs.py:84-105`; `tests/test_provider_defs.py:136-141` | Host, paths, key location, catalogue and dialect already live in one place |
| A synthetic second provider already routes, bills and labels correctly | `tests/test_provider_swap.py:80-155` | The transport half of "add a provider" is bounded and tested |
| The relay compares the dialect as a literal string | `ai_router/relay.py:53`, `:57` | A provider with any other dialect silently loses the context-window frame and the key-rejected window |
| The relay's refusal cache is hard-wired to one provider id | `ai_router/relay.py:20-23` | Only OpenRouter turns get the 409 refusal cache |
| The failure describer parses OpenRouter's metadata envelope | `ai_router/upstream.py:99-128` | Another provider's 4xx body falls through to a raw relay with no described message and no bounded code |
| The key-info check assumes OpenRouter's `{"data": {...}}` body | `ai_router/key_store.py:44-50` | A provider whose key endpoint answers a different shape reports a valid key as rejected |
| Live metadata derivation has exactly one shape | `ai_router/models.py:33-34`, `:306`; `ai_router/live_refresh.py:21-37` | Any second provider is `manual` shape today and its rows are hand-authored |
| Registry rows key on the bare slug and reject duplicates | `ai_router/registry.py:64-65`, `:113`, `:116-117` | Two providers can never both serve `anthropic/claude-opus-5`; a direct Anthropic, Azure or self-hosted provider is blocked on identity, not transport |
| The second-provider fixture borrows OpenRouter's dialect and shape | `tests/test_provider_swap.py:38-40` | The acceptance proof does not exercise a genuinely foreign provider |
| Only one provider key file is ignored by git | `.gitignore:14` | A second provider's key file is not ignored and can be committed by accident |
| Client-facing prose names one provider | `ai_router/errors.py:59`, `:127`; `ai_router/catalogue.py:148`; `ai_router/openrouter_base_instructions.txt:1` | A second provider's users are told to "use an OpenRouter model" |
| The merged Codex catalogue is 629,869 bytes for 27 rows, 90% of it one repeated instruction blob | measured from `ai_router/catalogue.py:133-145`, `:181-201`, `:289` | The catalogue grows with rows squared: 19 rows is 0.4 MB, 200 rows projects to about 5.1 MB |
| The roster line inside the instructions grows with visible rows | `ai_router/catalogue.py:152-161` | Instruction bytes per row grow with the roster, which is the squared term |
| Subscription rows are served the routed-model instructions | `ai_router/catalogue.py:133-145` with `:148` | A ChatGPT subscription session on `gpt-6-astra` is told it is "running the selected OpenRouter model" |
| Onboarding is already one probe-gated command with a discover report | `ai_router/models.py:110-176`, `:235-268` | Onboarding is not the bottleneck; visibility and propagation are |
| Hourly registry refresh exists but has no caller | `ai_router/model_refresh.py:1-13`, `:109-138` | Growing the roster still needs a release and a restart |
| Client visibility has two owners that disagree | `ai_router/clients/__init__.py:11-29` versus `ai_router/claude.py:65-79` | Measured: `/v1/models` returns 19 rows including four externally billed Anthropic rows; `models_for(MODELS, 'claude')` returns 15 and none of them |
| The client set is an enum repeated in four places | `ai_router/clients/__init__.py:22`; `ai_router/catalogue.py:371`; `packaging/install.py:207`, `:577-580` | A third client is four edits plus an adapter, and nothing tells you that |
| Protocol dispatch is already separable from client activation | `ai_router/protocols/__init__.py:17-26`; `packaging/codex_config.py`; `packaging/claude_config.py` | A third client that speaks Responses or Messages is an activation adapter, not a protocol change |
| The offline suite is large and clean | 1217 tests, exit 0, 137 s at `0024a42` | Coverage breadth is real |
| CI runs the suite on one OS and only for pull requests | `.github/workflows/check.yml:23`, `:32-33` | A push to `develop` never executes a test |
| macOS dialog paths never execute in CI | `tests/test_key_prompt.py:341`, `:351`, `:365`; `tests/test_notice.py:199`, `:213`; `tests/test_notice_delivery.py:214` | The first-run key window and update notice are proven only on the owner's Mac |
| Python 3.9 compatibility is grammar-only | `tests/test_packaging.py:219-246` | A 3.10+ stdlib call in `packaging/` passes the gate and breaks on a real 3.9 host |
| The source-limits baseline drifts silently | `tools/check_source_limits.py:23`; measured two stale entries: `ai_router/router.py` recorded 204 against 207 actual, `tests/test_history_portability.py` recorded 164 and is now under the soft cap | Stale entries are never validated because the baseline is read only above the soft cap |
| Source carries 212 plan references on 123 lines; 84 of those lines name 23 plan numbers with no file | measured across `ai_router/`, `packaging/`, `tools/`, `tests/` | A public reader following a comment to `plans/063-*.md` finds nothing |
| Two plan numbers are used twice | `plans/139-native-key-popup.md` versus `plans/139-router-private-feed-publication.md`; `plans/145-model-verification-gate.md` versus `plans/145-router-tool-alias-repair.md` | `139-native-key-popup.md` has no row in `plans/README.md` at all, and its work has already landed |
| The AWS account id is in four tracked files | `.github/workflows/release.yml:17-18`; `infra/feed.yaml:22`; `tools/publish_feed.py:17`; `tools/publish_first_install.py:30` | Publication discloses the account, bucket and publisher role name |
| The release bundle ships every developer tool | `packaging/release.py:55` | Probe harnesses and the key ceremony land on recipient machines |
| The changelog is one 1125-line file with 22 version headings | `CHANGELOG.md` | A first-time reader cannot find the current release |

## What already scales

- **The provider definition table.** `ai_router/provider_defs.py` imports
  nothing, is spec-loadable on Python 3.9, and owns host, endpoint prefixes,
  key location, catalogue URL, catalogue shape, key-info URL and dialect. The
  boundary scan in `tests/test_provider_defs.py:107-133` proves no other module
  under `ai_router/` names a provider host, key env var or key file.
- **Adapter construction from the table.** `providers.adapters()`
  (`ai_router/providers.py:249-257`) builds one adapter per external definition
  serving Responses, so a new table entry is routable with no second
  registration. `claude.select` does the same for Messages
  (`ai_router/claude.py:152-171`).
- **Credential resolution.** `Credentials.key_for`
  (`ai_router/credentials.py:36-71`) follows the definition's own precedence
  and fails closed per provider, proven by
  `tests/test_provider_swap.py:125-142`.
- **The key ceremony is already multi-provider.** `setup.open_key_window` and
  `_repoint_window` (`ai_router/setup.py:153-236`) take a provider id and
  repoint an open window, and `setup_page.form`
  (`ai_router/setup_page.py:55-77`) renders labels and placeholders from the
  definition.
- **Protocol dispatch.** `ai_router/protocols/__init__.py:17-26` is a
  three-row table whose path sets are owned by `providers` and `claude`, with a
  contract test that the union stays exact
  (`tests/test_protocol_contracts.py:23-38`).
- **Model onboarding.** `models add <slug> --probe` derives the row, writes it
  unlisted, verifies it in isolation and only then promotes
  (`ai_router/models.py:110-176`). `models discover`
  (`ai_router/models.py:235-268`) reports the live diff without writing or
  billing.
- **Offline testing.** 1217 tests run with no network, a shared fake upstream
  (`tests/fakes.py`), a shared server harness (`tests/harness.py`) and a
  stateful launchd double (`tests/fakes.py:20-60`) that reproduces the real
  bootout race rather than rubber-stamping it.
- **Source size discipline.** Every module is under its hard cap, and the
  domain-boundary test (`tests/test_domain_boundaries.py:57-77`) proves its own
  detector is not vacuous.

## What does not scale

1. **Provider dialects.** The three places that decide "is this provider
   OpenRouter" are string compares (`ai_router/relay.py:20`, `:53`, `:57`) and
   one envelope parser (`ai_router/upstream.py:99-128`). A Groq, Together,
   Azure or self-hosted OpenAI-compatible endpoint returns a plain
   `{"error": {"message": ..., "code": ...}}` body; `_provider_reason` reads
   `error.metadata.provider_name` and `error.metadata.raw`, finds neither, and
   returns `None`, so `describe_failure` gives up and the raw upstream body is
   relayed. The same provider never gets the context-window SSE frame and never
   opens the key window on a 401.

2. **Model identity.** `registry.load` rejects duplicate slugs
   (`ai_router/registry.py:64-65`) and `BY_SLUG` is a single flat map
   (`:113`). The routing key is the bare slug, so the registry can express
   "OpenRouter serves `anthropic/claude-opus-5`" or "a direct Anthropic key
   serves it", never both. This, not transport, is what blocks a direct
   Anthropic, Azure OpenAI or self-hosted provider.

3. **Catalogue size.** `subscription_stub` and `external_entry` both embed the
   full rendered instructions into every row
   (`ai_router/catalogue.py:145`, `:194`), and `instructions_for`
   (`:152-161`) renders every visible slug into that text. Measured: 19
   external rows produce 443,606 bytes; with the eight-row subscription roster,
   27 rows produce 629,869 bytes, of which 89.7% is the repeated blob. Scaling
   the roster to 100 rows projects to about 2.3 MB and 200 rows to about
   5.1 MB, parsed by the client at every start.

4. **Roster propagation.** `ai_router/model_refresh.py` is complete and tested
   but its docstring records the truth: `start()` has no caller
   (`:3-6`). Every new model still needs a release. Plan 099's own STOP
   condition names the repository being private as the blocker; the public flip
   removes it.

5. **Client visibility.** Two projections answer "what does Claude see" and
   they disagree. `clients.visible_for` hides externally billed Anthropic rows
   (`ai_router/clients/__init__.py:26-29`); `claude.models_listing`
   (`ai_router/claude.py:65-79`) never calls it and lists those same four rows
   under bare ids. Whichever is intended, nothing records the decision and no
   test pins the difference.

6. **Client enumeration.** Adding Cursor, OpenCode, Cline, a Gemini CLI or a
   plain OpenAI-compatible client means editing four separate enums plus
   writing an activation adapter. Nothing in the repository states the contract
   a new client must satisfy, so the cost is discovered rather than known.

7. **CI breadth.** `.github/workflows/check.yml:32-33` runs the suite only on
   `pull_request`, and only on `ubuntu-latest` (`:23`). The darwin-gated tests
   (six of them, listed in the evidence table) never execute there, the
   Windows backend is exercised only through Python fakes, and Python 3.9
   compatibility is a grammar assertion rather than an interpreter run
   (`tests/test_packaging.py:219-246`).

8. **Backlog and reference hygiene.** 84 source lines cite 23 plan numbers
   with no file; two plan numbers are duplicated; `plans/139-native-key-popup.md`
   is absent from the backlog tables entirely even though its modules
   (`ai_router/key_dialog.py`, `ai_router/key_prompt.py`,
   `ai_router/setup_page.py`) all exist. The recommended execution order in
   `plans/README.md` still assumes a private repository.

## Recommendations ranked by value over effort

| Rank | Recommendation | Value | Effort | Plan |
|---|---|---|---|---|
| 1 | Make the failure dialect, key-info shape and key-window trigger table-driven, so a non-OpenRouter provider is a first-class citizen | High | M | 152 |
| 2 | Separate the client-facing slug from the upstream model id so two providers can serve the same model | High | M | 153 |
| 3 | Put a measured size budget on the merged catalogue and bound the roster text | High | M | 154 |
| 4 | Give the client set one owner and one contract, and make the two Claude projections agree on purpose | High | M | 155 |
| 5 | Run the suite on three operating systems, on every push, and on a real Python 3.9 for the installer half | High | S | 156 |
| 6 | Repair every dangling plan reference and add a test that keeps them resolvable | Medium | S | 157 |
| 7 | Split the changelog and finish the docs index for a first-time public reader | Medium | S | 158 |
| 8 | Consolidate the backlog: fix the two number collisions and move owner-gated paid legs to a separate acceptance list | Medium | S | 159 |
| 9 | Move the AWS account id, bucket and role out of tracked source into workflow inputs | Medium | S | 160 |

## Explicit rejections

- **A generic provider plugin system with entry points or dynamic loading.**
  `AGENTS.md` section 1 forbids third-party dependencies and the definition
  table already gives the needed indirection. A plugin loader would add an
  attack surface (arbitrary code chosen by data) for a table that has three
  rows.
- **A protocol translation layer so any provider can serve any client.** The
  2026-09-12 external review already rejected a LiteLLM-style sidecar and the
  reasoning holds: byte-identical passthrough is what keeps thinking blocks,
  tool_use ids and cache_control intact (`ai_router/claude.py:1-13`).
  Translation would put us on the hook for every upstream schema change.
- **Making the registry a database or a service.** 19 rows today, 200 as the
  validated ceiling (`ai_router/model_refresh.py:35-36`). A validated JSON file
  plus an atomic swap is the right size and is already written.
- **Splitting `ai_router/` into subpackages by domain.** The current flat
  module set with a boundary test is easier to read for a newcomer than a deep
  tree, and `docs/architecture.md` already carries the map. Renaming would
  break 212 plan references and every installer path for no functional gain.
- **Deleting `codex_router/` now.** `plans/README.md` records the removal
  condition and `packaging/router_launch.py` still falls back to the old name
  for pre-rename installed releases. Removing it before that search is run
  would break existing installs.
- **Dropping the per-row `instructions_template` entirely.** It is how routed
  sessions learn the delegation roster and the tool-name rule
  (`ai_router/openrouter_base_instructions.txt:1-18`), and plan 151 has live
  incident evidence for why it exists. The fix is to bound its growth, not to
  remove it.
- **Adding a third client now.** No demand is recorded, and the external
  review already rejected Cursor, Gemini CLI and similar targets. Plan 155
  makes the contract explicit so the decision stays cheap, without attaching
  anything.
- **Rewriting the changelog history.** The entries are evidence. Plan 158
  archives rather than edits them.

## Risks and open owner decisions

1. **Which Claude surface is authoritative.** Plan 155 documents the current
   difference and makes both projections read one table. Whether `/v1/models`
   should keep listing the four externally billed Anthropic rows is an owner
   call, and the plan stops rather than guessing.
2. **A second real provider needs a paid key.** Plans 152 and 153 are proven
   offline with a synthetic provider. Turning that into a real second upstream
   is an owner-gated, billed step that belongs in the acceptance list plan 159
   creates.
3. **Catalogue size is bounded by a client we do not own.** Plan 154 sets the
   budget from measurement, but only a live Codex start on a large catalogue
   proves the client tolerates it. That leg is owner-gated.
4. **The AWS account id may be acceptable to disclose.** Plan 160 moves it out
   of source; keeping it public is a legitimate owner choice, and the plan says
   so rather than assuming.
5. **CI cost.** Plan 156 adds two runners and one short 3.9 job. On a public
   repository with a busy fork queue this is a real minute cost, and the owner
   may prefer the matrix on merge only.
6. **Python 3.9 for `packaging/`.** If the owner is willing to raise the
   installer floor to 3.11, most of plan 156's 3.9 job and several
   `spec_from_file_location` workarounds disappear. That is a larger decision
   than this review should make.
