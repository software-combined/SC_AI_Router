# SC AI Router agent instructions

## 1. Purpose

These instructions apply to contributors and coding agents working in this
repository. See [README.md](README.md) for setup and supported clients.

The router keeps ChatGPT subscription traffic on OpenAI and Claude subscription
traffic on Anthropic. External providers use separate credentials. The runtime
requires Python 3.14+ and the standard library only. Keep the unit suite offline;
run live probes separately under section 5.

## 2. Worktree discipline

One writable worktree per agent session; never edit the primary checkout.
Never run `git reset --hard` or `git checkout --` without explicit approval.
Record worktree ownership (path, branch, owning task, integration target) and
reuse the same worktree for follow-ups. Clean up after verified integration.

Base every branch on `development` and target every PR at `development`,
except release PRs from `development` to `main` and the scoped plugin release
procedure in section 9. Never push directly to `main`.

## 2a. Architecture

[docs/architecture.md](docs/architecture.md) defines module responsibilities and
allowed dependency direction. Place new modules within those boundaries and
update the map when responsibilities change.

## 3. Source limits

Modules have a soft limit of 250 lines and a hard limit of 400. Entrypoints and
tools use 400/700; tests use 300/500. Check these with
`python3.14 tools/check_source_limits.py`. A file above
the soft cap needs a baseline entry, which is a ceiling: the file may shrink
freely and may not grow past the recorded count. Remove the entry once the
file is back under the cap. Keep router and provider modules small.
An upstream is one entry in
`ai_router/provider_defs.py` (host, endpoint prefixes, key location,
catalogue, failure dialect) consumed by adapter classes parameterized with
that definition; a provider with a different wire format is a new adapter
class, never a new branch in the request path. No provider host, key name,
or catalogue URL literal belongs anywhere else under `ai_router/`.

## 4. Security

Never commit state, activation receipts, catalogues, logs, keys or bearer
tokens. Never log request or tool content. Bind only to loopback addresses;
the path token is unique to each installation. Never send subscription headers
to external providers.

## 4a. Popup style

Every dialog the router shows a person (the update notice, the first-run key
window, and anything added later) follows one style:

- the title `SCG Router` and the bundled product icon
  `packaging/assets/router-icon.png`; never use a platform default icon;
- plain language for non-technical users: say "key", "ChatGPT subscription",
  "restart"; never name router internals (`nonce`, `loopback`, `catalogue`,
  `owner-only file`, process or port detail);
- client-aware: name the clients this install serves (Codex, Claude Code or
  both) in the wording and the action. Never tell a Claude-only user to
  reopen Codex, and never offer a restart the machine cannot perform;
- at most two actions, and the safe one is always available ("Later" or
  "Cancel" never disappears);
- dialog-only: a missing dialog tool leaves the notice pending and never
  opens a browser or sends a separate notification; no popup ever blocks or
  fails an install.

`tests/test_popup_style.py` pins the shared title, icon asset and vocabulary
across the platforms, so a new dialog cannot drift from this style.

## 5. Verification before commit

Run all four checks:

```sh
python3.14 -m unittest discover -s tests -t .
python3.14 -m compileall -q ai_router tools tests packaging
python3.14 tools/check_source_limits.py
python3.14 tools/check_policy_scans.py
```

Then run the installed
[pre-commit-review skill](plugins/scg-review/skills/pre-commit-review/SKILL.md).
Its [setup guide](plugins/scg-review/skills/review-setup/SKILL.md) covers the
required hooks and scanner. Commit subjects use `<type>: <short summary>` with
type `feat`, `fix`, `refactor`, `test`, `chore` or `docs`.

Test discovery runs the fast core suite. Installer tests are opt-in via
`SCG_RUN_INSTALLER_TESTS=1` (native CI runners cover them on scope for release
PRs into `main` and pushes to `main`). Development continuous integration (CI)
runs fast static checks; full remote regression runs for main acceptance.
Stable tags publish only an exact
main commit with a successful `Check` run; beta tags publish a commit that
`development` or `main` moved to (their first-parent line). Neither repeats those
acceptance checks.
Local pre-commit requirements above still apply.

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
change explicit pre-commit model or effort requirements or waive section 7's
compatibility checks.

## 6. Release rule

Every user-visible router change updates `CHANGELOG.md` and
`packaging/VERSION` (semver). Releases are cut with the full `v<VERSION>` tag
matching `packaging/VERSION`, then run the release workflow. Plugin-only changes
follow section 9; they never bump `packaging/VERSION` or trigger router tags.
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
`provider_defs.label_for`). The prefix always equals the row's `vendor` field,
with one redundant leading vendor
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

This repository hosts the `scg-agent-plugins` marketplace. See
[agent plugins](docs/agent-plugins.md) for installation and available plugins.
Author under `plugins/<name>`; installed plugin caches are delivery copies. The root
`scg-openrouter` plugin stays outside the marketplace. Keep the marketplace
name and plugin names stable. Release via `development` to `main`; the router
delivers the plugins without requiring users to run Git or marketplace commands.

Before coding or reviewing code, read the installed
[`scg-ponytail:ponytail` skill](plugins/scg-ponytail/skills/ponytail/SKILL.md)
in full. Resolve its current absolute path from the active client's
skill catalogue or plugin inventory; never pin a cache version. SCG Review
requires that same skill for its simplifier and all three lanes, and blocks
when the dependency is missing, disabled or unreadable. Ponytail owns solution
simplicity; this file and the review skill retain all verification gates.

- Every plugin works in Codex and Claude Code: ship both `.codex-plugin`
  and `.claude-plugin` manifests at the same version, keep skill content
  client-agnostic, and read system state through whichever MCP or connector
  tools the active client exposes.
- Router release bundles carry the plugin trees. Each install or scheduled
  update that lands a new release creates a local marketplace and registers it
  with the attached clients. Shipped plugins carry no updater of their own.
  Keep the retained `scripts/updater.py` and `scheduling.py` byte-identical
  across the plugins (tests pin it); the release bundle withholds them. Link
  every skill to its shared update guide.
- Release a plugin by bumping both manifests' version and adding a
  `plugins/CHANGELOG.md` entry. Validate Claude manifests and skills with
  `claude plugin validate --strict`, run the installed skill-creator's
  `scripts/quick_validate.py` for a new or changed skill, and run the plugin
  test modules for paired Codex/Claude manifests and package contracts.
  Require actual Codex installation and skill availability in a new session
  before claiming local delivery.
- Integrate plugin fixes through `development` first. If `development` contains
  unrelated unreleased router changes, reuse the owned worktree for a release
  branch based on current `main` and cherry-pick only the reviewed plugin
  commits. The release PR targets `main`; its diff may contain only `plugins/`,
  directly related plugin verification tests, marketplace registration in
  `.agents/plugins/marketplace.json`, the README's agent-plugin documentation,
  and directly related plugin-release instructions in this file.
  Verify the complete diff against current `main`, run all required checks and
  reviews on that exact candidate,
  and use the normal PR gates. Do not include router code, `packaging/VERSION`,
  router tags, or release-workflow changes. Reconcile
  the release into `development` afterwards without discarding either side.
