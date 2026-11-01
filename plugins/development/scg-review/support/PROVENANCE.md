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

Release 0.7.2 binds receipts to the reviewed base and tree, rejects changed
scanner bytes before execution, and rechecks scope after chained hooks.
Its new merge shim uses the shared gate. Fresh POSIX setup restores executable
shim modes and validates the copied adapter before activation. The reliability
tests exercise these paths in disposable repositories.
The export resolves amendments from matching branch reflog evidence and checks
that the replaced and amended commits have the same parents. Missing or
ambiguous evidence stops export without changing saved receipts.

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
| `support/git-hooks/lib/scg_agent_git_hooks.py` | `ed143dfe219caca31f338eabf77f0b2c7220042f3cf5f4664d80ef90aae80857` |
| `support/git-hooks/pre-commit` | `2b33623f31fc1acddba480987fbd6769d88e232b2bd3494145d0723be741d98b` |
| `support/git-hooks/pre-merge-commit` | `388c1103d3fa84b870cc5bf8a108cc141335e19b1995702c7fb52bf7adb79efe` |
| `support/git-hooks/tests/test_review_gate.py` | `3bb1db985898559c78cb56988cda8b079fec669afaf8efdcfda3cea2c5b2558d` |
| `support/git-hooks/tests/test_gitleaks_pin_portability.py` | `14dede90f90ceddb2fee67e33b5f9b84bf29a9aac44d535eb364d92b161d8004` |
| `support/git-hooks/tests/test_interpreter_selection.py` | `6ee93ee55dfc9b0c2f47681c1089bc0163d25be4fb293e98e507d9de281506e5` |
| `support/git-hooks/tests/test_review_reliability.py` | `365ee15d125c30a5339b8a9e53816ed5856781be34601108d9e55a5d99432414` |

Every row is the current content of this repository. The helper was imported as
`cdfd1a571df8eff2f37e9466fba01ca04684525ef92400094c19ca483c72266d`.
