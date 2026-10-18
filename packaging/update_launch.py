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
import os
import runpy
import sys
from pathlib import Path

home = Path(__file__).resolve().parent
express = Path(__file__).name == 'express_launch.py'
try:
    pointer = home / 'current'
    name = pointer.resolve().name if pointer.is_symlink() else pointer.read_text(encoding='utf-8').strip().split('/')[-1]
except (OSError, ValueError):
    raise SystemExit('router pointer file missing: reinstall the router')
installer = home / 'releases' / name / 'packaging' / 'install.py'
# Native setup retains the updater separately from the serving release.
# Restoring older router code must not undo updater recovery fixes.
try:
    control = (home / 'control-version').read_text().strip()
    if control and all(part.isdigit() for part in control.split('.')):
        candidate = home / 'control' / control / 'packaging' / 'install.py'
        if candidate.is_file():
            installer = candidate
except OSError:
    pass
if not installer.is_file():
    raise SystemExit('router release missing: reinstall the router')
# Reloading a scheduler replaces its command while this process can still use
# the old release. Pruning must retain that origin until this pass exits.
os.environ['ROUTER_UPDATE_ORIGIN'] = ('control' if installer.parent.parent.parent == home / 'control'
                                      else name)
# The home launcher outlives the release that installed it: an explicit
# rollback points `current` at an older installer, and only 0.6.37+ takes
# --update. Ask the resolved release which applying verb it advertises so a
# rolled-back host keeps updating instead of exiting 2 every four hours.
try:
    installer_text = installer.read_text(encoding='utf-8')
except OSError:
    installer_text = ''
if express and "'--express-only'" not in installer_text:
    raise SystemExit(0)  # An older restored release keeps its regular updater.
verb = '--update' if "'--update'" in installer_text else '--check-update'
try:
    import importlib.util as _ilu
    _rotate_spec = _ilu.spec_from_file_location(
        'router_service_rotate', installer.with_name('service.py'))
    _rotate_mod = _ilu.module_from_spec(_rotate_spec)
    _rotate_spec.loader.exec_module(_rotate_mod)
    _rotate_mod.rotate_log(home / 'logs' / 'update.log')
except (OSError, ImportError, AttributeError):
    pass  # Rotation is hygiene; an older release without it still boots.
sys.argv = [str(installer), verb, '--home', str(home)]
if express:
    sys.argv.append('--express-only')
runpy.run_path(str(installer), run_name='__main__')
