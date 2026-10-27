"""Run Windows core and native contracts under the disposable CI account."""
import argparse
import ctypes as C
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest


def profile():
    # ProcessStartInfo's explicit environment must not inherit the runner's profile.
    shell = C.WinDLL('shell32', use_last_error=True)
    shell.SHGetFolderPathW.argtypes = (C.c_void_p, C.c_int, C.c_void_p, C.c_uint32, C.c_wchar_p)
    for name, kind in (('USERPROFILE', 0x28), ('APPDATA', 0x1A), ('LOCALAPPDATA', 0x1C)):
        value = C.create_unicode_buffer(32768)
        if shell.SHGetFolderPathW(None, kind, None, 0, value) != 0:
            raise OSError('CI user profile unavailable')
        os.environ[name] = value.value
    os.environ['HOME'] = os.environ['USERPROFILE']


def cleanup(expected_sid):
    if os.name != 'nt' or os.environ.get('GITHUB_ACTIONS') != 'true':
        raise RuntimeError('Cleanup requires the disposable Windows GitHub runner')
    from tests.test_native_setup import module
    api = module('windows_native').Native()
    ended = 0
    if expected_sid == api.user():
        raise RuntimeError('Refusing to clean up the invoking account')
    for row in api.entries():
        try:
            with api.opened(row['pid'], terminate=True) as handle:
                if api.user(handle) == expected_sid:
                    api.end(handle)  # Owner check and termination use the same retained handle.
                    ended += 1
        except OSError:
            pass  # Protected unrelated processes and processes already leaving.
    print('windows_standard_cleanup ended=%d' % ended, flush=True)


def run(expected_sid, report):
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    os.chdir(root)
    from tests.test_native_setup import module
    api = module('windows_native').Native()
    sid = api.user()
    token, size, elevated = C.c_void_p(), C.c_uint32(), C.c_uint32()
    api.check(api.OpenProcessToken(api.GetCurrentProcess(), 8, C.byref(token)), 'ci_token')
    try:
        api.check(api.GetTokenInformation(token, 20, C.byref(elevated), C.sizeof(elevated),
                                         C.byref(size)), 'ci_elevation')
    finally:
        api.CloseHandle(token)
    if sid != expected_sid or elevated.value or C.windll.shell32.IsUserAnAdmin():
        raise RuntimeError('CI child must use the expected standard account')
    profile()
    subprocess.run(['git', '--version'], check=True, timeout=10)
    os.environ['SCG_REQUIRE_STANDARD_USER'] = '1'
    os.environ.pop('SCG_RUN_INSTALLER_TESTS', None)
    print('windows_standard sid=%s elevated=false profile_loaded=true' % sid, flush=True)
    outcomes = []
    for name, suite in (
            ('core', lambda: unittest.defaultTestLoader.discover('tests', top_level_dir='.')),
            ('native', lambda: unittest.defaultTestLoader.loadTestsFromNames([
                'tests.test_windows_native_lifecycle', 'tests.test_windows_acl_native']))):
        started = time.monotonic()
        result = unittest.TextTestRunner(verbosity=1).run(suite())
        outcomes.append(dict(suite=name, tests=result.testsRun, skipped=len(result.skipped),
                             success=result.wasSuccessful(), elapsed_s=time.monotonic() - started))
    status = 0 if all(row['success'] for row in outcomes) else 1
    Path(report).write_text(json.dumps(dict(sid=sid, elevated=False, status=status,
                                           suites=outcomes)), encoding='utf-8')
    return status


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sid', required=True)
    parser.add_argument('--report')
    parser.add_argument('--cleanup', action='store_true')
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    if args.cleanup:
        cleanup(args.sid)
    else:
        if not args.report:
            parser.error('--report is required for the standard-user suite')
        sys.exit(run(args.sid, args.report))
