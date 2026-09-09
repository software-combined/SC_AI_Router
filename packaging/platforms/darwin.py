"""macOS launchd backend (Plan 056). Moved verbatim from install.py.

Owns plists, reload convergence, TERM handover, updater adoption, serving
assertion, and uninstall. Knows nothing about feeds, bundles, or config.
Runs on Python 3.9+ like the installer.
"""
import os
from pathlib import Path


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

    def install(self, python, home, state, release_dir, previous):
        """Write plists and hand over; mirrors the pre-split else-branch."""
        svc, LABEL, UPDATE_LABEL = self._svc, self._svc.LABEL, self._svc.UPDATE_LABEL
        uid, agents = self._uid(), self._agents()
        needs_reload = svc.main_plist_needs_reload(uid, python, home, state, agents)
        svc.write_plist(agents / (LABEL + '.plist'), svc.render_plist(python, home, state))
        svc.write_plist(agents / (UPDATE_LABEL + '.plist'), svc.render_update_plist(python, home))
        if previous is None:
            svc.restart_service(uid, agents)
        elif needs_reload:
            if not svc.reload_main_service(uid, agents):
                raise SystemExit(f'router service reload failed for {LABEL}')
        else:
            # Nothing launchd owns changed, so hand over in place. TERM lets
            # the old process drain in-flight requests while launchd keeps
            # the listening socket and respawns into the new pointer, so no
            # connection is refused and no bootout can strand the machine.
            self.restart(home)
        if not svc.ensure_updater(uid, python, home, agents):
            # The router is fine; only the update channel is not. Say so
            # rather than exiting clean over a machine that will never
            # update itself again.
            print('warning: the scheduled updater is not loaded; run the '
                  'installer again to restore automatic updates')

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
        return self._svc.loaded_updater_release(self._uid(), home)

    def uninstall(self, home):
        svc = self._svc
        uid, agents = self._uid(), self._agents()
        self._run(['launchctl', 'bootout', f'gui/{uid}/{svc.LABEL}'], capture_output=True)
        self._run(['launchctl', 'bootout', f'gui/{uid}/{svc.UPDATE_LABEL}'], capture_output=True)
        for name in (svc.LABEL, svc.UPDATE_LABEL):
            try:
                (agents / (name + '.plist')).unlink()
            except FileNotFoundError:
                pass
