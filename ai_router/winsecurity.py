"""Read Windows security descriptors without starting a process (Python 3.9+)."""
import ctypes as C
from functools import lru_cache

U32, U16, U8, PTR = C.c_uint32, C.c_uint16, C.c_ubyte, C.c_void_p


class AclSize(C.Structure):
    _fields_ = [('count', U32), ('used', U32), ('free', U32)]


class AceHeader(C.Structure):
    _fields_ = [('kind', U8), ('flags', U8), ('size', U16)]


class QueryError(OSError):
    def __init__(self, operation, code):
        self.operation = operation
        super().__init__(code, 'Windows permission query failed')


def _bind(dll, name, result, *arguments):
    function = getattr(dll, name)
    function.restype, function.argtypes = result, arguments
    return function


@lru_cache(maxsize=1)
def _api():
    """Bind lazily: installers can import this module on every supported OS."""
    kernel = C.WinDLL('kernel32', use_last_error=True)
    security = C.WinDLL('advapi32', use_last_error=True)
    api = type('WindowsSecurity', (), {})()
    signatures = (
        (kernel, 'GetCurrentProcess', PTR, ()),
        (kernel, 'GetCurrentThread', PTR, ()),
        (kernel, 'CloseHandle', C.c_int, (PTR,)),
        (kernel, 'LocalFree', PTR, (PTR,)),
        (security, 'OpenThreadToken', C.c_int, (PTR, U32, C.c_int, C.POINTER(PTR))),
        (security, 'OpenProcessToken', C.c_int, (PTR, U32, C.POINTER(PTR))),
        (security, 'GetTokenInformation', C.c_int, (PTR, C.c_int, PTR, U32, C.POINTER(U32))),
        (security, 'GetNamedSecurityInfoW', U32,
         (C.c_wchar_p, C.c_int, U32) + (C.POINTER(PTR),) * 5),
        (security, 'GetSecurityDescriptorDacl', C.c_int,
         (PTR, C.POINTER(C.c_int), C.POINTER(PTR), C.POINTER(C.c_int))),
        (security, 'IsValidAcl', C.c_int, (PTR,)),
        (security, 'GetAclInformation', C.c_int, (PTR, PTR, U32, C.c_int)),
        (security, 'GetAce', C.c_int, (PTR, U32, C.POINTER(PTR))),
        (security, 'IsValidSid', C.c_int, (PTR,)),
        (security, 'ConvertSidToStringSidW', C.c_int, (PTR, C.POINTER(PTR))),
    )
    for dll, name, result, arguments in signatures:
        setattr(api, name, _bind(dll, name, result, *arguments))
    return api


def _call(api, name, *arguments):
    if not getattr(api, name)(*arguments):
        raise QueryError(name, C.get_last_error())


def _sid(api, pointer):
    if not pointer:
        raise ValueError('missing SID')
    _call(api, 'IsValidSid', pointer)
    text = PTR()
    try:
        _call(api, 'ConvertSidToStringSidW', pointer, C.byref(text))
        if not text.value:
            raise ValueError('missing SID string')
        return C.wstring_at(text)
    finally:
        if text.value:
            api.LocalFree(text)


def _user(api):
    token = PTR()
    try:
        if not api.OpenThreadToken(api.GetCurrentThread(), 8, True, C.byref(token)):
            code = C.get_last_error()
            if code != 1008:  # ERROR_NO_TOKEN: the process is not impersonating.
                raise QueryError('OpenThreadToken', code)
            _call(api, 'OpenProcessToken', api.GetCurrentProcess(), 8, C.byref(token))
        size = U32()
        if api.GetTokenInformation(token, 1, None, 0, C.byref(size)) or C.get_last_error() != 122:
            raise QueryError('GetTokenInformation', C.get_last_error())
        if not C.sizeof(PTR) <= size.value <= 65536:
            raise ValueError('invalid token size')
        buffer = C.create_string_buffer(size.value)
        _call(api, 'GetTokenInformation', token, 1, buffer, size, C.byref(size))
        return _sid(api, C.cast(buffer, C.POINTER(PTR)).contents.value)
    finally:
        if token.value:
            api.CloseHandle(token)


def _rules(api, acl):
    _call(api, 'IsValidAcl', acl)
    info = AclSize()
    _call(api, 'GetAclInformation', acl, C.byref(info), C.sizeof(info), 2)
    if info.used < 8 or info.count > (info.used - 8) // 16:
        raise ValueError('invalid ACL size')
    rules = []
    for index in range(info.count):
        pointer = PTR()
        _call(api, 'GetAce', acl, index, C.byref(pointer))
        if not pointer.value or not acl.value + 8 <= pointer.value <= acl.value + info.used - 4:
            raise ValueError('invalid ACE pointer')
        header = AceHeader.from_address(pointer.value)
        if (header.kind not in (0, 1) or header.size < 16
                or pointer.value + header.size > acl.value + info.used):
            raise ValueError('unsupported ACE')
        sid = pointer.value + 8
        revision, count = C.string_at(sid, 2)
        if revision != 1 or count > 15 or 8 + 4 * count > header.size - 8:
            raise ValueError('invalid ACE SID size')
        rules.append(dict(sid=_sid(api, sid), type=header.kind, flags=header.flags,
                          mask=U32.from_address(pointer.value + 4).value))
    return rules


def query(path, api=None):
    """Return SID/owner/DACL facts; raise on API failure or unsupported structure."""
    api = _api() if api is None else api
    doc = {'user': _user(api)}
    if path is None:
        return doc
    owner, acl, descriptor = PTR(), PTR(), PTR()
    try:
        code = api.GetNamedSecurityInfoW(str(path), 1, 5, C.byref(owner), None,
                                         C.byref(acl), None, C.byref(descriptor))
        if code:
            raise QueryError('GetNamedSecurityInfoW', code)
        if not descriptor.value:
            raise ValueError('missing security descriptor')
        present, defaulted = C.c_int(), C.c_int()
        _call(api, 'GetSecurityDescriptorDacl', descriptor, C.byref(present),
              C.byref(acl), C.byref(defaulted))
        doc.update(owner=_sid(api, owner), dacl=bool(present.value and acl.value),
                   rules=_rules(api, acl) if present.value and acl.value else [])
        return doc
    finally:
        if descriptor.value:
            api.LocalFree(descriptor)
