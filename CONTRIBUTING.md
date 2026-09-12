# Contributing

Thanks for taking the time. This page covers the mechanics; `AGENTS.md` holds
the same rules in the form coding agents read, and `docs/architecture.md`
says where new code belongs.

## Before you start

- Bugs and feature requests go through GitHub issues. For a suspected
  vulnerability, follow [SECURITY.md](SECURITY.md) instead.
- Small fixes can go straight to a pull request. For anything larger, open an
  issue first so the approach can be agreed before the work.

## Set up

The runtime needs Python 3.14 and nothing else; installer scripts stay
Python 3.9-compatible. Clone the repository and run the gates:

```sh
python3.14 -m unittest discover -s tests -t .
python3.14 -m compileall -q ai_router tools tests packaging
python3.14 tools/check_source_limits.py
python3.14 tools/check_policy_scans.py
```

All tests run offline; nothing in `tests/` may reach the network or touch a
real router home.

## Branches and pull requests

- Branch from `develop` and open the pull request against `develop`. `main`
  only receives release merges from `develop`.
- Commit subjects use `<type>: <short summary>` with type `feat`, `fix`,
  `refactor`, `test`, `chore` or `docs`.
- Every user-visible change updates `CHANGELOG.md` and `packaging/VERSION`
  (semver). Maintainers cut releases by tagging `v<VERSION>`.
- Keep the source limits: modules 250 lines soft and 400 hard, entrypoints
  and tools 400/700, tests 300/500. `tools/check_source_limits.py` reports
  the numbers.
- A change to `ai_router/models.json` needs the
  `python3.14 -m ai_router.models check` output and a probe result in the
  pull request, or a deliberate `tier: preview`.

## Design rules pull requests are checked against

- Runtime code uses the standard library only.
- An upstream provider is one entry in `ai_router/provider_defs.py`
  consumed by adapters; a provider with a different wire format is a new
  adapter, never a branch in the request path. Provider hosts, key names and
  catalogue URLs live nowhere else under `ai_router/`.
- Loopback only, per-install path token, subscription headers never
  accompany an externally billed request, and no request content in logs.
- Never commit state files, activation receipts, catalogues, logs, keys or
  tokens.

## Licence

By contributing you agree that your contributions are licensed under the
[Apache License 2.0](LICENSE), as section 5 of that licence provides.
