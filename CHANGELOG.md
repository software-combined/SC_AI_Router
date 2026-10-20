# Changelog

## Unreleased

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
  as Microsoft's licence requires. Record the basis for shipping those files so
  the Windows installer can be published once the terms are approved.

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
