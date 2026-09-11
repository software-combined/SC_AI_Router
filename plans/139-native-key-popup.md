# Plan 139: Native popup for the OpenRouter key

> Owner-approved 2026-09-11. Replaces the browser-launched key page as the
> primary first-run surface; the loopback page stays as the no-GUI fallback.

## Status and first proof

- Priority P2; effort M; risk MEDIUM; category dx/security-surface.
- First proof: `install.py --setup` on macOS shows a native window that asks
  for the key, the ChatGPT-subscription choice and the starter; the stored
  key lands in `openrouter.key` (mode 600) and the popup confirms it with the
  remaining credit. On a host without a dialog tool the loopback page opens
  and the link is printed.

## Why this matters

The first-run flow opened a browser page at
`http://127.0.0.1:<port>/<token>/setup/<nonce>`. Operators read that as a web
page appearing out of nowhere, and the browser is a second surface that has
to be trusted with the key. A native window keeps the same single-use nonce
route — validation, owner-only storage, starter install and nonce closure all
stay in `ai_router.setup` — while removing the browser from the happy path.

## Scope

- `ai_router/key_dialog.py` (new): per-platform dialog argv, output parsing,
  cancel/error handling, and plain native messages.
- `ai_router/key_prompt.py` (new): the flow (collect → submit → confirm →
  retry), the `open_window` helper for the router, the browser fallback and
  the `python -m ai_router.key_prompt <url>` entry point used by the
  installer.
- `ai_router/setup_page.py` (new): the HTML page moved out of `setup.py`, which
  is at its source-limit ceiling.
- `ai_router/setup.py`: `handle_setup_json` plus the shared `_submit` core;
  `serve` answers a POST carrying `Accept: application/json`; `open_key_window`
  spawns the popup on a worker thread with the browser as its fallback.
- `packaging/install.py`: `--setup` spawns the prompt child instead of
  `webbrowser.open`.
- `packaging/notice.py`: `ROUTER_NO_NOTICE=1` opt-out; `tests/test_systemd_runtime.py`
  sets it so the suite no longer spawns real dialogs.
- Popup style rule (`AGENTS.md` 4a): every dialog carries the title
  `SCG Router`, the bundled product icon and plain language, with the safe
  action always available; `tests/test_popup_style.py` pins it across the
  update notice and the key window.

**Out of scope**: the Claude Desktop gateway setup, key rotation semantics
(unchanged), and any change to where the key is stored or read.

## Interfaces

- `key_dialog.tool(platform_name=None, which=None) -> path|None`;
  `key_dialog.collect(tool_path, platform_name=None, run=None) -> {'key','mode','profile'}|None`;
  `key_dialog.message(tool_path, text, ...)`.
- `key_prompt.submit(url, fields, opener=None) -> (status, payload)`;
  `key_prompt.run_window(...) -> 0 stored, 2 cancelled, 3 no GUI, 1 refused`;
  `key_prompt.open_window(url, thread=False, ...) -> bool`.
- Setup route: `POST /<token>/setup/<nonce>` with
  `Accept: application/json` returns `{"ok": true, "label", "limit", "usage",
  "mode", "starter"}` or `{"ok": false, "error"}`; the HTML path is unchanged.
- Security: the key never enters argv, the environment, a file or a log before
  the POST; the URL is printed only on a TTY.

## Verification

- Focused: `python3.14 -m unittest tests.test_key_prompt tests.test_setup
  tests.test_setup_agents tests.test_install_config tests.test_notice
  tests.test_notice_delivery tests.test_systemd_runtime`.
- Full: `python3.14 -m unittest discover -s tests -t .`, `compileall`,
  `python3.14 -m ruff check --select F401,F811 ai_router packaging tools tests`,
  `python3.14 tools/check_source_limits.py`, then the shared pre-commit review.
- Live macOS: one real popup run; Windows and Linux remain owner-gated machine
  acceptance.
