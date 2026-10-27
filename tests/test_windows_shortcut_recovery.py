"""Restore only owned Windows entry points and preserve a concurrent startup choice."""
import base64
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.test_native_setup import module


class ShortcutRecoveryTests(unittest.TestCase):
    def fixture(self, root):
        owner = module('native_shortcuts')
        home = root / 'home'
        home.mkdir()
        startup = SimpleNamespace(windows_target=lambda: root / 'startup/SCG Router.lnk',
                                  IDENTITY='com.softwarecombined.router.menu',
                                  enabled=mock.Mock(return_value=False), configure=mock.Mock())
        real = owner.load
        owner.load = lambda name: startup if name == 'desktop_startup' else real(name)
        owner._start_menu = lambda: root / 'menu'
        def run(args, **kwargs):
            rows = json.loads(kwargs['input'])
            links = {row['name']: (base64.b64encode(Path(row['path']).read_bytes()).decode()
                                  if Path(row['path']).exists() else None) for row in rows}
            return SimpleNamespace(stdout=json.dumps(links), returncode=0)
        return owner, home, startup, run

    def test_binary_links_restore_exactly_and_new_links_are_removed(self):
        with tempfile.TemporaryDirectory() as temporary:
            owner, home, _, run = self.fixture(Path(temporary))
            with mock.patch.object(owner, '_registry_snapshot', return_value=None), \
                    mock.patch.object(owner, '_registry_restore'):
                rows = owner._cohort_links(home)
                first = Path(rows[0]['path'])
                first.parent.mkdir()
                first.write_bytes(b'\x00old\xff\r\n')
                before = owner.snapshot(home, run)
                first.write_bytes(b'new')
                Path(rows[1]['path']).write_bytes(b'new uninstall')
                owner.restore(home, before, run)
                self.assertEqual(first.read_bytes(), b'\x00old\xff\r\n')
                self.assertFalse(Path(rows[1]['path']).exists())

    def test_malformed_record_refuses_before_any_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            owner, home, _, run = self.fixture(Path(temporary))
            with mock.patch.object(owner, '_registry_snapshot', return_value=None), \
                    mock.patch.object(owner, '_registry_restore') as registry:
                before = owner.snapshot(home, run)
                path = Path(owner._cohort_links(home)[0]['path'])
                path.parent.mkdir()
                path.write_bytes(b'current')
                for change in ({'links': dict(before['links'], open='%%%')},
                               {'registry': {'InstallLocation': str(home), 'NoRepair': 'wrong'}}):
                    with self.subTest(change=change), self.assertRaises(ValueError):
                        owner.restore(home, dict(before, **change), run)
                    self.assertEqual(path.read_bytes(), b'current')
                registry.assert_not_called()

    def test_registration_ownership_resolves_equivalent_home_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / 'home'
            home.mkdir()
            owner = module('native_shortcuts')
            owner._valid_registry(home.resolve(), {'InstallLocation': str(home / '..' / 'home')})
            with self.assertRaises(ValueError):
                owner._valid_registry(home, {'InstallLocation': str(home.parent / 'foreign')})

    def test_changed_signin_choice_is_reconciled_without_restoring_old_startup_link(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            owner, home, startup, run = self.fixture(root)
            with mock.patch.object(owner, '_registry_snapshot', return_value=None), \
                    mock.patch.object(owner, '_registry_restore'):
                before = owner.snapshot(home, run)
                startup.enabled.return_value = True
                link = startup.windows_target()
                link.parent.mkdir()
                link.write_bytes(b'new explicit choice')
                resources = SimpleNamespace(current=lambda _: root / 'restored-resources')
                real = owner.load
                owner.load = lambda name: resources if name == 'native_resources' else real(name)
                owner.restore(home, before, run)
                self.assertEqual(link.read_bytes(), b'new explicit choice')
                startup.configure.assert_called_once_with(home.resolve(), root / 'restored-resources', None)

    def test_concurrent_shortcut_edit_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            owner, home, _, run = self.fixture(Path(temporary))
            atomic = module('atomic_write')
            write = atomic.replace_bytes
            with mock.patch.object(owner, '_registry_snapshot', return_value=None), \
                    mock.patch.object(owner, '_registry_restore') as registry:
                path = Path(owner._cohort_links(home)[0]['path'])
                path.parent.mkdir()
                path.write_bytes(b'old')
                before = owner.snapshot(home, run)
                path.write_bytes(b'installed')
                real = owner.load
                owner.load = lambda name: atomic if name == 'atomic_write' else real(name)
                def race(target, content, **kwargs):
                    target.write_bytes(b'concurrent')
                    return write(target, content, **kwargs)
                with mock.patch.object(atomic, 'replace_bytes', side_effect=race), \
                        self.assertRaises(OSError):
                    owner.restore(home, before, run)
                self.assertEqual(path.read_bytes(), b'concurrent')
                registry.assert_not_called()


@unittest.skipUnless(os.name == 'nt', 'native Windows shortcut and HKCU recovery')
class NativeShortcutRecoveryTests(unittest.TestCase):
    def test_owned_entry_points_restore_and_foreign_shortcut_refuses(self):
        import uuid
        import winreg
        owner = module('native_shortcuts')
        with tempfile.TemporaryDirectory(prefix='shortcut é ') as temporary:
            root = Path(temporary).resolve()
            home = root / 'home'
            home.mkdir()
            key = r'Software\SCG-CI-' + uuid.uuid4().hex
            startup = SimpleNamespace(windows_target=lambda: root / 'startup.lnk',
                                      IDENTITY='ci-menu', enabled=lambda *a, **kw: False)
            real = owner.load
            owner.load = lambda name: startup if name == 'desktop_startup' else real(name)
            with mock.patch.object(owner, 'UNINSTALL_KEY', 'HKCU:\\' + key), \
                    mock.patch.object(owner, '_start_menu', return_value=root / 'menu'):
                try:
                    before = owner.snapshot(home)
                    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as handle:
                        winreg.SetValueEx(handle, 'InstallLocation', 0, winreg.REG_SZ, str(home))
                        winreg.SetValueEx(handle, 'DisplayVersion', 0, winreg.REG_SZ, '1.3.23')
                    self.assertIsNotNone(owner.snapshot(home)['registry'])
                    owner.restore(home, before)
                    self.assertIsNone(owner.snapshot(home)['registry'])
                    path = root / 'menu/SCG Router.lnk'
                    path.parent.mkdir(exist_ok=True)
                    target = home / 'setup/retained/runtime/pythonw.exe'
                    args = subprocess.list2cmdline([str(home.resolve() / 'native_launch.py')])
                    command = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut(%s);"
                               "$s.TargetPath=%s;$s.Arguments=%s;$s.Save()" %
                               (owner._quote(path), owner._quote(target), owner._quote(args)))
                    subprocess.run(['powershell', '-NoProfile', '-Command', command], check=True,
                                   capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                    owned = owner.snapshot(home)
                    self.assertIsNotNone(owned['links']['open'])
                    path.unlink()
                    owner.restore(home, owned)
                    self.assertEqual(owner.snapshot(home)['links'], owned['links'])
                    command = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut(%s);"
                               "$s.TargetPath=$env:ComSpec;$s.Arguments='foreign';$s.Save()" % owner._quote(path))
                    subprocess.run(['powershell', '-NoProfile', '-Command', command], check=True,
                                   capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                    exact = path.read_bytes()
                    foreign = dict(owned, links=dict(owned['links'], open=base64.b64encode(exact).decode()))
                    path.unlink()
                    with self.assertRaises(subprocess.CalledProcessError):
                        owner.restore(home, foreign)
                    self.assertFalse(path.exists())
                    path.write_bytes(exact)
                    with self.assertRaises(subprocess.CalledProcessError):
                        owner.restore(home, before)
                    self.assertEqual(path.read_bytes(), exact)
                finally:
                    try:
                        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
                    except FileNotFoundError:
                        pass
