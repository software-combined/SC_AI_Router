"""Policy acceptance without reading or changing the host's managed settings."""
import json
import plistlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.claude_profile_sync_fixtures import load_helper
from tests._platform import requires_posix_perms

policy = load_helper('claude_desktop_policy')


class Registry:
    HKEY_LOCAL_MACHINE, HKEY_CURRENT_USER = 'machine', 'user'
    KEY_READ, KEY_WOW64_64KEY = 1, 256
    REG_SZ, REG_DWORD, REG_EXPAND_SZ, REG_QWORD = 1, 4, 2, 11

    def __init__(self, machine, user):
        self.values = {'machine': machine, 'user': user}
        self.opened = []

    def OpenKey(self, hive, path, reserved, access):
        assert path == r'SOFTWARE\Policies\Claude'
        assert access == self.KEY_READ | self.KEY_WOW64_64KEY
        self.opened.append(hive)
        if self.values[hive] is None:
            raise FileNotFoundError()
        key = mock.MagicMock()
        key.hive = hive
        return key

    def EnumValue(self, key, index):
        rows = self.values[key.hive]
        if index < len(rows):
            return rows[index]
        exc = OSError('enumeration complete')
        exc.winerror = 259
        raise exc


class DesktopPolicyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.profile = self.root / 'Claude-3p'
        library = self.profile / 'configLibrary'
        library.mkdir(parents=True)
        identifier = '11111111-2222-4333-8444-555555555555'
        self.meta = library / '_meta.json'
        self.meta.write_text(json.dumps({'appliedId': identifier}))
        self.entry = library / (identifier + '.json')
        self.entry.write_text('{}')

    def check(self, name, managed):
        method = {'darwin': 'managed_macos', 'win32': 'managed_windows',
                  'linux': 'managed_linux'}[name]
        with mock.patch.object(policy, method, return_value=managed):
            return policy.policy_disabled(name, self.profile)

    def test_local_restriction_encodings_and_invalid_values_on_all_platforms(self):
        for name in ('darwin', 'win32', 'linux'):
            for value, expected in ((True, True), (' TRUE\r ', True), (1, True),
                                    ('1', True), (False, False), ('false', False),
                                    (0, False), ('0', False)):
                with self.subTest(platform=name, value=value):
                    self.entry.write_text(json.dumps({policy.DISABLE: value}))
                    self.assertIs(self.check(name, {}), expected)
            for value in ('maybe', None, [], 2):
                self.entry.write_text(json.dumps({policy.DISABLE: value}))
                with self.assertRaisesRegex(OSError, 'policy is unknown'):
                    self.check(name, {})

    def test_unmanaged_or_app_behavior_only_preserves_local_connection(self):
        for name in ('darwin', 'win32', 'linux'):
            self.assertFalse(self.check(name, {}))
            self.assertFalse(self.check(name, {'disableAutoUpdates': 'true',
                                              'egressProxyUrl': 'http://proxy.example'}))
            for managed in ({policy.DISABLE: 'true'}, {policy.DISABLE: 'false'},
                            {'inferenceProvider': 'gateway'}, {'unknownFuturePolicy': 'value'}):
                self.assertTrue(self.check(name, managed))

    def test_unreadable_managed_source_and_invisible_registry_value_refuse(self):
        with mock.patch.object(policy, 'managed_linux', side_effect=PermissionError()):
            with self.assertRaisesRegex(OSError, 'policy is unknown'):
                policy.policy_disabled('linux', self.profile)
        with self.assertRaisesRegex(OSError, 'policy is unknown'):
            self.check('win32', {'disableAutoUpdates': None})

    def test_invalid_local_selection_and_bootstrap_refuse(self):
        original = self.meta.read_bytes()
        for meta in ({'appliedId': '../outside'}, {'appliedId': 'not-native'},
                     {'hybridPointer': 'https://bootstrap.example'}, []):
            self.meta.write_text(json.dumps(meta))
            with self.assertRaises(OSError):
                self.check('linux', {})
        self.meta.write_bytes(original)
        self.entry.write_text('{bad json')
        with self.assertRaises(OSError):
            self.check('linux', {})
        self.entry.write_text(json.dumps({'bootstrapUrl': 'https://bootstrap.example'}))
        with self.assertRaises(OSError):
            self.check('linux', {})
        self.entry.unlink()
        with self.assertRaises(OSError):
            self.check('linux', {})

    def test_local_symlink_is_not_followed(self):
        outside = self.root / 'outside.json'
        outside.write_text('{}')
        self.entry.unlink()
        self.entry.symlink_to(outside)
        with self.assertRaises(OSError):
            self.check('linux', {})

    def test_non_utf8_and_redirected_local_library_refuse(self):
        self.entry.write_bytes('{}'.encode('utf-16'))
        with self.assertRaises(OSError):
            self.check('linux', {})
        self.entry.write_text('{}')
        library = self.entry.parent
        relocated = self.profile / 'redirected'
        library.rename(relocated)
        library.symlink_to(relocated, target_is_directory=True)
        with self.assertRaises(OSError):
            self.check('linux', {})

    def test_windows_machine_presence_selects_one_hive_without_merging(self):
        registry = Registry([('disableAutoUpdates', 'true', 1)], [(policy.DISABLE, 1, 4)])
        self.assertEqual(policy.managed_windows(registry), {'disableAutoUpdates': 'true'})
        self.assertEqual(registry.opened, ['machine'])
        registry = Registry([('unseen', 1, 11)], [(policy.DISABLE, 1, 4)])
        self.assertEqual(policy.managed_windows(registry), {policy.DISABLE: 1})
        self.assertEqual(registry.opened, ['machine', 'user'])
        registry = Registry([('unreadable', '%VALUE%', 2)], [(policy.DISABLE, 1, 4)])
        self.assertEqual(policy.managed_windows(registry), {'unreadable': None})
        self.assertEqual(registry.opened, ['machine'])
        self.assertEqual(policy.managed_windows(Registry(None, None)), {})

    def test_windows_access_and_enumeration_errors_never_fall_back(self):
        registry = Registry([], [])
        for method in ('OpenKey', 'EnumValue'):
            with mock.patch.object(registry, method, side_effect=PermissionError()):
                with self.assertRaises(PermissionError):
                    policy.managed_windows(registry)

    def test_mac_machine_and_user_plists_follow_vendor_precedence(self):
        machine, user = self.root / 'machine.plist', self.root / 'user.plist'
        machine.write_bytes(plistlib.dumps({policy.DISABLE: True, 'disableAutoUpdates': True}))
        user.write_bytes(plistlib.dumps({policy.DISABLE: 'false'}))
        self.assertEqual(policy.managed_macos((machine, user)),
                         {policy.DISABLE: 'false', 'disableAutoUpdates': True})
        user.unlink()
        self.assertTrue(policy.managed_macos((machine, user))[policy.DISABLE])
        machine.write_bytes(b'not a plist')
        with self.assertRaises(ValueError):
            policy.managed_macos((machine, user))

    @requires_posix_perms
    def test_linux_requires_root_owned_regular_file_and_protected_directory(self):
        directory = self.root / 'managed'
        directory.mkdir(mode=0o755)
        path = directory / 'managed-settings.json'
        self.assertEqual(policy.managed_linux(path), {})
        path.write_text(json.dumps({policy.DISABLE: True}))
        path.chmod(0o644)
        original = Path.lstat

        def trusted(item, *args, **kwargs):
            info = original(item, *args, **kwargs)
            return SimpleNamespace(st_uid=0, **{key: getattr(info, key) for key in (
                'st_mode', 'st_dev', 'st_ino', 'st_size', 'st_mtime_ns')})

        with mock.patch.object(Path, 'lstat', trusted):
            self.assertEqual(policy.managed_linux(path), {policy.DISABLE: True})
            for item in (path, directory):
                before = item.stat().st_mode
                item.chmod(before | 0o020)
                with self.assertRaises(OSError):
                    policy.managed_linux(path)
                item.chmod(before)
            renamed = directory / 'other.json'
            path.rename(renamed)
            path.symlink_to(renamed)
            with self.assertRaises(OSError):
                policy.managed_linux(path)
        # A non-root fixture is rejected even with otherwise safe permissions.
        path.unlink()
        renamed.rename(path)
        if path.stat().st_uid != 0:
            with self.assertRaises(OSError):
                policy.managed_linux(path)


if __name__ == '__main__':
    unittest.main()
