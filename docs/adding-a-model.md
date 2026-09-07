# Adding a model

One command derives the row from live OpenRouter metadata:

```sh
python3.14 -m codex_router.models add <slug> --dry-run   # inspect first
python3.14 -m codex_router.models add <slug> --probe     # verify, then write
```

Without `--probe` the row lands as `tier: preview`: it appears in the
picker labelled Preview but is not trusted yet. With `--probe` the base
tool round trip runs on the installed router; a pass writes
`tier: verified`, anything else stays `preview` and appends a row to
`docs/compatibility.md`. Validate with
`python3.14 -m codex_router.models check` (`0 problems` required) and
remove with `python3.14 -m codex_router.models remove <slug>`.

Preview models route exactly like verified ones; only the picker label
and ordering differ. A model that needs behaviour the adapter does not
have (a new quirk type) is a normal code change and release, not a data
row.
