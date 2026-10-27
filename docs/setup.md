# Router setup

Start with the [README](../README.md#get-started) for the ordinary staff path.
This guide covers prerequisites and alternatives. Setup changes this computer's
assistant settings and adds a background service and automatic update jobs.

## Before you start

- Install the assistant you want to use. Keep its subscription sign-in for
  Codex or Claude Code in the terminal.
- Have an OpenRouter key for models billed to OpenRouter. Enter it only in the
  setup window; a coding agent must never handle it.
- Optional: an AWS Bedrock API key enables the Bedrock models. Create it in
  the AWS console for one region, enable the models you want in that
  region, and enter the key only in the setup window when the router asks
  for AWS Bedrock. Set `bedrock_region` in the router state file to that
  region (default `us-east-1`) and restart the router after changing it.
- Native installers include Python and graphical setup. They need no Git.
  The older macOS/Linux setup script still needs `python3`, `curl`, `tar`
  and a SHA-256 tool.
- Linux needs a running systemd user manager in the signed-in desktop session;
  setup refuses a bare remote SSH session without one.
- Check [compatibility](compatibility.md) for the supported platforms and
  unfinished acceptance checks.

## Setup for Software Combined staff

Download SCG Router from `https://hub.softwarecombined.com/install` and choose
your computer. Open the DMG on macOS, EXE on Windows, or AppImage on Ubuntu.
Ubuntu may require allowing execution in the file's Properties window.
No separate FUSE installation is needed. These packages have no paid publisher
certificate. Device policy can still block them; contact IT if that happens.

The SCG Router app saves setup in your user account. After setup, you can
delete the download or eject the disk image. Reopen SCG Router to check setup,
repair it, connect another assistant, replace your key, renew download sign-in
or remove the router. Reopening preserves the existing channel and settings.
With the same or an older download, **Update or repair** restores the service
using its installed release. **Connect another assistant** adds your selection
while preserving existing connections.

The default channel is `stable`. Use `--channel=beta` on macOS/Linux or
`-Channel beta` in PowerShell only when you intend to follow pre-releases.
After setup, restart your assistant, choose a model and check that it replies.
Native setup also checks installed SC tools and asks you to confirm they work
in a fresh assistant session. It leaves unfinished setup pending.

## Choose or change assistants

The installer asks which assistant you use and where. Cancel at either
question changes no attachments or subscription choices. With no available dialog, the default is Codex.
A fresh install asks when it can show a dialog; `--choose-clients` asks again.
`ROUTER_NO_CLIENT_CHOOSER=1` suppresses the questions for unattended runs.
Explicit flags take precedence; attaching never detaches another client.
Updates without a selection retain the attached assistants. If no attachments
are recorded, setup uses the saved selection, then Codex for a legacy install.
`--clients` selects only the requested additions, including after service-only
setup. `--client none` conflicts with an attachment request.

From a source checkout, with Python 3.14, use the command for your intended setup:

| Assistant | Command |
|---|---|
| Codex app or terminal | `python3.14 packaging/install.py --clients codex` |
| Claude Code terminal | `python3.14 packaging/install.py --clients claude` |
| Claude desktop | `python3.14 packaging/install.py --clients none --desktop` |
| Both Claude surfaces | `python3.14 packaging/install.py --clients claude --desktop` |
| Service only | `python3.14 packaging/install.py --client none` |

A bootstrap install needs no checkout. Re-run the current setup script with
`--choose-clients` (Windows: `-ChooseClients`), or use the
[installed interpreter and installer](claude-code.md#setup).
For Claude desktop, choose **Claude**, then **OpenRouter**, in the SCG Router menu.
Claude restarts on OpenRouter. The first switch sets up the OpenRouter profile; switch back and forth once to bring your saved Code tasks.
Then choose Code, a folder and a
model. All gateway rows bill OpenRouter. [Claude setup](claude-code.md) explains
its separate profile and unfinished task-sharing checks.

Claude Code in the terminal keeps its subscription sign-in. Never set
`ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN`; either overrides that sign-in.
The one exception is an install without a Claude subscription
(`--claude-mode none`, or **No subscription** in the key window): there the
installer sets `ANTHROPIC_AUTH_TOKEN` to a placeholder, so Claude Code needs no
Claude sign-in and every reply goes to OpenRouter.

## What the installer does

It verifies the bundle checksum, tests the runtime, installs the service and
writes the chosen client configuration. A missing key opens the setup window.
If it does not appear, re-run with `--setup` to restart the current release
with a fresh setup link. A key exported in the invoking shell is not passed to
the installed service. `ROUTER_NO_KEY_WINDOW=1` suppresses only the dialog.

The default router home is `~/.codex/mixed-model-router`, or
`%USERPROFILE%\.codex\mixed-model-router` on Windows. A bootstrap installs
the same installer at `<home>/releases/<version>/packaging/install.py`,
where `<version>` is recorded in `<home>/current`. Use its pinned interpreter
at `<home>/runtime/python/bin/python3.14` (`python.exe` on Windows)
when the computer has no Python 3.14. Source installs can run `--preflight`
to check prerequisites or `--dry-run` to see planned changes without writing.
Bootstrap and scheduled updates pass their retained interpreter to the installer.
An explicit eligible `--python` wins; otherwise an eligible running interpreter
precedes Python found through `PATH`. Older installer interpreters still discover
Python 3.14 before starting the router.

<p><img src="assets/key-window-macos.png" alt="The first-run key window on macOS" width="400"></p>
The setup window checks your key before saving it on this computer.
<p><img src="assets/update-dialog-macos.png" alt="The update notice on macOS" width="400"></p>
Updates install themselves. This notice asks for an assistant restart when new
models need to appear in its picker.

## Install from source

This alternative requires Git and Python 3.14. The install command
changes your local assistant settings and registers the service and update jobs.
Run from the cloned repository:

```sh
git clone https://github.com/software-combined/SC_AI_Router.git
cd SC_AI_Router
ROUTER_DIST_URL="$(python3.14 -c 'from pathlib import Path; print((Path.cwd() / "dist").as_uri())')"
python3.14 packaging/release.py --out dist --url-base "$ROUTER_DIST_URL"
python3.14 packaging/install.py --feed "$ROUTER_DIST_URL/latest.json"
```

On Windows, run the build and install commands in PowerShell:

```powershell
$RouterDist = Join-Path $PWD 'dist'
$RouterDistUrl = ([uri]$RouterDist).AbsoluteUri
py -3.14 packaging/release.py --out $RouterDist --url-base $RouterDistUrl
py -3.14 packaging/install.py --feed "$RouterDistUrl/latest.json"
```

Use Python 3.14 for these commands. The installer still supports Python 3.9
for an existing pinned-runtime setup. See [contributing](../CONTRIBUTING.md)
for development checks and [operations](operations.md) for update, rollback,
uninstall and diagnostic commands.
