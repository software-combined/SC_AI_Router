"""Small Win32 process/package primitives. Inert on import; Python 3.9+."""
import contextlib
import ctypes as C
import re

U32, PTR, BOOL = C.c_uint32, C.c_void_p, C.c_int
P32 = C.POINTER(U32)
ENUM = getattr(C, 'WINFUNCTYPE', C.CFUNCTYPE)(BOOL, PTR, C.c_ssize_t)
APPS_FOLDER = 'shell:AppsFolder\\'


class NativeError(OSError):
    def __init__(self, operation, reason='query_failed', code=0):
        super().__init__(code, 'Windows desktop operation failed')
        self.facts = dict(operation=operation, reason=reason, winerror=code)


class Entry(C.Structure):
    _fields_ = [('size', U32), ('usage', U32), ('pid', U32), ('heap', C.c_size_t),
                ('module', U32), ('threads', U32), ('parent', U32),
                ('priority', C.c_int32), ('flags', U32), ('name', C.c_wchar * 260)]


class FileTime(C.Structure):
    _fields_ = [('low', U32), ('high', U32)]


def app_uri(aumid):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+![A-Za-z0-9_.-]+', aumid):
        raise NativeError('app_open', 'invalid_identity')
    return APPS_FOLDER + aumid


class Native:
    def __init__(self):
        kernel = C.WinDLL('kernel32', use_last_error=True)
        security = C.WinDLL('advapi32', use_last_error=True)
        user = C.WinDLL('user32', use_last_error=True)
        shell = C.WinDLL('shell32', use_last_error=True)
        com = C.WinDLL('ole32', use_last_error=True)
        signatures = (
            (kernel, 'CloseHandle', BOOL, (PTR,)),
            (kernel, 'LocalFree', PTR, (PTR,)),
            (kernel, 'GetCurrentProcess', PTR, ()),
            (kernel, 'GetCurrentProcessId', U32, ()),
            (kernel, 'OpenProcess', PTR, (U32, BOOL, U32)),
            (kernel, 'GetProcessTimes', BOOL, (PTR,) + (C.POINTER(FileTime),) * 4),
            (kernel, 'QueryFullProcessImageNameW', BOOL, (PTR, U32, C.c_wchar_p, P32)),
            (kernel, 'ProcessIdToSessionId', BOOL, (U32, P32)),
            (kernel, 'GetPackageFamilyName', C.c_int32, (PTR, P32, C.c_wchar_p)),
            (kernel, 'GetPackagesByPackageFamily', C.c_int32,
             (C.c_wchar_p, P32, C.POINTER(C.c_wchar_p), P32, C.c_wchar_p)),
            (kernel, 'GetPackagePathByFullName', C.c_int32, (C.c_wchar_p, P32, C.c_wchar_p)),
            (kernel, 'CreateToolhelp32Snapshot', PTR, (U32, U32)),
            (kernel, 'Process32FirstW', BOOL, (PTR, C.POINTER(Entry))),
            (kernel, 'Process32NextW', BOOL, (PTR, C.POINTER(Entry))),
            (kernel, 'WaitForSingleObject', U32, (PTR, U32)),
            (kernel, 'TerminateProcess', BOOL, (PTR, U32)),
            (security, 'OpenProcessToken', BOOL, (PTR, U32, C.POINTER(PTR))),
            (security, 'GetTokenInformation', BOOL, (PTR, C.c_int, PTR, U32, P32)),
            (security, 'IsValidSid', BOOL, (PTR,)),
            (security, 'ConvertSidToStringSidW', BOOL, (PTR, C.POINTER(PTR))),
            (user, 'EnumWindows', BOOL, (ENUM, C.c_ssize_t)),
            (user, 'GetWindowThreadProcessId', U32, (PTR, P32)),
            (user, 'IsWindowVisible', BOOL, (PTR,)),
            (user, 'PostMessageW', BOOL, (PTR, U32, C.c_size_t, C.c_ssize_t)),
            (shell, 'ShellExecuteW', C.c_ssize_t,
             (PTR, C.c_wchar_p, C.c_wchar_p, C.c_wchar_p, C.c_wchar_p, C.c_int)),
            (com, 'CoInitializeEx', C.c_int32, (PTR, U32)),
            (com, 'CoUninitialize', None, ()),
        )
        for dll, name, result, arguments in signatures:
            function = getattr(dll, name)
            function.restype, function.argtypes = result, arguments
            setattr(self, name, function)

    def check(self, value, operation):
        if not value:
            raise NativeError(operation, code=C.get_last_error())
        return value

    @contextlib.contextmanager
    def opened(self, pid, terminate=False):
        handle = self.check(self.OpenProcess(0x101000 | int(terminate), False, pid), 'process_open')
        try:
            yield handle
        finally:
            self.CloseHandle(handle)

    def user(self, process=None):
        token, text, size = PTR(), PTR(), U32()
        try:
            self.check(self.OpenProcessToken(process or self.GetCurrentProcess(), 8,
                                            C.byref(token)), 'process_owner')
            if (self.GetTokenInformation(token, 1, None, 0, C.byref(size))
                    or C.get_last_error() != 122 or not C.sizeof(PTR) <= size.value <= 65536):
                raise NativeError('process_owner', 'invalid_response')
            buffer = C.create_string_buffer(size.value)
            self.check(self.GetTokenInformation(token, 1, buffer, size,
                                               C.byref(size)), 'process_owner')
            sid = C.cast(buffer, C.POINTER(PTR)).contents.value
            self.check(sid and self.IsValidSid(sid), 'process_owner')
            self.check(self.ConvertSidToStringSidW(sid, C.byref(text)), 'process_owner')
            self.check(text.value, 'process_owner')
            return C.wstring_at(text)
        finally:
            if text.value:
                self.LocalFree(text)
            if token.value:
                self.CloseHandle(token)

    def packages(self, family):
        count, size = U32(), U32()
        code = self.GetPackagesByPackageFamily(family, C.byref(count), None, C.byref(size), None)
        if code == 0 and count.value == 0:
            return []
        if code != 122 or not 0 < count.value <= 64 or not 0 < size.value <= 262144:
            raise NativeError('app_identity', code=code)
        names, buffer = (C.c_wchar_p * count.value)(), C.create_unicode_buffer(size.value)
        code = self.GetPackagesByPackageFamily(family, C.byref(count), names, C.byref(size), buffer)
        if code:
            raise NativeError('app_identity', code=code)
        return list(names)[:count.value]

    def package_path(self, name):
        size = U32()
        code = self.GetPackagePathByFullName(name, C.byref(size), None)
        if code != 122 or not 0 < size.value <= 32768:
            raise NativeError('app_identity', code=code)
        buffer = C.create_unicode_buffer(size.value)
        code = self.GetPackagePathByFullName(name, C.byref(size), buffer)
        if code:
            raise NativeError('app_identity', code=code)
        return buffer.value

    def session(self, pid=None):
        value = U32()
        self.check(self.ProcessIdToSessionId(pid or self.GetCurrentProcessId(), C.byref(value)),
                   'process_session')
        return value.value

    def entries(self):
        handle = self.CreateToolhelp32Snapshot(2, 0)
        if handle in (None, PTR(-1).value):
            raise NativeError('process_snapshot', code=C.get_last_error())
        try:
            entry, rows = Entry(), []
            entry.size = C.sizeof(entry)
            found = self.Process32FirstW(handle, C.byref(entry))
            while found:
                if entry.pid:
                    rows.append(dict(pid=entry.pid, parent=entry.parent, name=entry.name))
                found = self.Process32NextW(handle, C.byref(entry))
            if C.get_last_error() != 18:  # ERROR_NO_MORE_FILES is the only complete scan.
                raise NativeError('process_snapshot', code=C.get_last_error())
            return rows
        finally:
            self.CloseHandle(handle)

    def facts(self, handle, pid):
        born, exited, kernel, user = FileTime(), FileTime(), FileTime(), FileTime()
        self.check(self.GetProcessTimes(handle, C.byref(born), C.byref(exited),
                                       C.byref(kernel), C.byref(user)), 'process_identity')
        size, image = U32(32768), C.create_unicode_buffer(32768)
        self.check(self.QueryFullProcessImageNameW(handle, 0, image, C.byref(size)), 'process_identity')
        length = U32()
        code = self.GetPackageFamilyName(handle, C.byref(length), None)
        family = ''
        if code != 15700:  # APPMODEL_ERROR_NO_PACKAGE: ordinary descendant, not a package root.
            if code != 122 or not 0 < length.value <= 4096:
                raise NativeError('process_identity', code=code)
            buffer = C.create_unicode_buffer(length.value)
            code = self.GetPackageFamilyName(handle, C.byref(length), buffer)
            if code:
                raise NativeError('process_identity', code=code)
            family = buffer.value
        return dict(pid=pid, born=(born.high << 32) | born.low, exe=image.value,
                    family=family, session=self.session(pid))

    def alive(self, handle):
        code = self.WaitForSingleObject(handle, 0)
        if code not in (0, 258):
            raise NativeError('process_wait', code=C.get_last_error())
        return code == 258

    def end(self, handle):
        if not self.TerminateProcess(handle, 0):
            code = C.get_last_error()
            if self.alive(handle):
                raise NativeError('process_end', code=code)

    def windows(self, visible=False):
        rows = []
        @ENUM
        def collect(window, _):
            pid = U32()
            if self.GetWindowThreadProcessId(window, C.byref(pid)):
                if not visible or self.IsWindowVisible(window):
                    rows.append((window, pid.value))
            return True
        self.check(self.EnumWindows(collect, 0), 'window_query')
        return rows

    def close_window(self, window, pid):
        current = U32()
        if self.GetWindowThreadProcessId(window, C.byref(current)) and current.value == pid:
            if not self.PostMessageW(window, 0x10, 0, 0) and C.get_last_error() != 1400:
                raise NativeError('window_close', code=C.get_last_error())

    def activate(self, aumid):
        uri = app_uri(aumid)
        initialized = self.CoInitializeEx(None, 6)
        if initialized not in (0, 1, -2147417850):  # RPC_E_CHANGED_MODE: COM already initialized.
            raise NativeError('app_open', code=initialized)
        try:
            result = self.ShellExecuteW(None, 'open', uri, None, None, 1)
            if result <= 32:
                raise NativeError('app_open', 'activation_failed', result)
        finally:
            if initialized in (0, 1):
                self.CoUninitialize()
