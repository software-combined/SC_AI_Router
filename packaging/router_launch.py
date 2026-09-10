"""Stable service entry point, installed at the router home root.

The service plist points here instead of `python -m codex_router` so no
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
if not (release / 'codex_router').is_dir():
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
runpy.run_module('codex_router', run_name='__main__')
