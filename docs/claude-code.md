# Claude Code via the local router (Preview)

Claude Code can talk to the local router instead of Anthropic directly. It
keeps your Claude subscription sign-in, and the router's approved OpenRouter
models appear next to your subscription models in the model picker. A model
that belongs to an external provider is billed to the OpenRouter key;
everything else passes through to your Claude subscription untouched.

## Setup

The desktop app and the terminal client are separate connections and are set
up separately. This section covers the terminal (`claude`); for the app, use
[Claude desktop app](#claude-desktop-app) below.

### Set it up

Run the installer. It asks which assistant you use and where, and attaches
only what you answer:

```sh
python3.14 packaging/install.py --choose-clients
```

Choose **Claude**, then **Terminal** for the terminal alone or **Both** to
connect the app as well. The same choice without the questions, and the other
Claude options:

```sh
python3.14 packaging/install.py --clients claude            # terminal only
python3.14 packaging/install.py --clients none --desktop    # Claude app only
python3.14 packaging/install.py --clients claude --desktop  # terminal and app
```

Then quit and restart Claude Code. That is the whole setup: the installer
writes the two settings it owns in `~/.claude/settings.json`, keeps your
existing subscription sign-in, and records what it changed so the same
installer can undo it. Attaching is additive, so nothing you did not ask for
is removed, and cancelling a question changes nothing. The one thing it will
not do is overwrite a setting you edited by hand: it refuses and tells you to
fix that value first.

On a machine installed from the bootstrap there is no checkout to run from, so
download the current bootstrap first (an older download rejects the new flag),
or run the installer already in the router home:

```sh
# beta hosts: download the current bootstrap, then ask it to attach a client
curl -fsSL https://dist.softwarecombined.com/bootstrap/bootstrap.sh -o bootstrap.sh
sh bootstrap.sh --channel=beta --choose-clients
# a stable host omits --channel=beta

# or run the installer already in the router home with its pinned interpreter
# (use $ROUTER_HOME instead of $HOME if the router was installed elsewhere)
"$HOME/.codex/mixed-model-router/runtime/python/bin/python3.14" "$HOME/.codex/mixed-model-router/releases/$(cat "$HOME/.codex/mixed-model-router/current")/packaging/install.py" --choose-clients
```

### Check it worked

- `claude` starts normally, and `/status` still shows your Claude
  subscription rather than an API key.
- `/model` lists the router's rows alongside your subscription models. A row
  named with its vendor and `· OpenRouter` is billed to the OpenRouter key;
  the plain Claude models use your subscription.
- `python3.14 packaging/install.py --doctor` reports the `claude` row as
  `match` (`absent` when nothing is attached).

Start a fresh session when you switch between a subscription model and a
routed one.

### Set it up by hand

If you would rather not use the installer, point the client at the router
yourself, using the `port` and `token` from `mixed-router-state.json` in the
router home (do not share that URL):

```sh
export ANTHROPIC_BASE_URL="http://127.0.0.1:<port>/<token>/"
export CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=true
```

Set only those two. Never set `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN`:
either one overrides the subscription bearer and breaks subscription
passthrough. Unset `ANTHROPIC_BASE_URL` to return to direct routing, and
restart Claude Code after changing it.

## Reference

### How discovery works

With `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=true` set, the client lists
the router models in its `/model` picker. Claude Code 2.1.x fetches
`GET <base>/v1/models` on startup and caches
it at `~/.claude/cache/gateway-models.json`; entries whose `id`
contains `claude` or `anthropic` appear as `From gateway` options.
Restart Claude Code after changing the base URL so it refetches.
`ANTHROPIC_AUTH_TOKEN` must stay unset for the fetch: when it is set
the CLI sends it as the listing credential, and the router answers the
listing from its local registry without needing any credential.

## Choosing a model

Pick the model in `/model`, or set `ANTHROPIC_MODEL` to its listing id. What
you see looks like `Z.ai: GLM 5.3 Flash · OpenRouter` for a routed model and
`Claude Sonnet 5` for a subscription one: the vendor and the billing label are
the row's real identity, and the id underneath mirrors the Codex registry
(`claude/scg/...` route IDs and the bare `anthropic/...` Claude IDs). Copy the
id from discovery rather than typing one; older `claude/<vendor>/<name>` aliases
still work in saved sessions and commands. The router resolves the id back to
the registry row before routing, so billing follows the row, and a registry
slug routes directly too. Reasoning is governed by each call's `max_tokens`
and `thinking` fields, which travel untouched. Start a fresh session when
switching providers.

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
when the receipt is unreadable or the router is not answering. The comparison is by listing id, so a
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

- OpenRouter-bound requests reach OpenRouter's Anthropic-compatible
  endpoint unchanged, so thinking blocks, `tool_use` IDs and
  `cache_control` keep full fidelity, and `count_tokens` follows the same
  split. Two shapes Claude Code 2.1.223 cannot survive are repaired in
  flight and every other byte is left alone. The `system` block carrying
  the client's own `x-anthropic-billing-header` line is dropped, because
  `anthropic/claude-fable-5.1` refuses any turn that carries it with HTTP
  400 and the line only matters to Anthropic's billing, which this route
  does not use. A thinking block that arrives with a signature but no
  thinking is dropped from the stream, because Claude Code throws away the
  whole answer when one follows it. The subscription route keeps both.
  `GET /v1/models` answers `{data: [{id, display_name, anthropic_family_tier}]}` from
  the local registry without touching the network; unknown paths answer
  404.
- Subscription requests forward the client's `Authorization` or
  `x-api-key` plus version and beta headers, minus hop headers. The
  router key never accompanies them. In `none` mode the passthrough is
  refused; OpenRouter models still serve.
- The Claude path relays the upstream stream, so `/health` `served_models`
  does not track it and no compaction endpoint exists for it.
- A routed row inherits whatever tools the client has loaded. Claude
  Code adds every claude.ai connector MCP tool to its request once the
  first turn has loaded them; on a machine with hundreds of connector
  tools that tool list alone can exceed the model's context window, and
  upstream refuses the turn with a context error. Exclude them for a
  routed session (`--strict-mcp-config --mcp-config '{"mcpServers": {}}'`)
  when the tool list does not fit the row.
- Live verification, 2026-09-21: Claude Code `2.1.223` completed a
  Read-tool round trip on all 18 advertised rows plus a subscription
  model, with those connector servers excluded. Before the two repairs
  above, `anthropic/claude-fable-5.1` refused every turn and
  `google/gemini-3.8-flash` returned an empty answer after its tool
  call. The versions, the failures and the run are recorded in
  `docs/compatibility.md`.

### Bounded Claude Code verification

`tools/probe_claude_code.py --home <router-home>` drives the installed
`claude` binary against a running router, one Read-tool round trip per
advertised row, and reports the rows that failed. Each row gets a synthetic
marker file named for that model, connector MCP servers are excluded so the
request stays at the client's own tool set, and a row is never retried. The
probe leaves the caller's Claude settings alone: it points a disposable
settings file at the router and never prints the loopback URL. Pass
`--models` to narrow it, `--max-rows` to raise the cap, or `--json` for a
machine-readable report. Point it at an isolated candidate home to check a
build before it is installed.

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
