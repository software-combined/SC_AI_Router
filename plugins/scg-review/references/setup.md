# Machine setup

This release targets macOS, Linux and native Windows with Python 3.11+, Git and
an owner-approved native Gitleaks executable. Installing the plugin does not
install providers or activate Git hooks, and does not prove a completed review.

## Interpreter

The hook helper runs on an interpreter recorded in the config as an absolute
path, so on Windows the gate never depends on PATH discovery:

- Windows defaults to the Python runtime shipped by the SCG router,
  `%USERPROFILE%\.codex\mixed-model-router\runtime\python\python.exe`, or the
  same path under `ROUTER_HOME` when that variable is set. Native Windows has
  no `python3` on PATH, so a missing router runtime is a blocker rather than a
  reason to search for another interpreter.
- macOS and Linux keep the historical `python3` when the setting is absent, so
  an existing installation and its config bytes are unchanged.
- An explicit `interpreter` wins on every platform. It must be absolute, exist
  and be a Python 3.11 or newer that runs; the installer probes it before
  writing anything.

Git for Windows runs the Bash hook shims, which read that value from
`config.json`. Run `bin/scg-review-state` in Git Bash on Windows; it uses the
same interpreter for `approve`, `status` and `scan`.

## Reviewer preferences

Each user sets `review_models` in their local hook `config.json`, with separate
`codex` and `claude-code` profiles. Each pass has
an ordered list of callable `model@effort` choices; the first available suitable
entry is preferred, and later entries are permitted fallbacks. Use
`model@unavailable` when that model has no effort setting. For example, replace
these illustrative identifiers with models available in your client:

```json
"review_models": {
  "codex": {
    "simplification": ["your-codex-model@high"],
    "correctness": ["your-codex-model@high", "your-fallback@unavailable"],
    "quality": ["your-codex-model@high"],
    "adversarial": ["your-codex-model@high"],
    "security": ["your-security-model@high"]
  },
  "claude-code": {
    "simplification": ["your-claude-model@high"],
    "correctness": ["your-claude-model@high"],
    "quality": ["your-claude-model@high"],
    "adversarial": ["your-claude-model@high"],
    "security": ["your-security-model@high"]
  }
}
```

Preserve the scanner pin, interpreter, required lanes and receipt lifetime.
Run `~/.config/scg-agent-git-hooks/bin/scg-review-state models --client codex`
(or `--client claude-code`) to read back the choices. The skill requires this
before dispatch. A missing client profile never falls back to another client's
choices. The hook does not call a
provider or certify a model's capability; it records the completed lane choices.
Receipts must contain exactly the current required lanes. An old adapter without `models` needs the refresh
below before using this release. No plugin update selects models for the owner.

### Upgrade from three lanes

Version 0.7.0 adds a mandatory security lane. The new setup check refuses a
three-lane configuration without changing it. With the owner's authorization,
back up the local config and add `security` after `adversarial` in
`required_lanes`. Add the owner's ordered `security` choices to every configured
client profile. Preserve all other choices, scanner pins, interpreter and lifetime.
No shared model or effort is supplied, and there is no implicit cross-client
fallback. Select only routes available to that client; a Claude subscription
does not by itself provide a GPT route.

Run the new setup check and `models --client codex` and/or
`models --client claude-code`. Old three-lane receipts no longer satisfy the
gate. A new genuine four-lane review is required; never rewrite old receipts.
Claude Code loads the bundled `scg-review:review-security` agent in a fresh
session. The parent must pass its selected model and effort; the agent omits both.
Codex uses the bundled `security-review` skill in a fresh child context.
Verify both clients' actual new-session pickup before claiming local delivery.
Claude Code's [subagent reference](https://code.claude.com/docs/en/sub-agents#choose-an-effort-level)
documents per-invocation effort for version 2.1.292 and later. On older clients,
use a verified matching inherited session effort or stop at the selection gap.
Do not invent an effort field or silently change the owner's choice.

## Gitleaks scanner

The configured Gitleaks scanner is a pinned native executable: an absolute
path, an exact version and a lowercase SHA-256, with provenance recorded by the
owner. It can also run on its own, from the repository being scanned, with the
intended changes staged:

```powershell
python "<absolute-plugin-root>\support\git-hooks\lib\scg_agent_git_hooks.py" scan
```

The pin lives at `%USERPROFILE%\.config\scg-agent-git-hooks\config.json`
(macOS/Linux: `~/.config/scg-agent-git-hooks/config.json`) and must name an
absolute executable path as a JSON value, either with forward slashes
(`C:/Tools/Gitleaks/gitleaks.exe`) or with escaped backslashes. Quote the script
path, because user and plugin paths commonly contain spaces. A standalone scan
is scanner evidence, not a completed review: the gate still requires the
installed hooks and an approval receipt.

Run from a clone of the repository, or substitute the installed plugin's
absolute root for `plugins/scg-review`:

```sh
python3 plugins/scg-review/scripts/setup.py check --repo /absolute/path/to/repo
```

For first-time provisioning, have the machine owner supply a reviewed JSON
configuration. The scanner checksum must come from a trusted release or an
approved installation, not just whichever executable is on PATH. Save the JSON
configuration as UTF-8. Its shape is:

```json
{
  "review_state_ttl_seconds": 86400,
  "required_lanes": ["correctness", "quality", "adversarial", "security"],
  "gitleaks": {
    "binary": "/absolute/path/to/approved/gitleaks",
    "version": "approved-version",
    "sha256": "approved-64-character-lowercase-sha256",
    "provenance": "approved-release-or-installation-reference",
    "timeout_seconds": 60
  }
}
```

`interpreter` is optional. Omit it on macOS/Linux to keep `python3` and on
Windows to accept the router's runtime; set it to override either default:

```json
{
  "interpreter": "C:/Program Files/Python 3.14/python.exe",
  "review_state_ttl_seconds": 86400,
  "required_lanes": ["correctness", "quality", "adversarial", "security"],
  "gitleaks": { "...": "..." }
}
```

Then explicitly provision that repository:

```sh
python3 plugins/scg-review/scripts/setup.py install --repo /absolute/path/to/repo --config /absolute/path/to/approved-config.json
python3 plugins/scg-review/scripts/setup.py check --repo /absolute/path/to/repo
```

On native Windows, run the same commands in PowerShell with the router's runtime:

```powershell
& "$env:USERPROFILE\.codex\mixed-model-router\runtime\python\python.exe" "<plugin-root>\scripts\setup.py" install --repo "<path>" --config "<path>"
& "$env:USERPROFILE\.codex\mixed-model-router\runtime\python\python.exe" "<plugin-root>\scripts\setup.py" check --repo "<path>"
```

The installer records the resolved interpreter in the installed `config.json`,
which is what the shims read.

The installer validates the pin and the interpreter before running either
executable, creates the shared adapter only if absent, and refuses different
existing files/config. It preserves executable hooks in the repository's
normal `.git/hooks` through the existing adapter's chaining behaviour, and on
Windows it uses Git's hook runner to preserve the hook's declared interpreter.
A different effective `core.hooksPath` requires a deliberate
migration; the installer stops without overwriting it. Plugin updates do not
mutate machine configuration or refresh scanner pins.

### Refresh an existing installation

A plugin update changes the bundled hook adapter but never the installed copy,
and `setup.py check` compares each installed file with the bundled bytes. After
updating to a release that changes the adapter, the check names every file that
differs, for example `Existing adapter differs or is incomplete: pre-commit; no
files replaced.` Copy those files from the bundle over the installed copies:

```sh
cp "<plugin-root>/support/git-hooks/pre-commit" \
   "<plugin-root>/support/git-hooks/commit-msg" ~/.config/scg-agent-git-hooks/
cp "<plugin-root>/support/git-hooks/bin/scg-review-state" ~/.config/scg-agent-git-hooks/bin/
cp "<plugin-root>/support/git-hooks/lib/scg_agent_git_hooks.py" ~/.config/scg-agent-git-hooks/lib/
chmod +x ~/.config/scg-agent-git-hooks/pre-commit \
         ~/.config/scg-agent-git-hooks/commit-msg \
         ~/.config/scg-agent-git-hooks/bin/scg-review-state
python3 "<plugin-root>/scripts/setup.py" check --repo /absolute/path/to/repo
```

Keep `config.json` (including the recorded `interpreter`), the repository's
effective `core.hooksPath` and review receipts unchanged during an adapter refresh.
The separately authorized three-to-four-lane configuration migration above is
the only additional change needed for 0.7.0. The check passing
is the evidence that the refresh is complete; the installer's exact-match
refusal for every other difference stays in place.

After local setup passes, verify provider access through the required review
calls. An unavailable selected model can use a permitted fallback; no eligible model
for a required pass remains a blocker. New plugin versions take effect in a
new Codex task. Existing standalone skills or hard-coded AGENTS.md references
can still select an older copy; use the plugin's bundled skills explicitly
until the owner has migrated those references.

The hook checks receipt scope, age and required lane labels. It does not run
the scan/review itself or cryptographically prove reviewer identity. The skill
requires genuine reviews and scanning before approval; never invent receipts.

After committing, use [the review export](export.md) to share sanitized,
commit-bound evidence with the PR. Exporting never creates an approval.
