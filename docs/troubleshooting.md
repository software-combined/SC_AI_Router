# Troubleshooting

Scheduled checks can reconnect Codex when its complete Router block is missing.
This requires an active attachment receipt and a healthy Router.
Partial blocks, conflicting connection settings and damaged receipts require manual review.
Use the supported detach or removal action to disable automatic reconnection.
After attachment or repair, **Restart Codex to load SCG Router** offers **Quit and reopen** and **Later**.
If no dialog is available, the notice stays pending.
The content-free `logs/maintenance.jsonl` records regular and Express check outcomes.
It also records tray helper exits, retry decisions and controller exception types.
An unexpected tray exit gets one retry. Quit keeps the current controller closed.
New resource updates launch the menu quietly, including when sign-in startup is Off.
On Windows, missing or invalid preferences default to On. A valid saved Off stays Off.
Installs and updates reconcile the startup shortcut without saving a preference.
Use the menu's **Start at sign-in** action to save a choice.

Windows task logs record launch, completion and safe failure facts, including missing launch scripts.
If no Python launch event exists, check Task Scheduler History and the task's last-result number.
The launcher cannot record attempts Windows refuses before Python starts.
`logs/update.log` records `installed <version>; health verified` after each verified installation.
Attachment failures have separate maintenance events. Unchanged checks and rollbacks do not claim an installation.

Windows updates verify the executable paths of all three owned scheduled tasks.
Failed verification restores prior definitions and retries on the next maintenance pass.
Both runtime folders remain available. Do not remove old setup folders during recovery.

Temporary network, update-signature and download failures retry on the existing schedule.
The current Router keeps running. Rejected updates cannot install.
The menu shows **Updates will retry automatically**; these failures do not open Repair dialogs.
A verified successful feed check clears its earlier feed error, including an unchanged Express check.
If retry status persists, run **Check for updates** and share the safe error code with IT.

A repair warning can show matching running and latest versions.
It means an installation is incomplete, a saved component failed, or an installer repeatedly failed.
A successful version check does not verify those components or clear a pending installation repair.
Missed checks alone do not require repair; the computer may have been asleep.
The dialog names failed components; `logs/maintenance.jsonl` records their names and your choice.
**Later** delays the next displayed warning for 24 hours. It keeps the repair pending.
If it returns sooner, the log distinguishes an unconfirmed dialog from a failed receipt write.
Choose **Repair now** after finishing active work. If the warning returns, run **Check setup**.
Share the reported component names with IT. Do not share keys or authentication files.

If Windows reports that Router could not check its stored key, retry shortly.
This message does not mean the key is invalid. If it persists, open **SCG Router**
and run **Check setup**. Permission-query diagnostics contain operation names,
Windows error numbers and timings, without key contents.
After three days, summarise `permission_query_failed`, `CREDENTIAL_PERMISSION` and
`CREDENTIAL_CHECK_UNAVAILABLE` across `router.jsonl` and rotations `.1`, `.2`, `.3`.
Include time coverage and missing files. Return counts, without raw log records.
This observation does not delay stable after functional Windows acceptance.

The historical configuration removal during account changes remains unverified.
Reproduce sign-in, sign-out or account switching only in an isolated standard Windows profile.
Compare configuration timestamps, size and block presence; do not read authentication files.

If Switch Codex reports a missing bundled tool, update the ChatGPT app (Codex).
Router discovers the current Store package, then checks the bundled Windows executable
and its version. Do not set `CODEX_BIN` or save a versioned Store path.
Store Codex identity and process checks use native Windows APIs.
Closing Codex's window can leave its tray app and tasks running.
Switch Codex asks to fully close Codex and stop its tasks before changing settings.
Finish active work before choosing Continue. Cancel leaves Codex unchanged.
The switch gives Codex five seconds to close, then ends its verified root before surviving workers.
It waits for confirmed exits before changing settings. Exiting processes need no further identity reads.
Reopening can take up to thirty seconds on a cold start.
A failure restores the previous connection and attempts reopening.
Confirmation and waiting windows use the verified native helper, without PowerShell.
Claude desktop process checks retain a sixty-second limit for busy sessions.
A failed check refuses before changing settings.
If an update owns the installation lock, Switch Codex waits up to sixty seconds.
Its waiting window offers Cancel. Healthy unchanged update checks do not take that lock.
An actual install or repair can still delay switching; retry after it finishes.
The switch log distinguishes identity timeouts, query failures and rejected commands.
It records identity, quit, proof and reopen durations, plus scan count and maximum scan time.
Its command paths are relative to the package. Protected unrelated Windows processes
do not block switching; an unreadable relevant app process still requires attention.

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

The catalogue check uses your company policy and the models available to your
key. Models hidden by either filter do not require a repair. A catalogue warning
means the saved rows differ from that installed projection.
Setup and repair record Claude's current served model list, including those
filters, for the separate listing check.

## Windows: use the installed setup tools

On Microsoft Windows 11 x64, run the supplied `bootstrap.ps1` before these steps.
Use ordinary PowerShell under the same Windows user who ran setup.
If your organization blocks scripts, contact IT; keep its execution policy in place.
You do not need a repository checkout or a separate Python installation.

Paste this block once to find the installed tools. It reads paths and the
installed version, and prints no keys:

```powershell
$RouterRoot = if ($env:ROUTER_HOME) { $env:ROUTER_HOME } else { Join-Path $env:USERPROFILE '.codex\mixed-model-router' }
$RouterVersion = (Get-Content -Raw -LiteralPath (Join-Path $RouterRoot 'current')).Trim()
$RouterPython = Join-Path $RouterRoot 'runtime\python\python.exe'
$RouterInstaller = Join-Path $RouterRoot "releases\$RouterVersion\packaging\install.py"
if (!(Test-Path -LiteralPath $RouterPython) -or !(Test-Path -LiteralPath $RouterInstaller)) { throw 'Run SCG Router setup again before continuing.' }
$RouterSavedState = Get-Content -Raw -LiteralPath (Join-Path $RouterRoot 'mixed-router-state.json') | ConvertFrom-Json
$RouterClaudeRoute = if ($null -ne $RouterSavedState.anthropic_mode) { $RouterSavedState.anthropic_mode } elseif ($null -ne $RouterSavedState.openai_mode) { $RouterSavedState.openai_mode } else { 'subscription' }
Remove-Variable RouterSavedState
if (@('subscription', 'none') -notcontains $RouterClaudeRoute) { throw 'SCG Router settings need an IT check before continuing.' }
```

The block also preserves Claude's current subscription setting, including older
installs where it follows the ChatGPT setting. Keep `$RouterClaudeRoute` in the
Codex commands below so a Codex change does not disable a working Claude connection.

For a diagnostic check, run:

```powershell
& $RouterPython $RouterInstaller --home $RouterRoot --doctor
```

If you open a new PowerShell window or the router updates, paste the path block again.
For a source installation, use its Python 3.14 interpreter and matching installer instead.

## Codex Send button is greyed out or ChatGPT subscription access is unavailable

From 1.3, open **SCG Router → Codex → OpenRouter only** and confirm the restart.
Choose **ChatGPT + OpenRouter** to return. The [desktop menu](desktop-menu.md)
preserves the saved-chat connections. The commands below remain recovery steps
for installations without the menu and have their stated history limits.

Affected Codex desktop versions disable **Send** when the ChatGPT allowance runs out,
including when you select an OpenRouter model. The router cannot fix a disabled
button by changing models alone. Change Codex's connection to OpenRouter.
If you have no ChatGPT subscription access, use the same OpenRouter connection.
Other causes of a disabled button need diagnosis if this does not restore it.

### Microsoft Windows

Use these commands for new chats. Before changing connections, save a short task
handover outside Codex. Existing chats can need their original connection to reopen:
OpenRouter chats need the OpenRouter connection again after you return to your subscription.
These Windows commands do not provide the Mac helper's preservation of both chat connections.

1. Let any running task finish. Quit Codex and close its terminal sessions normally.
2. Open PowerShell and paste the [installed-tool path block](#windows-use-the-installed-setup-tools).
3. Run this command to use OpenRouter without a ChatGPT subscription:

```powershell
& $RouterPython $RouterInstaller --python $RouterPython --home $RouterRoot --clients codex --openai-mode none --anthropic-mode $RouterClaudeRoute
if ($LASTEXITCODE -ne 0) { throw 'The connection change failed. Stop and contact IT.' }
& $RouterPython $RouterInstaller --python $RouterPython --home $RouterRoot --setup
if ($LASTEXITCODE -ne 0) { throw 'SCG Router did not restart. Stop and contact IT.' }
```

4. The second command restarts SCG Router and opens its key window. If your key
   already works, choose **Cancel**; the connection change and restart still apply.
   If you enter a key, choose **No subscription**, then save it in that window.
5. Reopen Codex and start a new chat. Select a model labelled `· OpenRouter`, then send a short greeting.
6. Check that Send works and that you receive a reply. OpenRouter charges your key.

When ChatGPT subscription access returns, quit Codex normally and run this command
from the same PowerShell window. Recreate the paths first if needed:

```powershell
& $RouterPython $RouterInstaller --python $RouterPython --home $RouterRoot --clients codex --openai-mode subscription --anthropic-mode $RouterClaudeRoute
if ($LASTEXITCODE -ne 0) { throw 'The connection change failed. Stop and contact IT.' }
& $RouterPython $RouterInstaller --python $RouterPython --home $RouterRoot --setup
if ($LASTEXITCODE -ne 0) { throw 'SCG Router did not restart. Stop and contact IT.' }
```

In the key window, choose **Cancel** if your key already works. If you save a
key again, choose **I have one** for the ChatGPT subscription question.
Reopen Codex, start a new chat and choose a subscription model without the `· OpenRouter` suffix.
Check that it replies. Switching back cannot restore an expired plan or exhausted allowance.
These commands keep your sign-in and other attached assistants in place.
Use `--clients codex` with the mode flag so an already-current install applies the change.
Run `--setup` separately afterwards to restart the router; combining the flags
can take the key-window repair path without applying the client connection.

### macOS

If Codex already uses your ChatGPT subscription, open **Switch Codex** from
your user's Applications folder, or choose **Open Switch Codex** in the router notice.
Confirm the restart. Select an OpenRouter model and check that it replies.
When subscription access returns, open **Switch Codex** again, confirm, and
choose a subscription model after Codex reopens.

For a first setup without a ChatGPT subscription, choose **No subscription**
in the key window. The Switch Codex helper is unnecessary in that mode.
The helper verifies the loaded settings and restores the previous connection if switching fails.
See [Switch Codex](operations.md#switch-codex) for the affected versions and recovery details.

While Codex uses its OpenRouter connection, automatic chat titles and archiving
are unavailable. On Mac, switch back with **Switch Codex** when you need to archive a chat.
On Windows, keep the chat-resume limit above in mind when changing connections.

## Claude desktop: switch to OpenRouter and back

From 1.3, use **SCG Router → Claude** to choose an explicit connection.
The [desktop menu](desktop-menu.md) uses the same guarded switch owner described below.
Native Windows and Linux desktop acceptance remains pending.

Claude desktop uses separate subscription and OpenRouter profiles. Selecting a
model inside one profile does not change the connection. The OpenRouter profile
lists models billed to your OpenRouter key.

### Microsoft Windows

For first setup, choose **Claude desktop** in the setup questions. On an existing
router installation, quit Claude normally, paste the [installed-tool path block](#windows-use-the-installed-setup-tools), then run:

```powershell
& $RouterPython $RouterInstaller --python $RouterPython --home $RouterRoot --clients none --desktop --claude-mode subscription
```

This attaches only Claude desktop and keeps other attached assistants in place.
Claude stays on your Claude subscription until you choose **SCG Router → Claude →
OpenRouter**. Claude then restarts on OpenRouter. The first switch sets up the OpenRouter profile; switch back and forth once to bring your saved Code tasks. Choose **Code**,
a folder and an OpenRouter model. Send a short greeting and check that it replies. Re-running setup preserves an existing connection choice;
it does not toggle between subscription and OpenRouter.

**Windows switching is an IT pilot, not a verified staff rollout.** Setup does
not install **Switch Claude** or **Open Claude** shortcuts on Windows yet.
The release includes a manual helper for an IT-led pilot:

```powershell
$RouterClaudeSwitch = Join-Path $RouterRoot "releases\$RouterVersion\packaging\claude_desktop_switch.py"
& $RouterPython $RouterClaudeSwitch --home $RouterRoot --action switch
```

The helper asks to change to the other connection, closes Claude normally, then reopens it.
Run the same command again to return. It can refuse if settings are managed,
tasks are not ready to share, or Claude cannot close. Keep that refusal and contact IT.
Do not edit profile files or force-close Claude to get past it.

Before staff use this Windows switch, IT must verify both directions on a real
Windows machine, including a reply, saved Code tasks and the original subscription sign-in.
Windows task sharing remains unverified; Cowork tasks and cloud chats are not transferred.
Until that pilot passes, use Codex's Windows OpenRouter steps when you need to
work without ChatGPT subscription access.

### macOS

Open **Switch Claude** from your user's Applications folder. Confirm the change
to OpenRouter and let Claude restart. Choose **Code**, a folder and an OpenRouter
model, then check that it replies. Open **Switch Claude** again to return to your
Claude subscription, confirm the restart and check a subscription reply.
**Open Claude** opens whichever connection is selected; it does not switch it.
Cancel leaves the selection unchanged. If Claude refuses to close or share a task,
follow its message; keep your original tasks in place.

Mac Code-task sharing has passed recorded round trips. Cowork tasks and cloud chats
remain separate. See [Claude desktop setup and limits](claude-code.md#claude-desktop-app).

## I have no Claude subscription access

Choose **No subscription** for the Claude question in the key window. From a
terminal, add `--claude-mode none` to the install command. Then:

- Claude Code in the terminal needs no Claude sign-in. It starts on OpenAI
  GPT-6 Luna at max effort. Its Opus, Sonnet, Haiku and Fable choices use the
  matching Claude models on OpenRouter, or Claude Sonnet when one is missing.
  Restart it after setup.
- Claude desktop opens on OpenRouter. **Claude subscription** is unavailable
  in the SCG Router menu.

Setup stops with a message when your OpenRouter key cannot use Claude Sonnet.
Ask IT to check the key. To add a subscription later, choose **Replace model
key** in the SCG Router menu and answer **I have one**.

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
one replaces the subscription credential the router forwards. Without a Claude
subscription, the installer sets `ANTHROPIC_AUTH_TOKEN` to its own placeholder;
leave that value as it is.

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
