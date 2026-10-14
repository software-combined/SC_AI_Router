# Troubleshooting

Symptom-first remedies for a machine that runs the router. Every command here
is safe to run and prints no secrets. Replace the home path if you installed
elsewhere; the default is `~/.codex/mixed-model-router`.

```sh
python3.14 packaging/install.py --preflight --home ~/.codex/mixed-model-router
python3.14 packaging/install.py --status --home ~/.codex/mixed-model-router
python3.14 packaging/install.py --doctor --home ~/.codex/mixed-model-router
```

Start with `--doctor`: it reports one row per component (runtime, install,
service, each provider's key, the picker catalogue, the scheduled command and
update recency) and prints a `Fix:` line for every WARN or FAIL.

## The installer stops before it downloads anything

Check that the machine can reach the feed origin for this channel
(`https://dist.softwarecombined.com/<channel>/latest.json`; `--status` names
the channel and the feed source, not the URL), including any proxy, then run
the same command again. A transient DNS or TLS failure is not sticky.

## An update keeps failing, or stops trying

After three failed attempts at one version the updater parks that version and
prints `parking <version> after 3 failed attempts; run the installer by hand to
retry`; later checks report `skipping <version>`. A parked version does not
affect the running router, which keeps serving the version it already has.

- Failed attempts are counted per version in the router state and the count is
  cleared by a successful install.
- `logs/update.log` records each activated install as one JSON line (`at`,
  `version`, `source`). The output of a failed attempt goes there too on macOS,
  and to the update service's journal on Linux:
  `journalctl --user -u codex-mixed-model-router-update.service`.
- Retry by hand: run `packaging/install.py --home <home>`.
- Move back: `packaging/install.py --home <home> --rollback --to <installed
  version>` (`--version <version>` stays as its older spelling).

## The router is not serving

- Health: `http://127.0.0.1:<port>/<token>/health`, with the port and token
  from `mixed-router-state.json`. Keep that URL private. A healthy answer is
  `status: ok` with the installed version.
- `--status` reports `service: serving`, `not serving` or `unknown`.
- Service state per platform:

```sh
# macOS
launchctl print gui/$(id -u)/com.local.codex-mixed-model-router
# Linux with a systemd user manager
systemctl --user status codex-mixed-model-router.service
# Windows (PowerShell)
schtasks /Query /TN CodexMixedModelRouter /V /FO LIST
```

- Logs live under `logs/` in the router home. A file there is deleted 30 days
  after its last write, at each router start and scheduled update, apart from
  the three the running router writes, which keep their size caps.

## Codex does not show a model

Subscription installs use the router's `/models` response, which combines the
ChatGPT subscription catalogue with the approved OpenRouter registry. Codex
requests it immediately and on its own refresh cadence. Desktop picker repaint
timing is not yet proven, so quit and reopen Codex when a known addition is
not visible.

If only the built-in models appear while router health is good, check discovery
with `python3.14 tools/probe_model_discovery.py --codex <client-executable> --installed`.
This reads the model list through that client without making an inference call.
Release 0.6.117 rejected valid native visibility and upgrade metadata, causing
this fallback; update to the corrected release instead of disabling discovery.

- `--static-catalogue` uses `mixed-models.json` instead and requires a Codex
  restart after an install or catalogue change.
- A model outside this machine's policy is not listed; `--status` shows the
  router state, and the request log records a refusal rather than serving it.
- A ChatGPT subscription row is always listed, exhausted or not, and its
  OpenRouter twin (`openai/<slug>`, labelled `· OpenRouter`) is listed beside
  it: picking the twin bills OpenRouter deliberately when the subscription
  cannot run. An exhausted subscription row answers the refusal message that
  names the model and points at a routed row.

## Claude Code stopped using the router

`ANTHROPIC_BASE_URL` must point at the loopback URL with the path token;
`ANTHROPIC_AUTH_TOKEN` and `ANTHROPIC_API_KEY` must stay unset, because either
one replaces the subscription credential the router forwards.

- Re-attach: `packaging/install.py --home <home> --clients claude` (or `both`).
- Detach everything: `packaging/install.py --home <home> --uninstall`.
- Desktop third-party profile: add `--desktop` when attaching.

If Claude Code routes but loads every MCP tool on every turn, deferred tool
loading is off. `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS`, set anywhere in
reach, forces it off and no value overrides it: the attach refuses while it is
set and `python3.14 packaging/install.py --doctor` names the file carrying it.
Remove the variable, restart Claude Code, and check that `ENABLE_TOOL_SEARCH`
is `true` in the client's `env` block. See `docs/claude-code.md`.

## A request fails

| Code | Meaning |
|---|---|
| 400 | Model id, payload or local key configuration is invalid |
| 403 | Missing or wrong path token, or a browser-originated request was refused |
| 409 | The provider cannot serve this request, for example an unsupported reasoning level; the message names the allowed levels |
| 503 with `Retry-After` | Not served: the router is draining for an update (`SERVER_DRAINING`) or mapped an upstream 429 (`UPSTREAM_RATE_LIMITED`); retry after the delay. A refused subscription turn names the model and the subscription: retry shortly, or select a routed model |

`BODY_TOO_LARGE` (`400`) means the request exceeds the router's local 256 MiB
ceiling on sent or decompressed bytes. Native history and images are preserved;
external Responses can shorten old content before sending it. Reduce large
attachments or use the client's compaction command before retrying. The work
on disk is untouched. `logs/router.jsonl` records sizes and carried classes in
`turn_refused`; `turn_trimmed` records any external content reduction.
`OVERSIZE_BUSY` (`503`) means a large turn could not reserve space in the shared
1 GiB request budget after waiting up to 60 seconds. Retry shortly; smaller
requests can still proceed.

## The key is missing or was revoked

A fresh install opens the native key window by itself when the installed
service has no key; the agent must never handle the key. If no window
appears, re-run the installer with `--setup`: it restarts the current release
with a fresh setup link and opens the window, without re-extracting the
release. A key exported in the invoking shell is not passed to the installed
service, so the installer collects a key file instead. Scheduled `--update`
runs and manual `--check-update` runs never pop the window; the next request
opens it instead. `ROUTER_NO_KEY_WINDOW=1` suppresses only the dialog for
unattended installs.

On Codex, a missing or rejected key opens the native key window on the next
request; on a host with no dialog tool the loopback setup page opens instead.
A rejected key is only detected on that path, so a Claude Code (Messages)
request reports the upstream error instead of opening a window. Never paste a
key into chat, a ticket or a logged terminal. The plain `--status` line covers
the default provider and is one of `usable`, `present` or `missing`;
`--status --json` reports every provider. Neither prints the key.

## What to send IT

`--doctor --json` and `--status --json` output. They carry no tokens, keys,
URLs or config bodies. For anything deeper run `--support` and send the
bundle it names: booleans, counts, versions and timestamps only. Never send
`mixed-router-state.json`, `activation.json` or the raw `logs/` files.
