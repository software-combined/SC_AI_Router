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
writes the four settings it owns in `~/.claude/settings.json`, keeps your
existing subscription sign-in, and records what it changed so the same
installer can undo it. Attaching is additive, so nothing you did not ask for
is removed, and cancelling a question changes nothing. The one thing it will
not do is overwrite a setting you edited by hand: it refuses and tells you to
fix that value first.

### Deferred tool loading

Claude Code can hold MCP tool definitions back and load them only when they
are needed: the client keeps the catalogue, searches it locally through its
own `ToolSearch` tool, and sends the model only the tools a search released.
That is what keeps a session attached to a dozen connector servers inside a
model's context window instead of sending every schema on every turn.

It is off for any base URL that is not Anthropic's own host unless asked for,
so the installer sets `ENABLE_TOOL_SEARCH=true` and
`_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL=1` alongside the base URL and the
listing flag. Measured on Claude Code `2.1.223` with 700 synthetic MCP tools,
the first request of a session carries 727 tool definitions and 271 KB
without it, and 11 definitions and 100 KB with it; the deferred tools arrive
as the model asks for them.

Two things defeat it, and neither is something the installer can fix quietly:

- `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS`, set to anything truthy, turns the
  feature off and no value overrides it. The attach refuses while it is set in
  the settings `env` block or in the environment, and `--doctor` reports it
  with the file that carries it.
- A client that cannot search at all still loads every MCP tool. Exclude the
  connector servers for that session with
  `--strict-mcp-config --mcp-config '{"mcpServers": {}}'`.

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

The installer owns exactly four `env` keys in `~/.claude/settings.json`
(`ANTHROPIC_BASE_URL`, `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY`,
`ENABLE_TOOL_SEARCH` and `_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL`) and
restores the previous values on detach. A hand-edited value for any of the
four refuses the attach rather than being overwritten, and so does
`CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS`, which is refused rather than owned:
it forces deferred tool loading off and no value overrides it.
`ANTHROPIC_AUTH_TOKEN` and
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
  endpoint unchanged except for the repairs below, so thinking blocks and
  `cache_control` keep full fidelity, and `count_tokens` follows the same
  split. The router gives each streamed `tool_use` a fresh client-visible ID.
  DeepSeek V4.1 Flash otherwise returns `call_0` for every tool call; Claude
  Code collapses duplicate IDs and keeps only one earlier `tool_result`, which
  makes later reads look empty. The same repair applies to top-level tool calls
  in non-streaming JSON; nested tool-shaped input and unknown fields stay
  unchanged. The external route also hides Read's `pages` argument.
  Claude Code rejects a blank page range on an ordinary text file, and models
  that fill every advertised argument otherwise retry the same read. PDF page
  ranges stay available on the subscription route.
  The `system` block carrying
  the client's own `x-anthropic-billing-header` line is dropped, because
  `anthropic/claude-fable-5.1` refuses any turn that carries it with HTTP
  400 and the line only matters to Anthropic's billing, which this route
  does not use. A thinking block that arrives with a signature but no
  thinking is dropped from the stream, because Claude Code throws away the
  whole answer when one follows it. The subscription route keeps both shapes
  byte-identical.
  `GET /v1/models` answers `{data: [{id, display_name, anthropic_family_tier}]}` from
  the local registry without touching the network; unknown paths answer
  404.
- Subscription requests forward the client's `Authorization` or
  `x-api-key` plus version and beta headers, minus hop headers. The
  router key never accompanies them. In `none` mode the passthrough is
  refused; OpenRouter models still serve.
- The Claude path relays the upstream stream, so `/health` `served_models`
  does not track it and no compaction endpoint exists for it.
- A routed row inherits whatever tools the client has loaded, but with
  deferred loading on it inherits only the names until a search releases one.
  OpenRouter implements no part of Anthropic's deferred-tool protocol, so the
  external route rewrites that one shape before forwarding it rather than
  relying on it being tolerated: the
  `DeferredToolPlaceholder` and the server-side search tool entry go, the
  `defer_loading` flag goes (the released definition is already in the same
  request's tool list, so the model keeps the tool), and a `tool_reference`
  content block becomes the plain text naming the tool it stood for, which
  keeps every `tool_use` and `tool_result` paired. The subscription route is
  left byte-identical. Without deferred loading a long connector list can
  still exceed a row's context window, and the session workaround is
  `--strict-mcp-config --mcp-config '{"mcpServers": {}}'`.
- Live verification, 2026-09-21: Claude Code `2.1.223` completed a
  Read-tool round trip on all 18 advertised rows plus a subscription
  model, with those connector servers excluded. Before the two repairs
  above, `anthropic/claude-fable-5.1` refused every turn and
  `google/gemini-3.8-flash` returned an empty answer after its tool
  call. The versions, the failures and the run are recorded in
  `docs/compatibility.md`.
- Deferred-tool verification, 2026-09-22: a synthetic 700-tool MCP server,
  `z-ai/glm-5.3-flash`, Claude Code `2.1.223` and a router built from the
  working tree. Both legs passed; the deferred leg took three turns, meaning
  the search ran, the client released the tool and the model called it. The
  same two legs then passed against the installed release, unchanged, which
  is why the rewrite above is described as hardening: OpenRouter tolerates
  the raw shape today, and the routed path no longer depends on that. The
  shape the client sends is captured offline by
  `tools/capture_claude_shapes.py`, and `docs/compatibility.md` carries the
  run record, including the first, rate-limited control attempt.

### Bounded Claude Code verification

`tools/probe_claude_code.py --home <router-home>` drives the installed
`claude` binary against a running router, one Read-tool round trip per
advertised row, and reports the rows that failed. Each row gets a synthetic
marker file named for that model, connector MCP servers are excluded so the
request stays at the client's own tool set, and a row is never retried. A row
passes when the marker comes back in the answer, not only when it is the whole
answer: some rows narrate it, and that is a finished turn rather than a fault.
An empty or refused turn still fails. The probe leaves the caller's Claude
settings alone: it names the router in the client's private process environment
and never prints the loopback URL. The environment
matters: Claude Code lets its own environment override a settings file, and a
probe started from a Claude Code session inherits that session's first-party
`ANTHROPIC_BASE_URL`, which sent every turn to Anthropic on the user's own
login instead of the router under test. The client also runs with an empty
per-run config folder, so none of the owner's instructions, skills, plugins,
hooks, permissions or login apply, and it sends a synthetic bearer that
`PROBE_AUTH_TOKEN` can replace. The probe therefore covers routed rows; the
subscription leg of the AGENTS.md section 7 check runs as a real Claude Code
session with the owner's own login and settings, started from a terminal
rather than from inside another Claude Code session. `--deferred` adds the leg an attached client
actually runs: a synthetic MCP server advertising 700 stub tools. A pass requires
ToolSearch followed by the released tool, matching result IDs, no tool errors,
and the returned marker. An answer that only echoes the marker fails.
`--candidate <slug>` boots an isolated router from this working tree with a shared
12-attempt cap, 512 KiB input and 2,048 output tokens per attempt, then tears it
down. Repairs and replays consume that same cap. Pass `--models` to
narrow it, `--max-rows` to raise the cap, or `--json` for a machine-readable
report, and set `CLAUDE_BIN` to drive a different client binary. For the
multi-turn history check, `--read-count 2` makes two sequential synthetic
Read calls in the exact `probe-1.txt` then `probe-2.txt` order and requires
`--max-budget-usd` as a hard spend cap; it reports the
client version, requested and served model, effort, call count and result.
It also requires exactly one `tool_result` for each rewritten `tool_use` id,
so stale or duplicate result ids fail the gate.
The report labels served identity `matched`, `mismatched` or `unverified`;
a known mismatch fails the probe, while absent identity remains unverified.
Hashed listing aliases resolve to their registry upstream id before that
comparison, so a valid routed row is not rejected for using a client-safe
discovery id.
Budgeted runs accept exactly one row and one leg, so the cap cannot be
multiplied across models.

Both the probe and the zero-paid shape capture use a fresh empty client config
and remove inherited Claude routing, authentication, effort and retry variables.
Each client invocation limits agentic turns to three and output to 2,048 tokens;
an explicit effort overrides the parent's setting. SDK retries are disabled, but
Claude Code 2.1.284 still makes one separate recovery request after a 503. The
isolated router's attempt cap therefore remains the paid-call boundary; these
client settings alone are not a hard upstream-call cap on the installed router.

Verify the embedded client's limits separately, without calling a model:

```sh
SCG_TEST_CLAUDE_CLIENT=1 CLAUDE_BIN="<tested-client-path>" \
  python3.14 -m unittest tests.test_claude_client_limits -v
```

That check uses a local fake upstream and disposable history, tests turn and
output limits after resume, and measures the bounded 503 recovery. It is opt-in
and does not run an installed client during the ordinary unit suite. It does
not establish that the desktop app propagates the same settings.

## Claude desktop app

With the router already installed, run this once from the router checkout:

```sh
python3.14 packaging/install.py --desktop
```

Quit and reopen Claude, choose **Code**, select your folder, then choose a
model and type your task. No key copying or Developer-menu configuration is
needed. Attachment also runs when there is no newer router release.

The task-sharing candidate detects the signed-in account and workspace when
you open a Code task. On macOS, setup installs that background callback
automatically; you do not enter account IDs or choose profile folders. The
callback exits quietly when the router or its sharing files are gone. It makes no
model call; its cached identity becomes invalid when the account or workspace changes.
The installed macOS launchers passed both subscription-to-OpenRouter-to-subscription
and OpenRouter-to-subscription-to-OpenRouter Code-tab round trips, preserving
original tool results and the newest turns. This acceptance does not cover Cowork
sharing or Windows/Linux switching. See [compatibility evidence](compatibility.md)
for client versions, tested models and limits.

On macOS, candidate desktop setup installs **Open Claude** and **Switch Claude**
launchers for the current user. In this beta they, and task sharing, are
macOS-only: on Windows and Linux setup connects Claude without them until
native acceptance exists. **Open Claude** opens the app with the selected connection.
**Switch Claude** asks for confirmation,
lets Claude exit normally, shares local tasks using the old selection as the
conflict winner, rechecks settings and that Claude is still closed, changes only
`deploymentMode`, and reopens Claude. A second launcher request is refused until
the first finishes, so it cannot copy from an outdated selection.
**Cancel** leaves everything alone. If Claude does not finish closing within
about a minute, or you cancel its quit prompt, nothing changes and Claude
reopens if it had closed. Task sharing runs only when switching; ordinary
app launches and router startup leave histories alone. Setup and updates preserve the selected mode.
A standalone Claude Code terminal installation is not required for the
desktop app. If the installed router predates these launchers, setup keeps
Claude connected and asks for a router update before installing them.
After `install.py --rollback --to` a 0.6 release, **Switch Claude** makes that
release's plain switch without sharing tasks, **Open Claude** just opens Claude,
and the session callback stays silent. Reinstall 1.0.0 to restore task sharing.

Every model labelled **OpenRouter** uses the OpenRouter key. In synthetic tests,
the candidate launchers copy local Claude Code tasks (`claude-code-sessions`)
between the `Claude` and `Claude-3p` profiles, with their JSON records and task
files. Cowork tasks (`local-agent-mode-sessions`) stay in their own profile in
this beta. Cloud conversations are not local session files and
are outside this transfer. The desktop adapter's `detach` operation restores
the original profile settings without removing the router. Full router
uninstallation also detaches Codex and the terminal client.

Task sharing preserves `sessionId` and `cliSessionId`, keeps workspace paths
outside the profiles unchanged, and retains tasks that exist in only one
profile. Only the resolved current account in each profile participates, and
in the subscription profile only its current organization. Previous accounts'
tasks and other organizations' tasks remain separate, including any unreadable
old records.
After the first copy, sharing is tied to that pair of accounts. Signing into a
different account stops sharing so it cannot inherit the earlier account's
gateway copies. Return to the original account to resume sharing.
When both profiles contain the same session, the profile selected
before a switch wins conflicting record fields and files. Unique files from
both bundles remain, and task files keep their exact bytes. If the two
profiles hold different continuations of the same conversation, or a task's
conversation file no longer exists anywhere, that task is not shared and every
copy stays as it is. The switch still goes ahead, and Claude then shows how
many tasks were not shared. A second successful run makes no content or
permission changes.

A task you delete stays deleted. After each successful share, the router notes
which tasks both profiles hold, in a private file in its own folder that keeps
task IDs and fingerprints but no titles or conversation text. When one of those
tasks is later missing from one profile, it was deleted there, so the next
switch moves the other profile's copy to a trash folder instead of copying it
back. Nothing is erased. The copy goes to the hidden
`.claude-profile-control-trash` folder inside that profile's
`claude-code-sessions` folder, for example
`~/Library/Application Support/Claude-3p/claude-code-sessions/.claude-profile-control-trash`
on macOS. Each entry there keeps the task's record, its files and a
`retire.json` note of where they came from, so a task can be moved back by
hand while Claude is closed. A copy that changed since the last switch is kept
and shared again, so an edit wins over a delete. If a profile loses all of
its shared tasks at once, and it had more than one, for example after signing
out or resetting Claude, the router treats it as a reset rather than
deletions: nothing goes to the trash, and the tasks are shared back as before. A trash
entry that cannot be finished or undone safely stays where it is and prevents
switching.

Separate sign-in and credential files, account identity, profile settings, trust state, connector
settings and caches never cross profiles. A rejected or malformed source
record fails by itself and leaves the source data in place. Existing full and
shortened native bundle folders keep their layout; new copies use full folders.
Two sessions claiming one shortened folder are refused without overwriting it.
Duplicate records
are consolidated only after their unique bundle files have been preserved.
The next run recovers interrupted transactions that have a valid journal,
including a committed cleanup that stopped partway. A copied or restored home
folder, a shared transcript that Claude Code later deleted, or a writer that
changed a transcript during its repair does not block later switches.
Ambiguous recovery files remain in place for inspection, and prevent switching.

The target account and organization must be positively identified. When they
cannot be resolved, no tasks are shared. Switching from OpenRouter to your
subscription still works and changes only the connection, so you can sign in
there. Switching away from the subscription while tasks are saved asks you,
before Claude closes, to open a Code task in Claude first; that establishes
the automatic binding. Existing hooks are preserved, and removing the desktop
attachment removes only the callback installed by the router. If any other
required history cannot be copied safely, switching stops, the original profile
remains selected and Claude reopens on it. No transcript is silently discarded
or redacted.
Every transcript row keeps all of its fields and text, including checkpoint
file lists, code examples and keys pasted into a conversation; only paths
inside the profile folders are relocated. That text can
reach the selected provider when the task resumes. Separate credential files
remain excluded, and other copied artifacts still undergo content screening.
The launcher checks that Claude still uses
this router's saved configuration; run setup again if that configuration has
changed. An organization policy that prevents subscription sign-in also
prevents a mode switch. The launcher checks the selected local configuration
and the platform's managed source before and after Claude quits. Managed
connection overrides and unreadable policy refuse switching. Update, lifecycle
and proxy policy alone can coexist with the locally controlled connection.

The desktop app (observed in the 2.9939.2 native probes) keeps first-party and
third-party mode in separate profiles (`.../Claude` and `.../Claude-3p`).
The third-party profile uses `~/Library/Application Support` on macOS,
`LOCALAPPDATA` on Windows, and `XDG_CONFIG_HOME` with a `~/.config` fallback
on Linux. Windows falls back to Electron's roaming AppData location only
when `LOCALAPPDATA` is absent. The subscription profile uses roaming AppData.
Set `CLAUDE_USER_DATA_DIR` to override the third-party profile on all three
systems. The first-party profile remains at the platform's native location.
Automatic updates keep using the profile recorded when Claude was attached,
so an attachment made before Windows moved to `LOCALAPPDATA` keeps updating.
Running setup with `--desktop` refuses a different profile while an existing
attachment still owns its restore record; detach that connection before
selecting another profile.
The paths are pinned by simulated platform tests. Real macOS Code-task visibility,
open and resume passed the installed-launcher round trips above. Windows and
Linux still require native app acceptance.
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

Deferred tool loading: the app's own gateway mode already asks for it. From
an app that bundles Claude Code `2.1.247` or later, the request carries the
`tool-search-tool-2025-10-19` beta value, the deferred tool loading and the
`tool_reference` blocks, while the app suppresses Claude Code's other
experimental betas for that provider. The external-route rewrite above is
what makes that shape work through OpenRouter; the desktop attachment does
not write any env key of its own for it, and the app's suppression stays as
it is. An operator who wants the app to defer even where its own policy says
otherwise can set `ENABLE_TOOL_SEARCH` to `force` in OS-level Claude Code
managed settings with `parentSettingsBehavior: "merge"`; the installer never
writes that policy file.

### Bounded desktop verification

`tools/probe_claude_desktop.py --execute --endpoint-file <private-file>` starts
a temporary loopback connection for a synthetic Code task. It accepts only
DeepSeek V4.1 Flash, with four requests, 2,048 output tokens and 256 KiB of input
per request. It writes the connection URL to a new owner-only file and logs
only counters, status and served model identity. It does not edit app settings.
Temporarily select that connection in an isolated gateway profile, read a
synthetic file once, and restore the normal router connection before stopping
the probe. A startup check for another model is refused by this test guard.
