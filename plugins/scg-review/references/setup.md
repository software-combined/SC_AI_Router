# Machine setup

This release targets macOS/Linux with Python 3.11+, Git and an owner-approved
native Gitleaks executable. Windows provisioning and Claude Code packaging are
not implemented. Installing the plugin does not install providers or activate
Git hooks, and does not prove a completed review.

The **configured Gitleaks scanner** does run on native Windows as a standalone
scanner. The machine owner provisions a pinned `gitleaks.exe` and a
`config.json` by hand, then runs the scan from the repository being scanned,
with the intended changes staged:

```powershell
python "<absolute-plugin-root>\support\git-hooks\lib\scg_agent_git_hooks.py" scan
```

Windows prerequisites: Python 3.11 or newer, `git` available to that
interpreter, and an owner-approved native `gitleaks.exe` matching the pin. The
pin lives at `%USERPROFILE%\.config\scg-agent-git-hooks\config.json` and must
name an absolute executable path as a JSON value, either with forward slashes
(`C:/Tools/Gitleaks/gitleaks.exe`) or with escaped backslashes. Quote the script
path, because user and plugin paths commonly contain spaces, and use `python`
when that is the supported interpreter on the machine.

`bin/scg-review-state` is a Bash shim invoking `python3` and is not the Windows
entry point. Windows scanner support does **not** extend to `setup.py`
provisioning, Git hook installation or approval-receipt enforcement, and a
standalone scan does not complete the SCG pre-commit review gate: that gate
still requires the supported platform's setup check, installed hooks and an
approval receipt, so treat the Windows result as scanner evidence rather than an
approved review. The pin still requires an absolute binary path, an exact
version and a lowercase SHA-256, and provenance remains an owner record.

Run from a clone of the repository, or substitute the installed plugin's
absolute root for `plugins/scg-review`:

```sh
python3 plugins/scg-review/scripts/setup.py check --repo /absolute/path/to/repo
```

For first-time provisioning, have the machine owner supply a reviewed JSON
configuration. The scanner checksum must come from a trusted release or an
approved installation, not just whichever executable is on PATH. Its shape is:

```json
{
  "review_state_ttl_seconds": 86400,
  "required_lanes": ["correctness", "quality", "adversarial"],
  "gitleaks": {
    "binary": "/absolute/path/to/approved/gitleaks",
    "version": "approved-version",
    "sha256": "approved-64-character-lowercase-sha256",
    "provenance": "approved-release-or-installation-reference",
    "timeout_seconds": 60
  }
}
```

Then explicitly provision that repository:

```sh
python3 plugins/scg-review/scripts/setup.py install --repo /absolute/path/to/repo --config /absolute/path/to/approved-config.json
python3 plugins/scg-review/scripts/setup.py check --repo /absolute/path/to/repo
```

The installer validates the pin before running the executable, creates the
shared adapter only if absent, and refuses different existing files/config.
It preserves executable hooks in the repository's normal `.git/hooks` through
the existing adapter's chaining behaviour. A different effective `core.hooksPath`
requires a deliberate migration; the installer stops without overwriting it.
Plugin updates do not mutate machine configuration or refresh scanner pins.

### Refresh an existing installation

A plugin update changes the bundled hook adapter but never the installed copy,
and `setup.py check` compares the installed helper with the bundled bytes. After
updating to a release that changes the adapter, the check reports `Existing
adapter differs or is incomplete: lib/scg_agent_git_hooks.py; no files
replaced.` until the owner refreshes that one file:

```sh
cp "<plugin-root>/support/git-hooks/lib/scg_agent_git_hooks.py" \
   ~/.config/scg-agent-git-hooks/lib/scg_agent_git_hooks.py
python3 "<plugin-root>/scripts/setup.py" check --repo /absolute/path/to/repo
```

Replace only `lib/scg_agent_git_hooks.py`. Keep `config.json`, the hook scripts
and their modes, the repository's effective `core.hooksPath` and the review
receipts under `~/.cache/scg-agent-git-hooks/reviews/` exactly as they are. The
check passing is the evidence that the refresh is complete; the installer's
exact-match refusal for every other difference stays in place.

After local setup passes, verify provider access through the required review
calls. A missing preferred model can use a permitted fallback; no eligible model
for a required pass remains a blocker. New plugin versions take effect in a
new Codex task. Existing standalone skills or hard-coded AGENTS.md references
can still select an older copy; use the plugin's bundled skills explicitly
until the owner has migrated those references.

The hook checks receipt scope, age and required lane labels. It does not run
the scan/review itself or cryptographically prove reviewer identity. The skill
requires genuine reviews and scanning before approval; never invent receipts.
