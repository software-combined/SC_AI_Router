# Imported source provenance

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
- The same helper chains a repository hook through the shell Git for Windows
  provides, because CreateProcess cannot exec a shell script directly. The
  direct exec on macOS/Linux is unchanged.

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
| `support/git-hooks/lib/scg_agent_git_hooks.py` | `f91709bfee9207eb4eeea072cc475de6c17555cc2fa83c535e49073bfed61e3d` |
| `support/git-hooks/pre-commit` | `2b33623f31fc1acddba480987fbd6769d88e232b2bd3494145d0723be741d98b` |
| `support/git-hooks/tests/test_review_gate.py` | `5eae5dddfa3c9961da77d4b4806056bd3a59a270734318492534f3aaa12620f7` |
| `support/git-hooks/tests/test_gitleaks_pin_portability.py` | `d551856d39ac756205e82ca94ae0a3b342cefa79f7f056d8ba98946934d40f9e` |
| `support/git-hooks/tests/test_interpreter_selection.py` | `e25beb090aca3406cc3bb73c13fe6c6451319626195e57c54e8aca3efadbfa7b` |

Every row is the current content of this repository. The helper was imported as
`cdfd1a571df8eff2f37e9466fba01ca04684525ef92400094c19ca483c72266d`.
