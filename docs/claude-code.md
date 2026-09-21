# Claude Code via the local router (Preview)

The router speaks the Anthropic Messages API alongside the Codex
backend, with the same billing split: registry slugs owned by an external
provider bill that provider's key, everything else passes through to the
Claude subscription untouched. A provider definition
(`ai_router/provider_defs.py`) says which external providers speak
Messages; one without a `messages_path` is refused here with a clear 400
and stays a Codex-only model.

## Setup

For the **Claude desktop app**, use the [desktop setup below](#claude-desktop-app).
The terminal settings in this section do not configure the app's connection.

Point Claude Code at the loopback router with the path token in the URL,
mirroring the Codex base URL. With `port` and `token` from
`mixed-router-state.json` (do not share that URL):

```sh
export ANTHROPIC_BASE_URL="http://127.0.0.1:<port>/<token>/"
```

Set only the base URL. Never set `ANTHROPIC_API_KEY` or
`ANTHROPIC_AUTH_TOKEN`: either would override the subscription bearer
and break subscription passthrough. Unset the variable to return to
direct routing.

To list the router models in the terminal client's `/model` picker, also set:

```sh
export CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=true
```

Claude Code 2.1.x fetches `GET <base>/v1/models` on startup and caches
it at `~/.claude/cache/gateway-models.json`; entries whose `id`
contains `claude` or `anthropic` appear as `From gateway` options.
Restart Claude Code after changing the base URL so it refetches.
`ANTHROPIC_AUTH_TOKEN` must stay unset for the fetch: when it is set
the CLI sends it as the listing credential, and the router answers the
listing from its local registry without needing any credential.

## Choosing a model

Set `ANTHROPIC_MODEL` to a listing id for OpenRouter billing, or leave
the default Claude model for subscription billing. Listing ids mirror
the Codex registry: stable `claude/scg/...` route IDs plus the bare
`anthropic/...` Claude IDs. Copy the ID from discovery; the picker shows
the real vendor, model and billing label. Older `claude/<vendor>/<name>`
aliases still work in saved sessions and commands. The router resolves the
ID back to the registry slug before routing, so billing follows the
registry row. A registry slug also routes directly. Reasoning is
governed by each call's `max_tokens` and `thinking` fields, which
travel untouched. Start a fresh session when switching providers.

## Attachment contract

The installer owns exactly two `env` keys in `~/.claude/settings.json`
(`ANTHROPIC_BASE_URL` and `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY`) and
restores the previous values on detach. `ANTHROPIC_AUTH_TOKEN` and
`ANTHROPIC_API_KEY` must stay unset: either one overrides the subscription
bearer, so subscription requests would stop reaching Anthropic with the
client's own login and the listing fetch would present the wrong credential.
The attach records the listing ids, display names and tiers it was told
about, and `--doctor` compares that snapshot with the live `GET /v1/models`;
a change shows up as `drift` with the added and removed ids, and `unknown`
when the router is not answering. The comparison is by listing id, so a
display-name or tier edit alone does not report drift. Restart Claude Code
after a listing change so the client refetches.

A launcher that only routes when the user types a different command (or a
wrapper script) was considered and rejected: an alias breaks a plain `claude`
invocation, and the external-router pattern of setting
`ANTHROPIC_AUTH_TOKEN` to a router secret is exactly what breaks subscription
passthrough, which requires the client's own credential to reach the router
untouched. The settings merge writes only owned keys and refuses a
hand-edited conflict instead of overwriting it.

## Behaviour and limits

- OpenRouter-bound bodies are forwarded byte-identical to OpenRouter's
  Anthropic-compatible endpoint, so thinking blocks, `tool_use` IDs and
  `cache_control` keep full fidelity. `count_tokens` follows the same
  split. `GET /v1/models` answers `{data: [{id, display_name, anthropic_family_tier}]}` from
  the local registry without touching the network; unknown paths answer
  404.
- Subscription requests forward the client's `Authorization` or
  `x-api-key` plus version and beta headers, minus hop headers. The
  router key never accompanies them. In `none` mode the passthrough is
  refused; OpenRouter models still serve.
- The Claude path is pure passthrough, so `/health` `served_models`
  does not track it and no compaction endpoint exists for it.
- A routed row inherits whatever tools the client has loaded. Claude
  Code adds every claude.ai connector MCP tool to its request once the
  first turn has loaded them; on a machine with hundreds of connector
  tools that tool list alone can exceed the model's context window, and
  upstream refuses the turn with a context error. Exclude them for a
  routed session (`--strict-mcp-config --mcp-config '{"mcpServers": {}}'`)
  when the tool list does not fit the row.
- Live verification, 2026-09-17: a real Claude Code session
  (`2.1.223`) completed a Read-tool round trip through the router on
  `anthropic/claude-haiku-4.5` with those connector servers excluded;
  the version and the run are recorded in `docs/compatibility.md`.

## Claude desktop app

With the router already installed, run this once from the router checkout:

```sh
python3.14 packaging/install.py --desktop
```

Quit and reopen Claude, choose **Code**, select your folder, then choose a
model and type your task. No key copying or Developer-menu configuration is
needed. Attachment also runs when there is no newer router release.

On macOS, desktop setup also installs **Switch Claude** in your user's
Applications folder. Open it from Spotlight or Finder to switch between your
Claude subscription and OpenRouter. It names the destination and restarts
Claude after you choose **Switch**. **Cancel** leaves the current selection
alone. If Claude stays open or you cancel its quit prompt, nothing changes.
Setup and updates preserve the selected mode. A standalone Claude Code
terminal installation is not required for the desktop app.
If the installed router predates the shortcut, setup keeps Claude connected
and asks for a router update before adding **Switch Claude**.

Every model labelled **OpenRouter** uses the OpenRouter key. The gateway
profile has its own sessions; your signed-in Claude profile and its existing
sessions remain separate. The desktop adapter's `detach` operation restores
the original profile settings without removing the router. Full router
uninstallation also detaches Codex and the terminal client.

Switching keeps each profile's conversations and settings in place. It does
not sign out, move conversations, detach the router or change Codex. The
shortcut checks that Claude still uses this router's saved configuration;
run setup again if that configuration has changed. An organization policy
that prevents subscription sign-in also prevents the shortcut from switching.
The shortcut currently supports macOS only.

The desktop app (verified against 2.2553.1) keeps first-party and
third-party mode in separate profiles (`.../Claude` and `.../Claude-3p`).
Pointing the third-party profile at the loopback router lists every
approved Messages-compatible registry row. The app filters non-Anthropic
vendor words from IDs even when a valid `anthropic_family_tier` is present.
The router therefore gives non-Anthropic entries stable route IDs derived
from the registry slug, retaining the actual name in `display_name`.
The projected tier remains `sonnet` for those rows, and each Anthropic row
keeps its own tier. These are client discovery fields, not upstream model
identities or capability claims. No stored registry field is added. Attach with
`packaging/install.py --desktop` (refuses when `claude_mode` is `none`);
service-only install and uninstall detach again. The first-party
profile's credentials are never touched, so native sign-in survives, and
a detach returns the app to first-party mode.

Coexistence limit: third-party mode replaces the whole picker with
gateway rows. Native subscription models are not in it, and the profile
starts empty of first-party preferences, trusted folders, and
org-served connectors (those resolve against org identity, not local
files, so the installer does not copy them). Local stdio or remote MCP
declarations can be owned the same way when they exist; on a profile
with none, nothing is carried. This is a client limitation, not a router
defect; reaching the app's hybrid selector would need a bootstrap server
and org changes, which remain out of scope.

Effort control: the desktop keys its thinking-effort options off native
model names, so gateway rows show no effort picker on this client
version. Any `thinking` the app sends still travels byte-identical
through the router. Effort choice for gateway models stays a CLI
(`ANTHROPIC_MODEL` plus per-call fields) and Codex picker affair until
the client offers otherwise.

### Bounded desktop verification

`tools/probe_claude_desktop.py --execute --endpoint-file <private-file>` starts
a temporary loopback connection for a synthetic Code task. It accepts only
DeepSeek V4.1 Flash, with four requests, 2,048 output tokens and 256 KiB of input
per request. It writes the connection URL to a new owner-only file and logs
only counters, status and served model identity. It does not edit app settings.
Temporarily select that connection in an isolated gateway profile, read a
synthetic file once, and restore the normal router connection before stopping
the probe. A startup check for another model is refused by this test guard.
