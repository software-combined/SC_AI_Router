"""Stable service entry point, installed at the router home root.

The service plist points here instead of `python -m ai_router` so no
symlink or per-release working directory is needed: the pointer file
resolves the active release at exec time, and every supervisor restart
follows updates without a plist rewrite. Not imported; executed with the
router home as its own location.
"""
import runpy
import sys
from pathlib import Path

home = Path(__file__).resolve().parent
try:
    name = (home / 'current').read_text(encoding='utf-8').strip().split('/')[-1]
except (OSError, ValueError):
    raise SystemExit('router pointer file missing: reinstall the router')
release = home / 'releases' / name
# Transition window: releases before the ai_router rename ship codex_router.
for pkg in ('ai_router', 'codex_router'):
    if (release / pkg).is_dir():
        module = pkg
        break
else:
    raise SystemExit('router release missing: reinstall the router')
try:
    import importlib.util as _ilu
    _rotate_spec = _ilu.spec_from_file_location(
        'router_service_rotate', release / 'packaging' / 'service.py')
    _rotate_mod = _ilu.module_from_spec(_rotate_spec)
    _rotate_spec.loader.exec_module(_rotate_mod)
    _rotate_mod.rotate_log(home / 'logs' / 'launchd.log')
except (OSError, ImportError, AttributeError):
    pass  # Rotation is hygiene; an older release without it still boots.
sys.path.insert(0, str(release))
runpy.run_module(module, run_name='__main__')
