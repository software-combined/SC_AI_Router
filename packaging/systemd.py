"""Linux user service lifecycle. Python 3.9+, no privileged service or lingering."""
import json
import os
from contextlib import contextmanager
from pathlib import Path

SERVICE = 'codex-mixed-model-router.service'
UPDATE = 'codex-mixed-model-router-update.service'
TIMER = 'codex-mixed-model-router-update.timer'


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

    @contextmanager
    def operation(self):
        import fcntl
        self.check()
        self.home.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(self.home / 'install.lock', os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SystemExit('Another router operation is in progress; retry when idle.')
            yield
        finally:
            os.close(fd)

    def install(self, python, release):
        import shutil
        python = shutil.which(python) or python
        if not Path(python).is_absolute():
            raise SystemExit('systemd requires an absolute Python interpreter path')
        # Stop the old timer and a legacy updater before replacing its definition.
        # A scheduled update must not stop its own service (and installer child).
        self.ctl('stop', TIMER, check=False)
        if os.environ.get('ROUTER_UPDATE_SERVICE') != '1':
            self.ctl('stop', UPDATE, check=False)
        env = quote('ROUTER_HOME=' + str(self.home))
        command = quote(python, True) + ' ' + quote(self.home / 'router_launch.py', True)
        updater = (quote(python, True) + ' ' + quote(release / 'packaging' / 'install.py', True)
                   + ' --check-update --home ' + quote(self.home, True))
        units = {
            SERVICE: ('[Unit]\nDescription=SC mixed model router\nAfter=network.target\n'
                      '[Service]\nExecStart=' + command + '\nEnvironment=' + env + '\n'
                      'Restart=always\nRestartSec=5\nTimeoutStopSec=150\nUMask=0077\n'
                      '[Install]\nWantedBy=default.target\n'),
            UPDATE: ('[Unit]\nDescription=Update SC mixed model router\n'
                     '[Service]\nType=oneshot\nExecStart=' + updater + '\n'
                     'Environment=' + env + '\nEnvironment=ROUTER_UPDATE_SERVICE=1\n'
                     'UMask=0077\n'),
            TIMER: ('[Unit]\nDescription=Check SC router updates every 15 minutes\n'
                    '[Timer]\nOnActiveSec=5min\nOnUnitInactiveSec=15min\n'
                    '[Install]\nWantedBy=timers.target\n'),
        }
        self.units.mkdir(parents=True, exist_ok=True)
        for name, content in units.items():
            (self.units / name).write_text(content)
        self.ctl('daemon-reload')
        self.ctl('enable', SERVICE, TIMER)
        self.restart()

    def start_updates(self):
        self.ctl('start', TIMER)

    def restart(self):
        self.ctl('restart', SERVICE)

    def stop(self):
        self.ctl('stop', SERVICE)

    def uninstall(self):
        self.ctl('disable', '--now', TIMER, SERVICE)
        self.ctl('stop', UPDATE, check=False)
        for name in (SERVICE, UPDATE, TIMER):
            (self.units / name).unlink(missing_ok=True)
        self.ctl('daemon-reload')
