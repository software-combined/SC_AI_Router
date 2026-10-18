"""Linux user service lifecycle. Python 3.9+, no privileged service or lingering."""
import json
import os
from pathlib import Path

SERVICE = 'codex-mixed-model-router.service'
UPDATE = 'codex-mixed-model-router-update.service'
TIMER = 'codex-mixed-model-router-update.timer'
EXPRESS_UPDATE = 'codex-mixed-model-router-express.service'
EXPRESS_TIMER = 'codex-mixed-model-router-express.timer'


def quote(value, command=False):
    value = str(value).replace('%', '%%')
    return json.dumps(value.replace('$', '$$') if command else value, ensure_ascii=False)


class Manager:
    def __init__(self, home, run):
        self.home, self.run = Path(home).resolve(), run
        config = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
        self.units = config / 'systemd' / 'user'

    def ctl(self, *args, check=True):
        return self.run(['systemctl', '--user', *args], check=check,
                        capture_output=True, text=True)

    def check(self):
        try:
            result = self.ctl('show-environment', check=False)
        except OSError:
            result = None
        if result is None or result.returncode:
            raise SystemExit('Linux installation requires a running systemd user manager; '
                             'run this installer in the signed-in desktop user session.')

    def install(self, python, release, *, updates_only=False):
        del release  # Stable launchers resolve their release when they run.
        import shutil
        python = shutil.which(python) or python
        if not Path(python).is_absolute():
            raise SystemExit('systemd requires an absolute Python interpreter path')
        launcher = self.home / 'update_launch.py'
        if not launcher.is_file():
            raise SystemExit('The stable update launcher is missing; run setup again.')
        # Stop the old timer and a legacy updater before replacing its definition.
        # A scheduled update must not stop its own service (and installer child).
        self.ctl('stop', TIMER, check=False)
        self.ctl('stop', EXPRESS_TIMER, check=False)
        if os.environ.get('ROUTER_UPDATE_SERVICE') != '1':
            self.ctl('stop', UPDATE, check=False)
        env = quote('ROUTER_HOME=' + str(self.home))
        command = quote(python, True) + ' ' + quote(self.home / 'router_launch.py', True)
        updater = quote(python, True) + ' ' + quote(launcher, True)
        units = {
            SERVICE: ('[Unit]\nDescription=SC mixed model router\nAfter=network.target\n'
                      '[Service]\nExecStart=' + command + '\nEnvironment=' + env + '\n'
                      'Restart=always\nRestartSec=5\nTimeoutStopSec=150\nUMask=0077\n'
                      '[Install]\nWantedBy=default.target\n'),
            UPDATE: ('[Unit]\nDescription=Update SC mixed model router\n'
                     '[Service]\nType=oneshot\nExecStart=' + updater + '\n'
                     'Environment=' + env + '\nEnvironment=ROUTER_UPDATE_SERVICE=1\n'
                     # The restart dialog is spawned detached; the default
                     # control-group kill would reap it when the oneshot ends.
                     'KillMode=process\n'
                     'UMask=0077\n'),
            TIMER: ('[Unit]\nDescription=Check SC router updates every 4 hours\n'
                    '[Timer]\nOnActiveSec=5min\nOnUnitInactiveSec=4h\n'
                    '[Install]\nWantedBy=timers.target\n'),
        }
        if updates_only:
            del units[SERVICE]
        express = (self.home / 'express_launch.py').is_file()
        if express:
            command = quote(python, True) + ' ' + quote(self.home / 'express_launch.py', True)
            units[EXPRESS_UPDATE] = units[UPDATE].replace('ExecStart=' + updater,
                                                        'ExecStart=' + command)
            units[EXPRESS_TIMER] = (
                '[Unit]\nDescription=Check Express router updates every minute\n'
                '[Timer]\nOnActiveSec=1min\nOnUnitInactiveSec=1min\nAccuracySec=1s\n'
                '[Install]\nWantedBy=timers.target\n')
        self.units.mkdir(parents=True, exist_ok=True)
        for name, content in units.items():
            (self.units / name).write_text(content)
        self.ctl('daemon-reload')
        self.verify_updater(python, launcher)
        self.ctl('enable', *((TIMER,) if updates_only else (SERVICE, TIMER)))
        if express:
            self.ctl('enable', EXPRESS_TIMER)
        if not updates_only:
            self.restart()
        # The installer calls start_updates() again once it finishes, but a
        # later failure (a refused settings merge, a client attach) used to
        # return before that call and leave the timer stopped: no scheduled
        # check ran again until the next reinstall. Start it here, where it
        # was stopped, so polling survives every later step.
        self.start_updates()

    def verify_updater(self, python, launcher):
        """Read systemd's loaded command, including overrides, after reload."""
        expected = '{ path=%s ; argv[]=%s %s ;' % (python, python, launcher)
        try:
            result = self.ctl('show', UPDATE, '--property=ExecStart', '--value', check=False)
            loaded = result.stdout.strip()
            ready = not result.returncode and loaded.startswith(expected) and loaded.count('{ path=') == 1
        except OSError:
            ready = False
        if not ready:
            raise SystemExit('The Linux scheduled updater did not load the stable launcher; run setup again.')

    def pinned_releases(self):
        """A loaded job can still name a release after its unit file changes."""
        versions = tuple(path.name for path in (self.home / 'releases').glob('*') if path.is_dir())
        pinned = set()
        if os.environ.get('ROUTER_UPDATE_SERVICE') == '1':
            origin = os.environ.get('ROUTER_UPDATE_ORIGIN')
            if origin not in (*versions, 'control'):
                return versions  # A legacy running updater has no origin marker.
            if origin != 'control':
                pinned.add(origin)
        for unit in (SERVICE, UPDATE, EXPRESS_UPDATE):
            try:
                result = self.ctl('show', unit, '--property=ExecStart', '--value', check=False)
            except OSError:
                return versions
            if result.returncode:
                return versions  # Unknown loaded state never authorises pruning.
            pinned.update(version for version in versions if '/releases/' + version + '/' in result.stdout)
        return tuple(pinned)

    def start_updates(self):
        if (self.units / EXPRESS_TIMER).is_file():
            self.ctl('start', EXPRESS_TIMER)
        self.ctl('start', TIMER)

    def restart(self):
        self.ctl('restart', SERVICE)

    def stop(self):
        self.ctl('stop', SERVICE)

    def uninstall(self):
        self.ctl('disable', '--now', EXPRESS_TIMER, check=False)
        self.ctl('stop', EXPRESS_UPDATE, check=False)
        self.ctl('disable', '--now', TIMER, SERVICE)
        self.ctl('stop', UPDATE, check=False)
        for name in (SERVICE, UPDATE, TIMER, EXPRESS_UPDATE, EXPRESS_TIMER):
            (self.units / name).unlink(missing_ok=True)
        self.ctl('daemon-reload')
