#!/bin/sh
# Staff install step 1 (macOS): run the canonical unit tests from this package.
# Fails closed; never prints secrets. Copying files beside private state is a
# separate operator step at an idle router boundary.
set -eu
SRC="$(cd "$(dirname "$0")/.." && pwd)"
DST="$HOME/.codex/mixed-model-router"
cd "$SRC"
python3 -m unittest test_mixed_router test_tool_adapter test_capabilities test_compaction test_apply_catalogue test_packaging
echo "Source tests passed in $SRC."
echo "Operator step: copy ONLY mixed_router.py tool_adapter.py capabilities.py compaction.py probe_codex_runtime.py update_reasoning_catalog.py apply_catalogue.py disable.py to $DST at an idle boundary."
echo "Never copy mixed-router-state.json activation.json mixed-models.json config-before.toml compatibility-release.json logs (private state stays local, never committed)."
