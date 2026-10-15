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
- On macOS and Linux, the setup script needs any `python3`, plus `curl`,
  `tar` and either `shasum` or `sha256sum`. It supplies its own pinned
  Python runtime. Windows needs no Python.
- Linux needs a running systemd user manager in the signed-in desktop session;
  setup refuses a bare remote SSH session without one.
- Check [compatibility](compatibility.md) for the supported platforms and
  unfinished acceptance checks.

## Setup for Software Combined staff

Ask a maintainer for the setup script for your operating system. It needs no
GitHub account, token or repository access. It downloads the pinned Python
runtime and release bundle, verifies them and installs the service for your user.

The default channel is `stable`. Use `--channel=beta` on macOS/Linux or
`-Channel beta` in PowerShell only when you intend to follow pre-releases.
After setup, restart your assistant, choose a model and check that it replies.

## Choose or change assistants

The installer asks which assistant you use and where. Cancel at either
question changes no attachments. With no available dialog, the default is Codex.
A fresh install asks when it can show a dialog; `--choose-clients` asks again.
`ROUTER_NO_CLIENT_CHOOSER=1` suppresses the questions for unattended runs.
Explicit flags take precedence; attaching never detaches another client.

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
For Claude desktop, quit and reopen Claude, then choose Code, a folder and a
model. All gateway rows bill OpenRouter. [Claude setup](claude-code.md) explains
its separate profile and unfinished task-sharing checks.

Claude Code in the terminal keeps its subscription sign-in. Never set
`ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN`; either overrides that sign-in.

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
python3.14 packaging/release.py --out dist --url-base "file://$PWD/dist"
python3.14 packaging/install.py --feed "file://$PWD/dist/latest.json"
```

On Windows, run the build and install commands in PowerShell:

```powershell
py -3 packaging/release.py --out dist --url-base "file://$PWD/dist"
py -3 packaging/install.py --feed "file://$PWD/dist/latest.json"
```

Use Python 3.14 for these commands. The installer still supports Python 3.9
for an existing pinned-runtime setup. See [contributing](../CONTRIBUTING.md)
for development checks and [operations](operations.md) for update, rollback,
uninstall and diagnostic commands.
