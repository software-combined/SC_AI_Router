# Troubleshooting

Symptom-first remedies for a machine that runs the router. Every command here
is safe to run and prints no secrets. Replace the home path if you installed
elsewhere; the default is `~/.codex/mixed-model-router`.

```sh
python3.14 packaging/install.py --preflight --home ~/.codex/mixed-model-router
python3.14 packaging/install.py --status --home ~/.codex/mixed-model-router
```

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
- Move back: `packaging/install.py --home <home> --version <installed version>`.

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

- Logs live under `logs/` in the router home.

## Codex does not show the OpenRouter models

Codex reads its catalogue once, at startup (verified 2026-09-12 against
codex-cli 0.153.4: rewriting `model_catalog_json` while the client runs does
not change the model list). After an install, an update or a catalogue change,
quit and reopen Codex.

- The catalogue Codex reads is `mixed-models.json` in the router home.
- A model outside this machine's policy is not listed; `--status` shows the
  router state, and the request log records a refusal rather than serving it.

## Claude Code stopped using the router

`ANTHROPIC_BASE_URL` must point at the loopback URL with the path token;
`ANTHROPIC_AUTH_TOKEN` and `ANTHROPIC_API_KEY` must stay unset, because either
one replaces the subscription credential the router forwards.

- Re-attach: `packaging/install.py --home <home> --clients claude` (or `both`).
- Detach everything: `packaging/install.py --home <home> --uninstall`.
- Desktop third-party profile: add `--desktop` when attaching.

## A request fails

| Code | Meaning |
|---|---|
| 400 | Model id, payload or local key configuration is invalid |
| 403 | Missing or wrong path token, or a browser-originated request was refused |
| 409 | The provider cannot serve this request, for example an unsupported reasoning level; the message names the allowed levels |
| 503 with `Retry-After` | Not served: the router is draining for an update (`SERVER_DRAINING`) or mapped an upstream 429 (`UPSTREAM_RATE_LIMITED`); retry after the delay |

## The key is missing or was revoked

A fresh install opens the native key window by itself when the installed
service has no key; the agent must never handle the key. If no window
appears, re-run the installer with `--setup`: it restarts the current release
with a fresh setup link and opens the window, without re-extracting the
release. A key exported in the invoking shell is not passed to the installed
service, so the installer collects a key file instead. Scheduled and manual
`--check-update` runs never pop the window; the next request opens it
instead. `ROUTER_NO_KEY_WINDOW=1` suppresses only the dialog for unattended
installs.

On Codex, a missing or rejected key opens the native key window on the next
request; on a host with no dialog tool the loopback setup page opens instead.
A rejected key is only detected on that path, so a Claude Code (Messages)
request reports the upstream error instead of opening a window. Never paste a
key into chat, a ticket or a logged terminal. The plain `--status` line covers
the default provider and is one of `usable`, `present` or `missing`;
`--status --json` reports every provider. Neither prints the key.

## What to send IT

`--status --json` output only. It carries no tokens, keys, URLs or config
bodies. Do not send `mixed-router-state.json` or anything from `logs/`.
