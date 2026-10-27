# Changelog

## Unreleased

- The OpenRouter picker now offers MiniMax M3.1 Flash on its paid endpoint,
  after the free entry was withdrawn. They are separate ids: the paid row
  passed both client route checks and keeps thread history on a switch.

- The OpenRouter picker no longer offers MiniMax M3.1 Flash (free). OpenRouter
  withdrew the free endpoint, so the router drops the row instead of keeping a
  model that can no longer answer.

- The OpenRouter picker now offers GPT-6.1 Terra. It passed the isolated Codex
  and Claude Code route checks, so both clients can switch to it and keep
  their thread history.

- Keep new Codex chats working on OpenRouter when Codex requests encrypted
  output metadata. Omit its unsupported include option on that route.
- Give OpenRouter Codex mode hidden Luna helper aliases and route chat titles
  and metadata to Luna. Preserve the chosen chat model and model access policy.
- Run Windows update checks at sign-in and catch missed scheduled checks.
  Migrate all three owned tasks while preserving disabled schedules and pending state.
- Keep one Windows tray menu per native session, even when Task Scheduler supplies
  a different environment. Start the menu before offering a repair warning.
- Report safe Windows task error codes and inspect only the owned task's instances.
  Ignore confirmed completed instances; refuse unknown or unreadable task state.
  Include active owned instances that Windows omits from the caller's scoped view.
- Record menu and setup installation launches, child exits and failures in the
  update log. A deferred menu install reports busy instead of reporting completion.
- Keep model verification usable without Git. Preserve source and capability
  fingerprints when the optional repository revision is unavailable.
- Require Windows core and native process, dialog and key-permission checks
  from a standard user account during main release acceptance.
- Keep task logging open when a Windows launch has no standard output or error.
- Verify and restore owned Windows shortcuts and the Apps entry during installation recovery.
  Preserve explicit sign-in choices and launch the sign-in menu without a console.

## 1.3.21

- Keep verified Windows Codex process handles through shutdown. Exiting app
  processes no longer fail switching when Windows stops answering identity queries.
- End the verified app root before surviving workers, and wait for retained handles
  to signal before changing settings. Give cold reopening up to thirty seconds.

## 1.3.20

- Remind Codex on subscription and routed models that native tools can be
  absent from `ALL_TOOLS`. Require current definitions or direct-call evidence
  before reporting missing tools, restarting the app or moving to a new chat.

## 1.3.19

- Replace Kimi K3 with Kimi K3.1 Pro in Codex and Claude Code.
  Retire K3 from saved pickers and model caches.

## 1.3.18

- Retry temporary update-check failures quietly on the existing schedule.
  Keep rejected updates blocked and show retry status without opening repair dialogs.
- Clear a recovered feed error after a verified unchanged Express check.
  Preserve incomplete installations, failed components and parked installer failures.
- Offer Repair only for installation faults, failed components or parked installers.
  Missed checks alone do not ask for repair after a computer wakes from sleep.

## 1.3.17

- Discover Windows Store Codex through native package APIs on every switch.
  Check package processes and tracked descendants without PowerShell owner scans.
  Recheck open handles before lifecycle actions and verify a visible window after reopening.
- Correct the Windows AppsFolder activation command used to reopen Claude desktop.
- Confirm that Windows Codex will fully close and running tasks will stop.
  Give the app five seconds to close, then end only its verified surviving processes.
  Keep settings only after Codex reopens; restore the prior connection on failure.
- Use the verified native helper for Switch Codex confirmation and waiting windows.
  Record stage durations and distinguish an app still running from an unavailable check.
- Preserve the original owned settings' line endings when a Codex switch rolls back.

## 1.3.16

- Allow sixty seconds for Windows process snapshots on busy Codex and Claude desktops.
  Keep each shutdown probe within the remaining graceful-close deadline.
- Wait up to sixty seconds for an active update before switching Codex.
  Show a waiting window with Cancel; cancellation leaves Codex and settings unchanged.
- Inspect attachments and scheduled runtime paths without the installation lock.
  Healthy unchanged regular and Express checks leave foreground switching free.
  Recheck every repair under the lock and present restart notices after releasing it.

## 1.3.15

- Switch Windows Store Codex without querying owners of unrelated protected processes.
  Keep tracking app descendants and refuse an unreadable relevant process.
- Allow thirty seconds for Store identity discovery and record safe failure reasons.
- Select and verify the bundled Windows executable before switching.
  Discover each updated package afresh; ignore Windows `CODEX_BIN` overrides.
- Default missing or invalid Windows startup preferences to On. Preserve saved Off choices.
  Installation maintenance never saves a startup choice.
- Relaunch the menu quietly after verified resource advancement, independently of sign-in startup.
  Keep one controller per session and leave unchanged checks and removal quiet.
  Keep resource reload independent of a changed sign-in choice.
- Offer Restart Codex after verified attachment changes, including same-version setup.
  Preserve pending offers and expose unsafe recovery through the existing repair warning.
- Record every Windows task launch and completion or safe failure classification.
  Write installation evidence only after verified health, across direct and scheduled installs.

## 1.3.14

- Preserve Unicode task paths and saved definitions across Windows PowerShell.
- Move all three owned Windows tasks to the verified retained runtime after delivery.
  Preserve schedules and disabled states. Restore prior definitions if verification fails.
- Record tray helper exits and controller failures. Retry an unexpected helper exit once.
  Keep Quit, removal and the saved startup choice effective.
- Explain which component needs repair when the installed and latest versions match.
  Record safe warning facts for support and hide the repair command's console window.
- Recognize Windows **Later** even when PowerShell returns extra output.
  Keep the daily warning limit and leave unconfirmed dialogs pending.

- Reconnect an active Codex attachment when its complete Router block is missing.
  Preserve model choices and original settings evidence. Conflicts stay unchanged.
  Offer a dismissible restart notice even when no version or model changed.
- Record regular and Express update launches, completion, failure and repair outcomes.

- Find the bundled Codex command beside the verified Windows Store app.
  Keep the same app identity during switching and recovery.
- Hide console windows during Windows app checks, setup choices and notices.

- Read Windows key permissions directly instead of starting PowerShell. A
  temporary permission-query failure now retries briefly and asks the client
  to retry, rather than rejecting requests for 30 seconds or requesting a new key.

## 1.3.13

- Point the setup-script links in the agent install prompt, the Claude Code
  guide and the operations guide at `https://dist.softwarecombined.com/install/`,
  where each release publishes the current scripts. The prompt named a folder
  that returns Forbidden, and the other links fetched an older script.
- Say plainly in the README and the Claude Code guide that Claude desktop's
  OpenRouter mode can offer other vendors' models as well as Claude models. The
  old wording read as if those models did not work. Anthropic still does not
  support them.
- Set up Claude without a Claude subscription. Answer **No subscription** for
  the Claude question in the key window (also asked for Claude desktop alone).
  Claude Code in the terminal then needs no Claude sign-in: it starts on
  OpenAI GPT-6 Luna at max effort, and its Opus, Sonnet, Haiku and Fable
  choices use the matching Claude models on OpenRouter. Claude desktop opens on
  OpenRouter, and the menu disables **Claude subscription**. Setup used to
  refuse this choice.

## 1.3.11

- Add MiniMax M3.1 Flash (free) to both model pickers after real Codex and
  Claude Code checks. Low is the default reasoning effort. OpenRouter retires
  this free entry on 22 October at 23:00 AEDT; the paid entry needs separate
  availability and onboarding checks before it can replace it.

## 1.3.10

- Add StepFun Step 5 Preview to both model pickers after real Codex and
  Claude Code checks. Low remains the default reasoning effort.

## 1.3.9

- Set the simulated platform before creating Mac reopen requests in tests, so
  Linux release checks use the same session lock as the menu under test.

## 1.3.8

- Update the warning-window test fixture for the shared window lock, so native
  installer checks exercise the same controls as the released app.

## 1.3.7

- Reopen the existing Mac menu when SCG Router is already running, instead of
  opening another control window. Control windows now run one action and close,
  use Run action and Close buttons, and fit Mac choices to their labels.
- Keep one control window per session on every platform. Fit Windows action
  lists to their labels and show more choices without scrolling. Check setup
  now asks before entering the setup wizard, which may restart assistants.
  Keep the working control window available if a menu update is incomplete.

- Point the setup and repair links in the README, guides and router skill to
  the short link `https://hub.softwarecombined.com/router`. It opens the same
  setup page.

## 1.3.6

- Keep Claude desktop on the Claude subscription when you connect it, so the
  menu shows the connection Claude is really using. Setup then offers Switch
  Claude, which restarts Claude on OpenRouter. The first switch sets up the
  OpenRouter profile instead of asking for a Code task that could not help;
  switching back and forth once more shares your saved Code tasks.
  Before, connecting selected OpenRouter for the next launch, the menu ticked
  OpenRouter while Claude still ran on the subscription, and a plain reopen
  skipped task sharing.
- Make Continue the default button in confirmation dialogs. Notices that need
  no decision now show a single OK button instead of Cancel.
- Keep the Codex and Claude rows in the menu when one status check fails.
- Stop Remove Router before it closes any app while Codex uses OpenRouter only,
  and say how to switch back in the menu.
- Explain an offline update check or a busy router in plain words instead of
  asking for a repair.
- Simplify the control window: it lists each assistant's current connection,
  offers only real changes, and merges duplicate actions. The menu drops the
  fine-print row, shows the running version only when it differs, offers
  Restart Router to use the installed version, and shows times without long
  Windows zone names.
- Make removal finish cleanly. Settings → Apps and the Start menu now list
  SCG Router with an Uninstall action on Windows. Removal waits for a running
  update instead of reporting success without removing anything, keeps Codex
  and terminals open, closes Claude only while it uses OpenRouter, then closes
  the SCG Router menu and removes its sign-in and Start menu entries. The final
  message says which assistant to reopen and that the key and settings stay.
- Dismiss the Windows tray menu when you click elsewhere or press Escape, and
  never leave a stale popup behind when the menu updates or closes.
- Offer the macOS, Windows and Linux installers as the download, with clear
  steps for the one-time unsigned-app prompt. When no installer is ready for
  the current release, say so; setup scripts stay in an IT section.
- Ask Windows users to accept short terms for Microsoft's Visual C++ runtime
  files before they are installed, in both the installer and the setup script,
  as Microsoft's licence requires. Record the owner-approved terms and the
  basis for shipping those files so the Windows installer can be published.

## 1.3.5

- Remove private environment identifiers and contact details from bundled
  plugins, examples and public package metadata.
- Keep private prototype publishing settings in an external configuration
  file. The bundled template is blank and fails closed.
- Mask private release infrastructure identifiers in GitHub Actions logs,
  including AWS account and derived distribution details.

## 1.3.4

- Resolve the Windows Store Claude subscription profile from its current-user
  package registration, including its `Network/Cookies` sign-in change detector.
  Keep legacy cookie storage supported without reviving a stale sign-in.
- Run the Windows Claude identity callback directly with literal arguments,
  so it needs no Git Bash and supports spaces and shell characters in paths.
- Preserve review-hook template bytes in Windows-built bundles so setup checks
  agree with the executable Bash hooks already installed.

- Accept canonical local file URLs during Windows source and native setup,
  including spaces, Unicode and percent signs in the download folder.
- Recognize Windows client-disconnect errors without treating them as an
  upstream fault. Preserve hash-pinned runtime notices across Windows checkouts.
- Preserve model labels and bundled instructions on Windows by reading them
  as UTF-8, including refreshed model caches.
- Stop asking for a key again when setup reports that a key is already stored.
- Treat closing the Windows key window as Cancel; submit only with Save and connect.
- Keep the native Windows migration fixture alive through slow Task Scheduler
  calls, and verify the updater process survives independently of its task.
- Make macOS identity mocks, exact-line-ending expectations and synthetic
  credential fixtures portable; skip symlink cases only when Windows denies
  the required privilege.
- Read source-size checks as UTF-8 so contributor verification works on
  Windows with its default non-UTF-8 encoding.

## 1.3.2

- Publish the common setup and repair page independently of native-installer
  acceptance. Verify Linux's loaded stable updater and timer on native CI.

- Keep update failures visible in Router controls. Offer **Repair now / Later**
  after a blocked update, two failures or two missed checks plus 15 minutes.
  Limit displayed prompts to once daily and retain warnings without a desktop.

- Repair existing installations through the public setup without replacing keys
  or saved choices. Keep platform repair links visible when native downloads
  are unavailable. Existing controls use the newest verified maintenance code.

- Show the latest verified channel version and last successful update check.
  Keep failed and parked updates visible after cached responses, channel changes
  and runtime rollback. Report component repair separately from routing health.

- Preserve Codex line endings, preference comments and unrelated formatting
  during repair and removal. Provide a read-only ownership report with specific
  conflict reasons and no configuration contents.

- Preflight every assistant before removal. Preserve changed connection values
  and unrelated settings, and keep Router running when an interrupted removal
  needs another attempt.

- Repair Linux's scheduled updater independently of assistant settings. Retain
  verified maintenance code across runtime rollback and keep releases used by
  loaded jobs or the running updater.

- Repair and remove Codex attachments after harmless client formatting changes.
  Preserve added user settings, comments and dotfile links, while refusing
  changed connection values and unsafe edits.

## 1.3.1

- Preserve the exact previous menu pointer after failed Windows menu delivery.

## 1.3.0

- Keep desktop controls responsive across profile changes, expose menu delivery
  failures separately and make redacted support bundles easy to find.
- Preserve Windows file durability and case-insensitive app identity, and wait
  for orphaned Linux app writers before changing client settings.

- Deliver matching native menu resources through signed updates. Repair missing
  controls on same-version and cached checks while preserving the previous menu.

- Build native menu helpers for macOS, Windows and Linux, with pinned Linux
  dependencies and per-target Resources archives for update delivery.

- Add shared desktop controls, safe router restart and owned sign-in startup.
  Keep the menu separate from routing and retain a full control window without a tray host.

- Add explicit desktop connection destinations while retaining existing switch
  shortcuts. Claude transitions now serialize with installation and updates.
