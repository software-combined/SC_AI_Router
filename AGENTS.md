# SC Router agent instructions

## 1. Purpose

Local loopback router that keeps ChatGPT subscription traffic on OpenAI and
Claude subscription traffic on Anthropic, and routes approved OpenRouter
models with a separate key. Runtime Python 3.14+, stdlib only, no
third-party dependencies, no network calls in the unit suite. Explicit live
probes run separately under section 5's verification rules.

## 2. Worktree discipline

One writable worktree per agent session; never edit the primary checkout.
Never run `git reset --hard` or `git checkout --` without explicit approval.
Record worktree ownership (path, branch, owning task, integration target) and
reuse the same worktree for follow-ups. Clean up after verified integration.

Base every branch on `develop` and target every PR at `develop`,
except release PRs from `develop` to `main` and the scoped plugin release
procedure in section 9. Never push directly to `main`.

## 2a. Architecture

`docs/architecture.md` owns domain responsibilities and allowed dependency
direction. New modules go where that map says; transitional owners name the
plan that will move them.

## 3. Source limits

Modules 250 lines soft / 400 hard, entrypoints and tools 400/700, tests
300/500. Checked by `python3.14 tools/check_source_limits.py`. A file above
the soft cap needs a baseline entry, which is a ceiling: the file may shrink
freely and may not grow past the recorded count. Remove the entry once the
file is back under the cap. Keep the
router and provider modules small. An upstream is one entry in
`ai_router/provider_defs.py` (host, endpoint prefixes, key location,
catalogue, failure dialect) consumed by adapter classes parameterized with
that definition; a provider with a different wire format is a new adapter
class, never a new branch in the request path. No provider host, key name,
or catalogue URL literal belongs anywhere else under `ai_router/`.

## 4. Security

Never commit state, activation receipts, catalogues, logs, keys or bearer
tokens. Never log request or tool content. Loopback only; the path token is
per-install. Subscription headers never accompany OpenRouter requests.

## 4a. Popup style

Every dialog the router shows a person (the update notice, the first-run key
window, and anything added later) follows one style:

- the title `SCG Router` and the bundled product icon
  `packaging/assets/router-icon.png` -- no platform default icon;
- plain language for non-technical users: say "key", "ChatGPT subscription",
  "restart"; never name router internals (`nonce`, `loopback`, `catalogue`,
  `owner-only file`, process or port detail);
- client-aware: name the client(s) this install serves (Codex, Claude Code,
  both) in the wording and the action -- never tell a Claude-only user to
  reopen Codex, and never offer a restart the machine cannot perform;
- at most two actions, and the safe one is always available ("Later" or
  "Cancel" never disappears);
- best-effort: a missing dialog tool falls back to the loopback page and no
  popup ever blocks or fails an install.

`tests/test_popup_style.py` pins the shared title, icon asset and vocabulary
across the platforms, so a new dialog cannot drift from this style.

## 4b. Local watchlist

In the primary checkout, `TO MONITOR/TOMONITOR.md` is the local, gitignored
watchlist of unusual events analysed but not yet actionable: one index plus one
file per issue type, each entry carrying the symptom, the evidence, the
conclusion and the trigger that reopens it. Read the matching type file before
re-investigating a recurring symptom, and add or update an entry when an event
is understood but not yet actionable. Keep entries in the primary checkout:
this local artifact sits outside the worktree discipline in section 2, so a
linked worktree has no folder to write to, and a fresh clone has neither the
folder nor the exclusion. It never carries keys, request content or tool
content.

## 5. Verification before commit

Run `python3.14 -m unittest discover -s tests -t .`,
`python3.14 -m compileall -q ai_router tools tests packaging`,
`python3.14 tools/check_source_limits.py` and
`python3.14 tools/check_policy_scans.py`, then the shared
`pre-commit-review` skill. Commit subjects use `<type>: <short summary>`
with type `feat`, `fix`, `refactor`, `test`, `chore` or `docs`.
Discover runs the fast core suite; installer tests are opt-in via
`SCG_RUN_INSTALLER_TESTS=1` (native CI runners cover them on scope).

### Bounded live regression probes

When a regression depends on real client or model behavior that offline tests
cannot prove, add a separately invoked live probe using synthetic task data.
Paid probes are permitted when necessary for authorized work. Keep the unit
suite offline; require hard caps on call count and token or cost spend, and
never add unbounded retries.

Use the cheapest suitable model and low reasoning effort where supported.
Prefer Luna, DeepSeek Flash or GLM Flash; use Sonnet at low effort when the
Anthropic-specific contract needs it. Resolve current IDs and supported effort
from the catalogue; expand model coverage only for a demonstrated need.
Record the client version, requested model and effort, served identity when
exposed, call count, and result. Reuse passing evidence for unchanged paths;
rerun only after a relevant change or failure. These probe defaults do not
change mandatory fixed-effort pre-commit reviewer routing or waive section 7's
compatibility checks.

## 6. Release rule

Every user-visible router change updates `CHANGELOG.md` and
`packaging/VERSION` (semver). Releases are cut with the full `v<VERSION>` tag
matching `packaging/VERSION`, then run the release
workflow. Plugin-only changes ride the plugin release train instead
(section 9); they never bump `packaging/VERSION` or trigger router tags.
New entries go under `## Unreleased` and move under the version heading when
the tag is cut; entries older than the current minor series move, unedited,
to `docs/changelog-archive.md`.

## 7. Compatibility rule

After any Codex desktop or Claude Code upgrade, run the paid probe from
`tools/probe_codex_runtime.py` on one OpenRouter model and one OpenAI model,
plus one OpenRouter model and one subscription model through a real Claude
Code session (see `docs/claude-code.md`), before publishing a release.
Record both client versions in `docs/compatibility.md`.

## 8. Model naming convention

Picker labels read `<Vendor>: <Model> <Version?>` (e.g. `Z.ai: GLM 5.3 Flash`).
`display_name` is stored fully qualified with a ` · <Provider label>` suffix
(` · OpenRouter` for the built-in external provider, from
`provider_defs.label_for`); the
prefix always equals the row's `vendor` field, with one redundant leading vendor
word dropped (`DeepSeek: DeepSeek V4 ...` becomes `DeepSeek: V4 ...`). The
roster pins exact upstream ids (`anthropic/claude-opus-5.5`,
`google/gemini-3.8-flash`), so a new version is a registry edit: add the new
pinned row and retire the superseded slug via `RETIRED_SLUGS`. Pinned rows keep
any version/snapshot token verbatim. A tilde alias row is only added when the
roster deliberately tracks upstream, and it tracks with `Latest`, never a pinned
snapshot; dated snapshots merge into a tracking alias only when upstream
actually serves the `~` id (never invent one). `models add` and `live_refresh`
must produce conforming rows; the registry naming test enforces it.

## 9. Agent plugins

This repo also hosts the `scg-agent-plugins` marketplace (`scg-review`,
`scg-subagents`, `scg-prototypes`, `scg-finance`). Author under
`plugins/<name>`; installed plugin caches are delivery copies. The root
`scg-openrouter` plugin stays outside the marketplace. Keep the marketplace
name and plugin names stable; release via `develop` to `main`, consumers
track branch `main`.

- Every plugin works in Codex and Claude Code: ship both `.codex-plugin`
  and `.claude-plugin` manifests at the same version, keep skill content
  client-agnostic, and read system state through whichever MCP or connector
  tools the active client exposes.
- Every plugin ships automatic updates: bundle the shared `updater.py` and
  `scheduling.py` byte-identical, link every skill to the shared update
  guide, and support macOS, Linux and Windows through the one shared native
  schedule. A pull alone is never setup.
- Release a plugin by bumping both manifests' version and adding a
  `plugins/CHANGELOG.md` entry; validate with the plugin-creator validator
  and the plugin test modules.
- Integrate plugin fixes through `develop` first. If `develop` contains
  unrelated unreleased router changes, reuse the owned worktree for a release
  branch based on current `main` and cherry-pick only the reviewed plugin
  commits. The release PR targets `main`; its diff may contain only `plugins/`,
  directly related plugin verification tests, and directly related
  plugin-release instructions in this file. Verify the complete diff against
  current `main`, run all required checks and reviews on that exact candidate,
  and use the normal PR gates. Do not include router code, `packaging/VERSION`,
  router tags, or release-workflow changes. Reconcile
  the release into `develop` afterwards without discarding either side.
