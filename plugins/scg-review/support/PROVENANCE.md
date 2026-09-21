# Imported source provenance

Captured 2026-09-08 from the installed SCG review tooling. No credentials,
machine scanner configuration, caches or review receipts are included.
The hook adapter and its tests were imported unchanged from `.config/scg-agent-git-hooks`
under the maintainer user profile. One imported file now carries a reviewed
portability change, so this repository is no longer a byte-identical copy of
the imported adapter:

- `support/git-hooks/lib/scg_agent_git_hooks.py` accepts a platform-native
  absolute scanner path and passes the platform null device to
  `--gitleaks-ignore-path`, so the configured Gitleaks scanner runs on native
  Windows. The pin, hash, version, configuration-refusal and scanner-exit
  rules are unchanged.

`support/git-hooks/tests/test_gitleaks_pin_portability.py` is new in this
repository rather than imported; it is the portability coverage for that
change.

The three original skills came from the corresponding installed Codex skill
directories. Their plugin copies change only packaging and dependency routing.

| Hook file | SHA-256 |
| --- | --- |
| `support/git-hooks/bin/scg-review-state` | `a28314644d25b207a78a14cece7f2c9d574dcf7b270045ad74903bba512fe703` |
| `support/git-hooks/commit-msg` | `728992f27353081ad7699f34b6d9ddd281070b26c40b05ace98327bf41ee6580` |
| `support/git-hooks/lib/scg_agent_git_hooks.py` | `74699690825d8ed9a94ea9ed3a1de959ed1960c414a6e52d0e513049edf78baa` |
| `support/git-hooks/pre-commit` | `76118678585ee0f3dd9731d3cfad158c97eff976d533880d474452ed57a02d5c` |
| `support/git-hooks/tests/test_review_gate.py` | `5bee8151e378fd62ac15aa1dbec3370a7b30af27bf5c62c17d1a7f515d91db95` |
| `support/git-hooks/tests/test_gitleaks_pin_portability.py` | `bf6c068b4c761cda5af33bd5be8a4e3b6019135141ba630a2d9ea786e15458e6` |

Every row is the current content of this repository. Four rows still equal the
imported bytes; `lib/scg_agent_git_hooks.py` was imported as
`cdfd1a571df8eff2f37e9466fba01ca04684525ef92400094c19ca483c72266d`.
