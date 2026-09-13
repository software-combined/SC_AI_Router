"""macOS launchd backend (Plan 056). Moved verbatim from install.py.

Owns plists, reload convergence, TERM handover, updater adoption, serving
assertion, and uninstall. Knows nothing about feeds, bundles, or config.
Runs on Python 3.9+ like the installer. Plist rendering and reload live in
packaging/launchd.py (Plan 103), loaded here the way linux.py loads
systemd.py; service only supplies the patchable seams and the labels.
"""
import os
from pathlib import Path

import importlib.util

_spec = importlib.util.spec_from_file_location(
    'router_launchd', Path(__file__).resolve().parent.parent / 'launchd.py')
_launchd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_launchd)


class Backend:
    name = 'darwin'

    def __init__(self, svc, run):
        self._svc = svc
        self._run = run

    def check(self, home):
        del home  # No precondition beyond a signed-in user session.

    def _uid(self):
        return os.getuid()

    def _agents(self):
        return Path.home() / 'Library' / 'LaunchAgents'

    def _seams(self):
        """Patchable service seams for the launchd helpers, read at call time."""
        svc = self._svc
        return {'sleep': svc._sleep, 'unload_timeout': svc.UNLOAD_TIMEOUT_S,
                'load_timeout': svc.LOAD_TIMEOUT_S}

    def install(self, python, home, state, release_dir, previous):
        """Write plists and hand over; mirrors the pre-split else-branch."""
        svc = self._svc
        uid, agents = self._uid(), self._agents()
        needs_reload = _launchd.main_plist_needs_reload(
            self._run, uid, python, home, state, agents)
        _launchd.write_plist(agents / (svc.LABEL + '.plist'),
                             _launchd.render_plist(python, home, state))
        _launchd.write_plist(agents / (svc.UPDATE_LABEL + '.plist'),
                             _launchd.render_update_plist(python, home))
        if previous is None:
            _launchd.restart_service(self._run, uid, agents, **self._seams())
        elif needs_reload:
            if not _launchd.reload_main_service(self._run, uid, agents, **self._seams()):
                raise SystemExit(f'router service reload failed for {svc.LABEL}')
        else:
            # Nothing launchd owns changed, so hand over in place. TERM lets
            # the old process drain in-flight requests while launchd keeps
            # the listening socket and respawns into the new pointer, so no
            # connection is refused and no bootout can strand the machine.
            self.restart(home)
        if not _launchd.ensure_updater(self._run, uid, python, home, agents,
                                       **self._seams()):
            # The router is fine; only the update channel is not. Say so
            # rather than exiting clean over a machine that will never
            # update itself again.
            print('warning: the scheduled updater is not loaded; run the '
                  'installer again to restore automatic updates')
        if (home / 'express_launch.py').is_file():
            _launchd.write_plist(agents / (_launchd.EXPRESS_LABEL + '.plist'),
                                _launchd.render_update_plist(python, home, express=True))
            if not _launchd.ensure_updater(self._run, uid, python, home, agents,
                                          express=True, **self._seams()):
                raise SystemExit('Express update job could not be loaded')

    def restart(self, home):
        self._run(['launchctl', 'kill', 'TERM', f'gui/{self._uid()}/{self._svc.LABEL}'],
                  capture_output=True)

    def stop(self, home):
        self._run(['launchctl', 'bootout', f'gui/{self._uid()}/{self._svc.LABEL}'],
                  capture_output=True)

    def start_updates(self, home):
        return None  # launchd starts the updater job on load; nothing to do.

    def ensure_serving(self, home, state, version):
        return self._svc.ensure_serving(self._uid(), home, state, self._agents(),
                                        version=version)

    def rollback_serving_ok(self, home, state, version):
        # Verify a loaded job serves the restored release; a TERM cannot
        # revive a job that is not loaded.
        return bool(self.ensure_serving(home, state, version))

    def pinned_release(self, home):
        return _launchd.loaded_updater_release(self._run, self._uid(), home)

    def protect_secret(self, path):
        del path  # POSIX mode bits (0600) already own this.

    def uninstall(self, home):
        svc = self._svc
        uid, agents = self._uid(), self._agents()
        self._run(['launchctl', 'bootout', f'gui/{uid}/{svc.LABEL}'], capture_output=True)
        self._run(['launchctl', 'bootout', f'gui/{uid}/{svc.UPDATE_LABEL}'], capture_output=True)
        self._run(['launchctl', 'bootout', f'gui/{uid}/{_launchd.EXPRESS_LABEL}'], capture_output=True)
        for name in (svc.LABEL, svc.UPDATE_LABEL, _launchd.EXPRESS_LABEL):
            try:
                (agents / (name + '.plist')).unlink()
            except FileNotFoundError:
                pass
