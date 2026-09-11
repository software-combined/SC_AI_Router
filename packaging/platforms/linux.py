"""Linux systemd backend (Plan 056). Thin wrapper over packaging/systemd.py.

Owns user units, timer, restart, and uninstall. Knows nothing about feeds,
bundles, or config. Runs on Python 3.9+ like the installer.
"""
from pathlib import Path

import importlib.util

_spec = importlib.util.spec_from_file_location(
    'router_systemd', Path(__file__).resolve().parent.parent / 'systemd.py')
_systemd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_systemd)
systemd = _systemd  # unit-name constants for tests; lifecycle goes through Backend


class Backend:
    name = 'linux'

    def __init__(self, svc, run):
        self._svc = svc
        self._run = run

    def _manager(self, home):
        return _systemd.Manager(home, self._run)

    def check(self, home):
        self._manager(home).check()

    def install(self, python, home, state, release_dir, previous):
        self._manager(home).install(python, release_dir)

    def restart(self, home):
        self._manager(home).restart()

    def stop(self, home):
        self._manager(home).stop()

    def start_updates(self, home):
        self._manager(home).start_updates()

    def ensure_serving(self, home, state, version):
        del version  # systemd restart is synchronous enough; health is checked by the caller.
        return True

    def rollback_serving_ok(self, home, state, version):
        # Matches the pre-split behavior: the timer resumes and the restored
        # release is reported without a second serving assertion.
        del state, version
        self.start_updates(home)
        return True

    def pinned_release(self, home):
        return None  # No cached in-memory command on systemd; prune freely.

    def protect_secret(self, path):
        del path  # POSIX mode bits (0600) already own this.

    def uninstall(self, home):
        self._manager(home).uninstall()
