# Machine setup

This release targets macOS/Linux with Python 3.11+, Git and an owner-approved
native Gitleaks executable. Windows provisioning and Claude Code packaging are
not implemented. Installing the plugin does not install providers or activate
Git hooks, and does not prove a completed review.

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

After local setup passes, verify provider access through the required review
calls. A missing preferred model can use a permitted fallback; no eligible model
for a required pass remains a blocker. New plugin versions take effect in a
new Codex task. Existing standalone skills or hard-coded AGENTS.md references
can still select an older copy; use the plugin's bundled skills explicitly
until the owner has migrated those references.

The hook checks receipt scope, age and required lane labels. It does not run
the scan/review itself or cryptographically prove reviewer identity. The skill
requires genuine reviews and scanning before approval; never invent receipts.
