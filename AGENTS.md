# SC Router agent instructions

## 1. Purpose

Local loopback router that keeps ChatGPT subscription traffic on OpenAI and
Claude subscription traffic on Anthropic, and routes approved OpenRouter
models with a separate key. Runtime Python 3.14+, stdlib only, no
third-party dependencies, no network calls in tests.

## 2. Worktree discipline

One writable worktree per agent session; never edit the primary checkout.
Never run `git reset --hard` or `git checkout --` without explicit approval.
Record worktree ownership (path, branch, owning task, integration target) and
reuse the same worktree for follow-ups. Clean up after verified integration.

Base every branch on `develop` and target every PR at `develop`,
except release PRs from `develop` to `main`. Never work off or push
to `main`.

## 2a. Architecture

`docs/architecture.md` owns domain responsibilities and allowed dependency
direction. New modules go where that map says; transitional owners name the
plan that will move them.

## 3. Source limits

Modules 250 lines soft / 400 hard, entrypoints and tools 400/700, tests
300/500. Checked by `python3.14 tools/check_source_limits.py`. Keep the
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

## 5. Verification before commit

Run `python3.14 -m unittest discover -s tests -t .`,
`python3.14 -m compileall -q ai_router tools tests packaging`, and
`python3.14 tools/check_source_limits.py`, then the shared
`pre-commit-review` skill. Commit subjects use `<type>: <short summary>`
with type `feat`, `fix`, `refactor`, `test`, `chore` or `docs`.

## 6. Release rule

Every user-visible change updates `CHANGELOG.md` and `packaging/VERSION`
(semver). Releases are cut by tag `v<VERSION>` and the release workflow.

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
roster pins exact upstream ids (`anthropic/claude-opus-5`,
`google/gemini-3.8-flash`), so a new version is a registry edit: add the new
pinned row and retire the superseded slug via `RETIRED_SLUGS`. Pinned rows keep
any version/snapshot token verbatim. A tilde alias row is only added when the
roster deliberately tracks upstream, and it tracks with `Latest`, never a pinned
snapshot; dated snapshots merge into a tracking alias only when upstream
actually serves the `~` id (never invent one). `models add` and `live_refresh`
must produce conforming rows; the registry naming test enforces it.
