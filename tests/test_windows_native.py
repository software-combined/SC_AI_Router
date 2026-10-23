"""Win32 bindings preserve pointer widths, process identity and handle ownership."""
import ctypes as C
import os
import unittest
from unittest import mock

from tests.test_native_setup import module

native = module('windows_native')


def put(pointer, value):
    C.cast(pointer, C.POINTER(native.U32)).contents.value = value


class NativeApiTests(unittest.TestCase):
    def setUp(self):
        self.api = native.Native.__new__(native.Native)
        self.api.CloseHandle = mock.Mock()
        self.api.LocalFree = mock.Mock()
        self.enterContext(mock.patch.object(C, 'get_last_error', return_value=122, create=True))

    def test_apps_folder_activation_uses_backslash_and_balances_com(self):
        self.api.CoInitializeEx = mock.Mock(return_value=0)
        self.api.CoUninitialize = mock.Mock()
        self.api.ShellExecuteW = mock.Mock(return_value=33)
        self.api.activate('OpenAI.Codex_publisher!App')
        self.assertEqual(self.api.ShellExecuteW.call_args.args[2],
                         'shell:AppsFolder\\OpenAI.Codex_publisher!App')
        self.api.CoUninitialize.assert_called_once()
        for invalid in ('', 'not-an-app', 'family!App;start other', 'family!../App'):
            with self.assertRaises(native.NativeError):
                native.app_uri(invalid)

    def test_activation_failure_is_numeric_and_does_not_uninitialize_an_existing_apartment(self):
        self.api.CoInitializeEx = mock.Mock(return_value=-2147417850)
        self.api.CoUninitialize = mock.Mock()
        self.api.ShellExecuteW = mock.Mock(return_value=2)
        with self.assertRaises(native.NativeError) as failure:
            self.api.activate('family!App')
        self.assertEqual(failure.exception.facts, dict(operation='app_open',
            reason='activation_failed', winerror=2))
        self.api.CoUninitialize.assert_not_called()

    def test_process_handle_is_closed_after_failure_and_has_minimum_termination_rights(self):
        self.api.OpenProcess = mock.Mock(return_value=123)
        with self.assertRaises(ValueError):
            with self.api.opened(50, terminate=True) as handle:
                self.assertEqual(handle, 123)
                raise ValueError('fixture')
        self.api.OpenProcess.assert_called_once_with(0x101001, False, 50)
        self.api.CloseHandle.assert_called_once_with(123)

    def test_unicode_package_buffers_and_registration_change_refuse_safely(self):
        names_buffer = C.create_unicode_buffer('OpenAI.Codex_version_x64__publisher')
        def packages(family, count, names, length, buffer):
            self.assertEqual(family, 'OpenAI.Codex_publisher')
            put(count, 1)
            put(length, 100)
            if names is None:
                return 122
            names[0] = C.cast(names_buffer, C.c_wchar_p)
            return 0
        self.api.GetPackagesByPackageFamily = packages
        self.assertEqual(self.api.packages('OpenAI.Codex_publisher'), [names_buffer.value])
        def path(name, length, buffer):
            put(length, 100)
            if buffer is None:
                return 122
            buffer.value = 'C:\\应用\\Codex'
            return 0
        self.api.GetPackagePathByFullName = path
        self.assertEqual(self.api.package_path(names_buffer.value), 'C:\\应用\\Codex')
        self.api.GetPackagePathByFullName = lambda *_: 122
        with self.assertRaises(native.NativeError):
            self.api.package_path(names_buffer.value)

    def test_token_buffers_and_sid_allocations_are_always_released(self):
        sid_text = C.create_unicode_buffer('S-1-5-21-1000')
        self.api.GetCurrentProcess = lambda: -1
        def token(_process, _access, result):
            C.cast(result, C.POINTER(native.PTR)).contents.value = 123
            return True
        def info(_token, _kind, buffer, _size, length):
            put(length, C.sizeof(native.PTR) + 16)
            if buffer is None:
                return False
            C.cast(buffer, C.POINTER(native.PTR)).contents.value = 456
            return True
        def convert(_sid, result):
            C.cast(result, C.POINTER(native.PTR)).contents.value = C.addressof(sid_text)
            return True
        self.api.OpenProcessToken, self.api.GetTokenInformation = token, info
        self.api.IsValidSid, self.api.ConvertSidToStringSidW = lambda _: True, convert
        self.assertEqual(self.api.user(), sid_text.value)
        self.api.CloseHandle.assert_called_once()
        self.api.LocalFree.assert_called_once()
        self.api.CloseHandle.reset_mock()
        self.api.LocalFree.reset_mock()
        self.api.ConvertSidToStringSidW = mock.Mock(side_effect=ValueError('fixture'))
        with self.assertRaises(ValueError):
            self.api.user()
        self.api.CloseHandle.assert_called_once()
        self.api.LocalFree.assert_not_called()

    def test_partial_snapshot_is_never_accepted_and_snapshot_handle_is_closed(self):
        self.api.CreateToolhelp32Snapshot = lambda *_: 789
        def first(_handle, pointer):
            row = C.cast(pointer, C.POINTER(native.Entry)).contents
            row.pid, row.parent, row.name = 50, 1, 'ChatGPT.exe'
            return True
        self.api.Process32FirstW, self.api.Process32NextW = first, lambda *_: False
        with mock.patch.object(C, 'get_last_error', return_value=18):
            self.assertEqual(self.api.entries(), [dict(pid=50, parent=1, name='ChatGPT.exe')])
        with self.assertRaises(native.NativeError):
            self.api.entries()
        self.assertEqual(self.api.CloseHandle.call_count, 2)

    def test_termination_distinguishes_an_already_exited_process_from_access_denied(self):
        self.api.TerminateProcess = lambda *_: False
        self.api.WaitForSingleObject = lambda *_: 0
        self.api.end(123)
        self.api.WaitForSingleObject = lambda *_: 258
        with self.assertRaises(native.NativeError) as failure:
            self.api.end(123)
        self.assertEqual(failure.exception.facts['operation'], 'process_end')
        self.assertEqual(failure.exception.facts['winerror'], 122)


@unittest.skipUnless(os.name == 'nt', 'native Windows API contract')
class NativeWindowsContractTests(unittest.TestCase):
    def test_current_standard_or_admin_user_is_read_without_powershell(self):
        api = native.Native()
        self.assertEqual(C.sizeof(native.Entry), 568 if C.sizeof(native.PTR) == 8 else 556)
        with api.opened(os.getpid()) as handle:
            facts = api.facts(handle, os.getpid())
            self.assertEqual(facts['pid'], os.getpid())
            self.assertEqual(facts['session'], api.session())
            self.assertTrue(facts['born'])
            self.assertTrue(facts['exe'].lower().endswith('.exe'))
            self.assertEqual(api.user(handle), api.user())
            self.assertTrue(api.alive(handle))
        self.assertIn(os.getpid(), {row['pid'] for row in api.entries()})


if __name__ == '__main__':
    unittest.main()
