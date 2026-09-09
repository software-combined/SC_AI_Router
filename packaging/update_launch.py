"""Stable scheduled-update entry point, installed at the router home root.

The updater plist points here instead of at a per-release `install.py` path,
so launchd's in-memory copy never goes stale when a release is installed or
pruned. Rewriting a loaded plist does not update launchd's copy, so a plist
that names a release path keeps running that release's installer long after
the release is gone -- which is how a pruned installer ends up fetching a
feed it no longer understands. This file resolves `current` at exec time,
exactly like router_launch.py. Not imported; executed with the router home
as its own location.
"""
import runpy
import sys
from pathlib import Path

home = Path(__file__).resolve().parent
try:
    name = (home / 'current').read_text(encoding='utf-8').strip().split('/')[-1]
except (OSError, ValueError):
    raise SystemExit('router pointer file missing: reinstall the router')
installer = home / 'releases' / name / 'packaging' / 'install.py'
if not installer.is_file():
    raise SystemExit('router release missing: reinstall the router')
try:
    import importlib.util as _ilu
    _rotate_spec = _ilu.spec_from_file_location(
        'router_service_rotate', home / 'releases' / name / 'packaging' / 'service.py')
    _rotate_mod = _ilu.module_from_spec(_rotate_spec)
    _rotate_spec.loader.exec_module(_rotate_mod)
    _rotate_mod.rotate_log(home / 'logs' / 'update.log')
except (OSError, ImportError, AttributeError):
    pass  # Rotation is hygiene; an older release without it still boots.
sys.argv = [str(installer), '--check-update', '--home', str(home)]
runpy.run_path(str(installer), run_name='__main__')
