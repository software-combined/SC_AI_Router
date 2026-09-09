# SC_OpenRouter_adapter Agent Instructions

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

## 3. Source limits

Modules 250 lines soft / 400 hard, entrypoints and tools 400/700, tests
300/500. Checked by `python3.14 tools/check_source_limits.py`. Keep the
router and provider modules small; a third provider is a new class, never a
new branch in the request path.

## 4. Security

Never commit state, activation receipts, catalogues, logs, keys or bearer
tokens. Never log request or tool content. Loopback only; the path token is
per-install. Subscription headers never accompany OpenRouter requests.

## 5. Verification before commit

Run `python3.14 -m unittest discover -s tests -t .`,
`python3.14 -m compileall -q codex_router tools tests`, and
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
`display_name` is stored fully qualified with the ` · OpenRouter` suffix; the
prefix always equals the row's `vendor` field, with one redundant leading vendor
word dropped (`DeepSeek: DeepSeek V4 ...` becomes `DeepSeek: V4 ...`). Tilde
alias rows track with `Latest`, never a pinned snapshot; pinned rows keep any
version/snapshot token verbatim, and dated snapshots merge into a tracking alias
only when upstream actually serves the `~` id (never invent one). `models add`
and `live_refresh` must produce conforming rows; the registry naming test enforces it.
