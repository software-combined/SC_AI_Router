# Changelog

## Unreleased

- Unreadable subagent handoffs now stop before Codex executes them, with a clear
  instruction to start a new turn using plaintext. The router no longer turns
  valid tool arguments into a string that triggers a parser error. Native
  encrypted handoffs and earlier valid tool calls remain intact.

## 1.0.4

- The Windows router finds an app-installed Codex again, so the SCG plugins
  reach it on a scheduled update. The Codex app keeps its own CLI under
  `%LOCALAPPDATA%` and never puts that directory on the updater's PATH, so the
  plugin refresh reported Codex as not installed; the router looks there too.

- The router now retires the old Git-based SCG plugin updater only once Codex
  accepts the router's copy of the plugins. That updater only ever refreshes
  Codex, but any client's success used to retire it. So a Claude Code success
  alone could retire it while Codex still took its plugins from Git, for
  example when the router serves only Claude Code or an update cannot find
  Codex, and Codex's plugins then stopped updating. The router also
  recognises the three earliest versions of that updater, so a host still
  running one of them has it retired too.

## 1.0.3

- Codex now keeps every subscription model OpenAI still advertises, including
  older models that the router had removed from its static list. Models OpenAI
  hides stay hidden, and subscription and OpenRouter billing remain separate.
  Updating the router does not replace updating Codex: OpenAI can offer a
  different model list to an older client.
- After a Codex upgrade, starting a chat now uses the model list for the
  current client version. Previously, cached lists from both versions could
  make a newly advertised model appear in the picker but fail as unavailable.

## 1.0.2

- Installing without a ChatGPT subscription no longer changes Codex settings
  written just below the router's lines. The router's provider settings used
  to open a section of their own, so an owner setting such as
  `approval_policy` that followed them was read as part of that section and
  ignored by Codex. The next update puts those settings back in effect.
  An owner line that sets one of the router's own settings, such as your own
  `model_provider`, is set aside while the router is attached instead of
  making the configuration unreadable, and uninstalling puts it back.

- On Linux, the router now switches off the old SCG plugin updater once it
  delivers the plugins itself. Before, the old updater's daily timer kept
  running and failed every day, which also marked the desktop session's
  services as degraded. The router also recognises every released version of
  that updater, and switches off a timer an earlier router left running after
  it had already moved the old updater aside. The old files are kept, renamed,
  rather than deleted. Its service is stopped too, and the old timer and
  service's failure state is cleared. If the scheduler refuses the change,
  retirement stays pending and keeps the files for a later retry.

## 1.0.0

- SCG plugins now reach Claude Code and Codex through the router. The router's
  plugin folder now includes the marketplace file Claude Code reads, so Claude
  Code installs the plugins instead of refusing the folder. When Codex still
  had the plugins registered from the Git repository, the installer moves that
  registration to the router's copy; before, Codex kept installing older
  plugins from Git. Automatic updates now find `codex` and `claude` in
  `~/.local/bin`, and on macOS and Linux also in `/opt/homebrew/bin` or
  `/usr/local/bin`, so plugins refresh on scheduled updates as well as manual
  installs. A plugin you turned off in Codex or Claude Code now stays off;
  every install used to turn it back on. On Windows, a client installed
  through npm (`codex.cmd`) now runs from the path it was found at; before,
  every plugin command failed. A first plugin delivery that was cut short no
  longer blocks every later one.
- On Windows, the installer no longer looks for Python in drive-root folders
  such as `C:\usr` or `C:\opt`, which any account on the computer can create.

- Switch Codex (macOS): the ChatGPT app (Codex) 26.917.51856 and later stops
  sending messages for every model once your ChatGPT subscription reaches its
  usage limit. The new Switch Codex app in your Applications folder moves Codex
  to OpenRouter models, and back. It asks first, quits and reopens the ChatGPT
  app, and checks that Codex loads the new settings before it keeps a switch to
  OpenRouter models. If the ChatGPT app does not close, Switch Codex reopens it
  and asks you to quit it yourself and try again.
- SCG Router offers Switch Codex once when your ChatGPT subscription reaches its
  usage limit, and offers the way back once when the limit resets.
- While Codex is switched, only OpenRouter models are listed, and a model that
  needs your ChatGPT subscription answers with a plain message that says what
  to pick instead. Codex still asks you before it runs a command that needs
  approval, and conversations started while switched still open after you
  switch back.
- Known limitations while Codex is switched: archiving a conversation fails with
  "Failed to archive conversation", a ChatGPT app (Codex) issue, so switch back
  to archive it. Conversation titles are not generated.
- If Claude does not close in time, Switch Claude reopens it and asks you to try
  again. Crash-reporter helpers, which can keep running for days after an app
  update, no longer hold up Switch Claude or Switch Codex.
- Switch Codex, like Switch Claude, is macOS-only in this beta.
- Claude Sonnet 5.5 replaces Claude Sonnet 5 in the OpenRouter model list.
- The OpenRouter picker now offers GPT-6.1 Sol in place of GPT-6 Sol. An
  upgrade drops the older row instead of showing both. A text-file Read no
  longer receives Claude Code's PDF page argument, so a model that fills every
  advertised argument reads the file once instead of retrying a blank page
  range.
- The OpenRouter picker no longer offers GPT-5.6 Terra. GPT-5.6 Terra on your
  ChatGPT subscription is unchanged.

- SCG plugin delivery now reports the cause of a marketplace-synchronisation
  failure and the command and client error for each refused plugin
  registration, so a broken but fail-soft delivery is diagnosable from the
  install log instead of showing only an exception type or a refusal count.

- Switch Claude now copies your current account's local Claude Code tasks, with
  their full conversations and files, to the other connection before switching.
  Only tasks from the organization you are signed in to are shared; tasks in
  your other organizations stay where they are. Cowork tasks are not shared in
  this beta and stay where they are. Sign-in files never move. A task whose
  conversation is missing, or was continued differently on each connection, is
  left as it is with both copies kept; Claude still switches and then says how
  many tasks were not shared. Any other copy problem keeps Claude on its current
  connection, and Claude reopens there if it had already closed. Open Claude and
  router startup leave tasks alone. Full native acceptance remains pending; see
  `docs/compatibility.md`.
- A Claude Code task you delete no longer comes back after Switch Claude. Its
  copy on the other connection is moved to a hidden trash folder,
  `claude-code-sessions/.claude-profile-control-trash` inside that connection's
  Claude folder, and is never erased. A copy that changed since the last switch
  is kept and shared again. When a connection loses every one of several shared
  tasks at once, for example after signing out, they are shared back instead.
- Switching from OpenRouter back to your Claude subscription no longer waits for
  task sharing to be set up. Switching away from the subscription with saved
  tasks first asks you to open a Code task in Claude, before Claude closes.
- Switch Claude waits for Claude's own task processes to finish before it
  switches; browser helpers can stay open. If a switch is interrupted, or your
  home folder was copied or restored, the next switch finishes or undoes the
  earlier one instead of refusing every later switch.
- On Windows, new Claude desktop setups use the gateway profile in local
  AppData. An earlier attachment keeps its original profile, and automatic
  updates keep using it.
- Switch Claude, Open Claude and task sharing are macOS-only in this beta. On
  Windows and Linux, setup connects Claude without them until they have been
  tested there. After rolling back to a 0.6 release, Switch Claude uses that
  release's plain switch, Open Claude just opens Claude, and Claude Code sessions
  start normally; reinstall 1.0.0 to share tasks again.

- Helper-turn fallback now also answers subscription 401/403 auth refusals
  from the twin row. An exhausted login refuses naming turns with 401 as
  well as 429; the twin answers those under the same gates. Ordinary
  turns keep the raw upstream answer so a sign-in problem stays visible.

- Refused thread-title helper turns now fall back to the Luna OpenRouter
  twin unless `openai_helper_fallback` is explicitly false. Slugs with a
  twin keep the same-model twin; twinless slugs answer from
  `openai/gpt-6-luna`. Portco allowlist, key-filtered availability and the
  single-handoff ledger rules still gate every fallback.

- The installer now sets `approvals_reviewer = "user"` in the managed
  Codex block in both subscription and no-subscription mode, so a fresh
  or updated install never falls back to the background reviewer. An
  owner copy of the line outside the block is removed on attach and its
  exact text is recorded in the activation receipt, so detach puts it
  back; `approval_policy` stays untouched.

Entries older than the 1.0 series are archived unedited in
[docs/changelog-archive.md](docs/changelog-archive.md).
