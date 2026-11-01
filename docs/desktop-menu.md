# SCG Router menu and tray

Open **SCG Router** from your applications to access its permanent controls.
On Mac, select its menu bar icon. On Windows and Linux, select its tray icon.
Reopening the Mac app opens its existing menu without creating another window.
If a menu update is incomplete, the control window stays available instead.
Windows decides whether the icon sits directly on the taskbar or in its overflow area.
You can change that choice in Windows settings.

## Change a connection

The menu shows a section for each attached desktop assistant.
Choose a destination in that assistant's section:

| Assistant | Connection choices |
| --- | --- |
| Codex | ChatGPT + OpenRouter; OpenRouter only |
| Claude | Claude subscription; OpenRouter |

The checkmark identifies the selected connection. Selecting it again does nothing.
Connecting Claude leaves it on your Claude subscription, which it is already using.
Choose **OpenRouter** to switch; setup offers the same switch when you connect Claude.
Before a change, SCG Router explains the required assistant restart.
**Continue** is the default button. Choose **Cancel** to leave the connection unchanged.
Finish any work the assistant asks you to save before it closes.

SCG Router waits for the assistant to close safely, then changes its connection.
Claude shares saved Code tasks between its profiles using the existing account binding.
Cowork tasks stay in their original profile.
Managed settings, failed shutdown or incomplete task recovery can stop the change.
SCG Router preserves the previous selection when it cannot finish safely.

Choose models inside the assistant. Claude Code keeps its terminal `/model` flow.
The tray does not switch named human accounts or sign either subscription out.

## Understand the status

**Running** means the router answered its health check.
It does not prove that a model has replied in your selected assistant connection.
Send a new message after switching and check the reply before relying on that connection.
**Switching…**, **Opening…**, **Updating…** and **Working…** identify work in progress.
If a status check fails, the menu shows **Needs attention** and keeps the last known
connections, so you can still switch or open an assistant.
Repeated clicks cannot start another menu action while that work runs.

Menu delivery and routing have separate status. A failed menu update keeps the
previous menu available; use **Update or repair** to retry delivery.

## Manage the router

**Manage Router** provides setup checks, repair, assistant attachment, key replacement,
safe restart and removal. These commands use the same owners as the existing setup tools.
Restart lets running replies finish before checking that the service has restarted.
Removal restores owned assistant settings, then closes the menu and removes its
sign-in entry. See [uninstall](operations.md#uninstall) for what stays open and
what stays on the computer. After removal, opening SCG Router shows setup again.

Use **Updates** to check the available version and install it.
If the router still runs an older version after an update, choose
**Restart Router to use version …** to start the installed one.
Use **Help** for troubleshooting and a redacted support bundle.
The support command opens the folder containing the bundle so you can locate it.

New installations enable **Start at sign-in**. Clear its checkmark to opt out.
Repair and updates preserve your choice.
**Quit SCG Router menu** closes the controls while routing continues.
Open **SCG Router** again to restore access.
The existing Mac Switch Codex and Switch Claude shortcuts remain recovery entry points.

## Control window

On Windows and Linux, opening SCG Router while its menu is running shows a control window.
Linux desktops without a tray host show the same window.
It lists each assistant's current connection, then only the changes you can make,
such as **Claude: switch to OpenRouter**, with the same management actions.
Choose **Run action** to run the selected action once, or **Close** to leave.
The window closes after the action; reopen SCG Router for another action.
Only one control window opens per session. Windows sizes the window and list to
fit their content; unusually long choices can also scroll horizontally.
**Check setup** reports when setup is complete. If setup is unfinished, it offers
**Finish setup** or **Cancel** before starting the wizard or restarting an assistant.

## Linux desktops without a tray

An automatic sign-in start stays quiet when the host is absent.
Open SCG Router when you need the control window.
The tray helper retries registration when the host returns.
SCG Router does not install a desktop extension.

## Verification record

Build checks and offline transition tests do not establish desktop acceptance.
See [compatibility](compatibility.md) for actual client versions and reply evidence.
The [native acceptance matrix](native-installers.md#acceptance-matrix) remains required
for each intended platform and connection.
