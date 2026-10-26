# Imported source provenance

## Security review method

The security-review skill adapts the defensive tracing and independent
refutation method in [Cloudflare security-audit-skill](https://github.com/cloudflare/security-audit-skill)
at commit `c1c8a8c1471069fb0e188eeaff69b8e8db6564a8`, inspected on 22 October 2026.
The reference was `skills/security-audit/`: `SKILL.md`, `HUNTING.md`,
`VALIDATION-AND-REPORTING.md`, `ATTACK-CLASSES.md`, `AI-AND-LLM.md` and
`SUPPLY-CHAIN-AND-RELEASE.md`. Its [MIT notice](cloudflare-LICENSE.txt) is retained.
SCG supplies its own staged-tree scope, Markdown report contract and commit gate.
It does not bundle Cloudflare's audit engine, validators or execution machinery.

## Original review tooling

Captured 2026-09-08 from the installed SCG review tooling. No credentials,
machine scanner configuration, caches or review receipts are included.
The hook adapter and its tests were imported from `.config/scg-agent-git-hooks`
under the maintainer user profile. Reviewed changes now sit on top of that
import, so no row below is still the imported bytes:

- `support/git-hooks/lib/scg_agent_git_hooks.py` accepts a platform-native
  absolute scanner path and passes the platform null device to
  `--gitleaks-ignore-path`, so the configured Gitleaks scanner runs on native
  Windows. The pin, hash, version, configuration-refusal and scanner-exit
  rules are unchanged.
- The same helper chains a repository hook through Git's hook runner on
  Windows, preserving its declared interpreter because CreateProcess cannot
  run a script directly. The direct exec on macOS/Linux is unchanged.

Native-Windows enforcement is a second reviewed change across the adapter:

- `support/git-hooks/pre-commit`, `support/git-hooks/commit-msg` and
  `support/git-hooks/bin/scg-review-state` read the helper interpreter from
  `config.json` (an explicit absolute path), so the one set of Bash shims also
  runs under Git for Windows, which ships bash but no `python3` on PATH. A
  POSIX installation without the setting keeps the historical `python3`, so
  its config bytes and behaviour are unchanged.
- `scripts/setup.py` no longer refuses `os.name != "posix"`; it resolves the
  interpreter (an explicit config value, the router's pinned runtime on
  Windows, or `python3` on POSIX), probes an absolute one before writing, and
  records the resolved path in the installed `config.json`.

`support/git-hooks/tests/test_gitleaks_pin_portability.py` and
`support/git-hooks/tests/test_interpreter_selection.py` are new in this
repository rather than imported; they are the portability and
interpreter-selection coverage for those changes. `test_review_gate.py` is the
imported end-to-end module, extended so the receipt gate runs on Windows too.

The three original skills came from the corresponding installed Codex skill
directories. Their plugin copies change only packaging and dependency routing.

| Hook file | SHA-256 |
| --- | --- |
| `support/git-hooks/bin/scg-review-state` | `0963d64953ef111793352370dd2886b995132e9ea97261276e53ed86b788e869` |
| `support/git-hooks/commit-msg` | `2cbaa16377d52c890c3d64488d7e8b404859f44f059420388ae0c599a3528362` |
| `support/git-hooks/lib/scg_agent_git_hooks.py` | `ad249c614a172b7936ac773edc2722cfe3098d5aaa94917b5abb6017f84230f2` |
| `support/git-hooks/pre-commit` | `2b33623f31fc1acddba480987fbd6769d88e232b2bd3494145d0723be741d98b` |
| `support/git-hooks/tests/test_review_gate.py` | `e204608d2ad51319bab97125b4e842290db95c351eedfd708ce4b7d6e43d134d` |
| `support/git-hooks/tests/test_gitleaks_pin_portability.py` | `87d7fafdc3a90e93214e35b4e9059d82e664d3dc545acc35b65aec6b20b99482` |
| `support/git-hooks/tests/test_interpreter_selection.py` | `a82500c6dc2160c056df95238f70207c302ce76d590f44b63a34bc1aaed7f198` |

Every row is the current content of this repository. The helper was imported as
`cdfd1a571df8eff2f37e9466fba01ca04684525ef92400094c19ca483c72266d`.
