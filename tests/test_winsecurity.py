"""Exercise native descriptor decoding and resource ownership with API buffers."""
import ctypes as C
import struct
import unittest
from unittest import mock

from ai_router import winsecurity as native

SID = 'S-1-5-21-1-2-3-1001'


class SecurityApi:
    def __init__(self, kind=0, present=True):
        sid = bytes([1, 1]) + bytes(5) + bytes([5]) + struct.pack('<I', 21)
        ace = struct.pack('<BBHI', kind, 16, 8 + len(sid), 2032127) + sid
        self.acl = C.create_string_buffer(bytes(8) + ace)
        self.owner = C.create_string_buffer(sid)
        self.descriptor = C.create_string_buffer(16)
        self.present, self.allocated, self.freed, self.closed = present, [], [], []

    def GetCurrentThread(self):
        return 1

    def OpenThreadToken(self, thread, access, own, result):
        result._obj.value = 42
        return 1

    def CloseHandle(self, token):
        self.closed.append(token.value)
        return 1

    def LocalFree(self, pointer):
        self.freed.append(pointer.value)

    def GetTokenInformation(self, token, kind, buffer, size, needed):
        needed._obj.value = 16
        if buffer is None:
            return 0
        C.cast(buffer, C.POINTER(C.c_void_p)).contents.value = C.addressof(self.owner)
        return 1

    def IsValidSid(self, pointer):
        return 1

    def ConvertSidToStringSidW(self, pointer, result):
        text = C.create_unicode_buffer(SID)
        self.allocated.append(text)
        result._obj.value = C.addressof(text)
        return 1

    def GetNamedSecurityInfoW(self, path, kind, flags, owner, group, acl, sacl, descriptor):
        self.path = path
        owner._obj.value = C.addressof(self.owner)
        acl._obj.value = C.addressof(self.acl)
        descriptor._obj.value = C.addressof(self.descriptor)
        return 0

    def GetSecurityDescriptorDacl(self, descriptor, present, acl, defaulted):
        present._obj.value = self.present
        acl._obj.value = C.addressof(self.acl) if self.present else None
        return 1

    def IsValidAcl(self, acl):
        return 1

    def GetAclInformation(self, acl, result, size, kind):
        info = result._obj
        info.count, info.used = 1, len(self.acl) - 1
        return 1

    def GetAce(self, acl, index, result):
        result._obj.value = C.addressof(self.acl) + 8
        return 1


class NativeReaderTests(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(C, 'get_last_error', return_value=122, create=True)
        patch.start()
        self.addCleanup(patch.stop)

    def assert_resources_released(self, api):
        self.assertEqual(api.closed, [42])
        self.assertEqual(set(api.freed), {C.addressof(api.descriptor)} |
                         {C.addressof(buffer) for buffer in api.allocated})

    def test_unicode_path_and_inherited_allow_are_decoded_without_processes(self):
        api = SecurityApi()
        with mock.patch('subprocess.run', side_effect=AssertionError('no process')):
            doc = native.query("C:/é [$x]; ' &/key", api)
        self.assertEqual(api.path, "C:/é [$x]; ' &/key")
        self.assertEqual(doc, dict(user=SID, owner=SID, dacl=True,
                                  rules=[dict(sid=SID, type=0, flags=16, mask=2032127)]))
        self.assert_resources_released(api)

    def test_null_dacl_has_no_rules(self):
        api = SecurityApi(present=False)
        doc = native.query('key', api)
        self.assertFalse(doc['dacl'])
        self.assertEqual(doc['rules'], [])
        self.assert_resources_released(api)

    def test_unsupported_ace_releases_descriptor(self):
        api = SecurityApi(kind=5)
        with self.assertRaisesRegex(ValueError, 'unsupported ACE'):
            native.query('key', api)
        self.assert_resources_released(api)

    def test_truncated_sid_is_rejected_before_conversion(self):
        api = SecurityApi()
        C.c_ubyte.from_address(C.addressof(api.acl) + 17).value = 15
        with self.assertRaisesRegex(ValueError, 'SID size'):
            native.query('key', api)
        self.assert_resources_released(api)

    def test_api_failure_keeps_operation_and_code_without_path(self):
        api = SecurityApi()
        api.GetNamedSecurityInfoW = mock.Mock(return_value=5)
        with self.assertRaises(native.QueryError) as caught:
            native.query('private-path', api)
        self.assertEqual(caught.exception.operation, 'GetNamedSecurityInfoW')
        self.assertEqual(caught.exception.errno, 5)
        self.assertNotIn('private-path', str(caught.exception))
        self.assertEqual(api.closed, [42])

    def test_failed_token_read_closes_handle(self):
        api = SecurityApi()
        api.GetTokenInformation = mock.Mock(return_value=0)
        with self.assertRaises(ValueError):
            native.query(None, api)
        self.assertEqual(api.closed, [42])
