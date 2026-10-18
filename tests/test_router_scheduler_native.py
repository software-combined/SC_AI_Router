"""Disposable GitHub Linux runner proof of the loaded job and unattended launcher."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.test_native_setup import module

systemd = module('systemd')
ROOT = Path(__file__).resolve().parents[1]
UNITS = (systemd.SERVICE, systemd.UPDATE, systemd.TIMER,
         systemd.EXPRESS_UPDATE, systemd.EXPRESS_TIMER)
ENABLED = (sys.platform == 'linux' and os.environ.get('GITHUB_ACTIONS') == 'true'
           and os.environ.get('SCG_TEST_NATIVE_ROUTER_SCHEDULER') == '1')


def run(command, **kwargs):
    kwargs.setdefault('timeout', 30)
    return subprocess.run(command, **kwargs)


@unittest.skipUnless(ENABLED, 'disposable GitHub Linux user manager only')
class NativeRouterSchedulerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='scg router scheduler ')
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.manager = systemd.Manager(self.home, run)
        self.manager.check()
        # The fixed user units belong to real installs outside this disposable job.
        # Refuse before registering cleanup or changing anything if one exists.
        for name in UNITS:
            self.assertFalse((self.manager.units / name).exists(), name)
            self.assertFalse((self.manager.units / (name + '.d')).exists(), name)
            loaded = self.manager.ctl('show', name, '--property=LoadState', '--value', check=False)
            self.assertEqual(loaded.stdout.strip(), 'not-found', name)
        self.addCleanup(self.cleanup_units)
        self.manager.units.mkdir(parents=True, exist_ok=True)
        self.dropin = self.manager.units / (systemd.TIMER + '.d')

    def cleanup_units(self):
        self.manager.ctl('disable', '--now', systemd.TIMER, systemd.EXPRESS_TIMER, check=False)
        self.manager.ctl('stop', systemd.UPDATE, systemd.EXPRESS_UPDATE, systemd.SERVICE, check=False)
        for name in UNITS:
            (self.manager.units / name).unlink(missing_ok=True)
        if hasattr(self, 'dropin') and self.dropin.exists():
            (self.dropin / 'acceptance.conf').unlink(missing_ok=True)
            self.dropin.rmdir()
        self.manager.ctl('daemon-reload')
        self.manager.ctl('reset-failed', *UNITS, check=False)

    def fire_timer(self):
        marker = self.home / 'scheduled-proof.json'
        marker.unlink(missing_ok=True)
        self.manager.ctl('stop', systemd.TIMER)
        self.manager.ctl('daemon-reload')
        self.manager.ctl('start', systemd.TIMER)
        deadline = time.monotonic() + 20
        while not marker.is_file() and time.monotonic() < deadline:
            time.sleep(0.2)
        self.assertTrue(marker.is_file(), self.manager.ctl(
            'status', systemd.UPDATE, '--no-pager', check=False).stdout)
        proof = json.loads(marker.read_text())
        self.assertEqual(proof['origin'], 'control')
        self.assertEqual(proof['argv'][1:], ['--update', '--home', str(self.home)])

    def test_migrate_read_back_and_run_the_stable_launcher_after_rollback(self):
        old = self.home / 'releases/1.2.6.174/packaging'
        old.mkdir(parents=True)
        (old / 'install.py').write_text("raise SystemExit('download_signin_required')\n")
        (self.home / 'current').write_text('1.2.6.174')
        (self.home / 'download-auth.json').write_text('{"signed_in":false}')
        command = systemd.quote(sys.executable, True) + ' ' + systemd.quote(old / 'install.py', True)
        original = '[Service]\nType=oneshot\nExecStart=' + command + '\n'
        for name in (systemd.SERVICE, systemd.UPDATE):
            (self.manager.units / name).write_text(original)
        self.manager.ctl('daemon-reload')
        self.assertIn('1.2.6.174', self.manager.pinned_releases())
        (self.home / 'update_launch.py').write_bytes((ROOT / 'packaging/update_launch.py').read_bytes())
        (self.home / 'express_launch.py').write_text('raise SystemExit(0)\n')
        control = self.home / 'control/1.3.2.185/packaging'
        control.mkdir(parents=True)
        (self.home / 'control-version').write_text('1.3.2.185')
        (control / 'install.py').write_text(
            "# '--update'\nimport json,os,sys\nfrom pathlib import Path\n"
            "home=Path(sys.argv[sys.argv.index('--home')+1])\n"
            "(home/'scheduled-proof.json').write_text(json.dumps(dict("
            "argv=sys.argv,origin=os.environ.get('ROUTER_UPDATE_ORIGIN'))))\n")
        self.manager.install(sys.executable, None, updates_only=True)
        self.assertEqual((self.manager.units / systemd.SERVICE).read_text(), original)
        loaded = self.manager.ctl('show', systemd.UPDATE, '--property=ExecStart', '--value').stdout
        self.assertIn(str(self.home / 'update_launch.py'), loaded)
        self.assertNotIn('/releases/', loaded)
        timers = self.manager.ctl('show', systemd.TIMER, '--property=TimersMonotonic', '--value').stdout
        self.assertIn('OnUnitInactiveUSec=4h', timers)
        self.dropin.mkdir()
        (self.dropin / 'acceptance.conf').write_text(
            '[Timer]\nOnActiveSec=\nOnActiveSec=1s\nAccuracySec=1ms\n')
        self.fire_timer()
        # The serving pointer remains on the old release: the newer controller wins.
        self.manager.install(sys.executable, None, updates_only=True)
        self.fire_timer()
        self.assertEqual((self.home / 'download-auth.json').read_text(), '{"signed_in":false}')
        (self.home / 'releases/1.2.5.173').mkdir()
        with mock.patch.dict(os.environ, ROUTER_UPDATE_SERVICE='1', ROUTER_UPDATE_ORIGIN='1.2.5.173'):
            self.assertIn('1.2.5.173', self.manager.pinned_releases())
        with mock.patch.dict(os.environ, ROUTER_UPDATE_SERVICE='1', ROUTER_UPDATE_ORIGIN='control'):
            self.assertNotIn('1.2.5.173', self.manager.pinned_releases())
