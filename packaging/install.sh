#!/bin/sh
# Staff install step 1 (macOS): run the canonical unit tests from this package.
# Fails closed; never prints secrets. Copying files beside private state is a
# separate operator step at an idle router boundary.
set -eu
SRC="$(cd "$(dirname "$0")/.." && pwd)"
DST="$HOME/.codex/mixed-model-router"
cd "$SRC"
python3 -m unittest discover -s tests -t .
echo "Source tests passed in $SRC."
echo "Operator step: copy ONLY codex_router/router.py codex_router/tool_adapter.py codex_router/capabilities.py codex_router/compaction.py tools/probe_codex_runtime.py codex_router/update_reasoning_catalog.py codex_router/apply_catalogue.py tools/disable.py to $DST at an idle boundary."
echo "Never copy mixed-router-state.json activation.json mixed-models.json config-before.toml compatibility-release.json logs (private state stays local, never committed)."
