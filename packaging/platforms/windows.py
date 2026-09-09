"""Windows backend (Plan 057). Task Scheduler lifecycle + ACL key protection.

Per-user Scheduled Tasks at logon (no admin, no stored password), updater on
a 15-minute repeat, pythonw.exe router with python.exe updater, and icacls
owner-only key protection verified after writing. Until Stage 6 passes on a
real machine, select() is not wired: the installer keeps refusing Windows.
"""
import os
import subprocess
from pathlib import Path

import importlib.util as _ilu
_winacl_spec = _ilu.spec_from_file_location(
    'router_winacl', Path(__file__).resolve().parents[2] / 'codex_router' / 'winacl.py')
_winacl = _ilu.module_from_spec(_winacl_spec)
_winacl_spec.loader.exec_module(_winacl)


def _run(cmd, **kwargs):
    return subprocess.run(cmd, **kwargs)


def _grantee(run=None):
    """Installing account for icacls grants; never a literal %VAR%."""
    run = run or _run
    expanded = os.path.expandvars('%USERNAME%')
    if expanded and expanded != '%USERNAME%':
        return expanded
    whoami = run(['whoami'], capture_output=True, text=True)
    owner = (whoami.stdout or '').strip()
    if owner:
        return owner
    raise SystemExit('cannot determine the installing user for key protection')


def protect_file(path, run=None):
    """Restrict path to the installing user via icacls; verify afterwards.

    Creates the file's parent with the restricted ACL first so the secret is
    never written widened-then-narrowed. Raises SystemExit naming the exact
    failure; never silently leaves an exposed key.
    """
    run = run or _run
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    grantee = _grantee(run)
    result = run(['icacls', str(path.parent), '/inheritance:r', '/grant:r',
                  grantee + ':F'], capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit('cannot restrict %s: %s'
                         % (path.parent, (result.stderr or '').strip()[-500:]))
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
    result = run(['icacls', str(path), '/inheritance:r', '/grant:r',
                  grantee + ':F'], capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit('cannot protect %s: %s'
                         % (path, (result.stderr or '').strip()[-500:]))
    _winacl.check(path, run=run)


class Backend:
    name = 'windows'

    def __init__(self, svc, run):
        self._svc = svc
        self._run = run

    def protect_secret(self, path):
        protect_file(path, run=self._run)

    def check(self, home):
        del home  # Stage 3 preconditions land with the Task Scheduler tasks.
        return None

    def install(self, python, home, state, release_dir, previous):
        del python, home, state, release_dir, previous
        raise SystemExit('Windows install is not supported yet')

    def restart(self, home):
        del home
        raise SystemExit('Windows install is not supported yet')

    def stop(self, home):
        del home
        raise SystemExit('Windows install is not supported yet')

    def start_updates(self, home):
        del home
        return None

    def ensure_serving(self, home, state, version):
        del home, state, version
        return False

    def rollback_serving_ok(self, home, state, version):
        del home, state, version
        return False

    def pinned_release(self, home):
        del home
        return None

    def uninstall(self, home):
        del home
        # Removes both Scheduled Tasks; the refusal above keeps this
        # unreachable until Stage 3 lands, but the shape is pinned now.
        for task in ('CodexMixedModelRouter', 'CodexMixedModelRouterUpdate'):
            result = self._run(['schtasks', '/delete', '/tn', task, '/f'],
                               capture_output=True)
            if result.returncode != 0:
                raise SystemExit('Windows task survived uninstall: %s' % task)
