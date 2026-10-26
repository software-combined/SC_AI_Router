"""Real Win32 process contracts use only children created by this test."""
import os
import ctypes as C
import concurrent.futures
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.test_native_setup import module


@unittest.skipUnless(os.name == 'nt', 'native Windows process integration')
class WindowsNativeLifecycleTests(unittest.TestCase):
    def child(self):
        child = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(30)'],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=0x08000000)
        def close():
            if child.poll() is None:
                child.terminate()  # Popen retains this test child's process handle.
            child.wait(timeout=5)
        self.addCleanup(close)
        return child

    def test_verified_native_handle_ends_only_our_child(self):
        api = module('windows_native').Native()
        child = self.child()
        with api.opened(child.pid, terminate=True) as handle:
            facts = api.facts(handle, child.pid)
            self.assertEqual(facts['pid'], child.pid)
            self.assertEqual(facts['session'], api.session())
            self.assertEqual(api.user(handle), api.user())
            self.assertTrue(facts['born'])
            api.end(handle)
            self.assertEqual(child.wait(timeout=5), 0)
            self.assertFalse(api.alive(handle))

    def test_fifty_owned_processes_are_checked_within_two_hundred_ms(self):
        policy = module('windows_codex')
        api = policy.bindings()
        children = [self.child() for _ in range(50)]
        exe = Path(sys.executable).resolve()
        identity = dict(root=str(exe.parent), exe=str(exe), family='synthetic-query',
                        user=api.user(), session=api.session())
        started = time.perf_counter()
        rows = policy.snapshot(identity, {}, (), api=api)
        elapsed = (time.perf_counter() - started) * 1000
        self.assertTrue({child.pid for child in children}.issubset(rows))
        print('windows_native_scan processes=50 elapsed_ms=%.1f' % elapsed)
        self.assertLess(elapsed, 200)

    def test_shutdown_ends_a_real_job_tree_through_its_retained_root_handle(self):
        policy = module('windows_codex')
        desktop = module('claude_desktop_platform')
        api = policy.bindings()
        token, size, elevated = C.c_void_p(), C.c_uint32(), C.c_uint32()
        api.check(api.OpenProcessToken(api.GetCurrentProcess(), 8, C.byref(token)), 'fixture_token')
        try:
            api.check(api.GetTokenInformation(token, 20, C.byref(elevated), C.sizeof(elevated),
                                             C.byref(size)), 'fixture_elevation')
        finally:
            api.CloseHandle(token)
        if os.environ.get('SCG_REQUIRE_STANDARD_USER') == '1':
            self.assertEqual(elevated.value, 0, 'Run the acceptance test without elevation')
        fixture = Path(__file__).with_name('windows_shutdown_fixture.py')
        root = subprocess.Popen([sys.executable, '-I', str(fixture)],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, creationflags=0x08000000)
        def cleanup():
            if root.poll() is None:
                root.terminate()  # Only the fixture's retained Popen handle.
            root.wait(timeout=5)
            root.stdout.close()
        self.addCleanup(cleanup)
        # A readiness timeout ends the root so the reader cannot remain blocked.
        with concurrent.futures.ThreadPoolExecutor() as reader:
            future = reader.submit(root.stdout.readline)
            try:
                pids = set(json.loads(future.result(timeout=10)))
            except Exception:
                cleanup()
                raise
        self.assertIn(root.pid, pids)
        entries = api.entries
        ended, end = [], api.end
        def terminate(handle):
            ended.append(handle)
            end(handle)
        identity = dict(root=str(fixture.parent), exe=str(Path(sys.executable).resolve()),
                        family='fixture-only', user=api.user(), session=api.session())
        record = {}
        with mock.patch.object(policy, 'validate'), mock.patch.object(policy, 'open_app'), \
                mock.patch.object(policy, 'identity', return_value=identity), \
                mock.patch.object(api, 'entries', side_effect=lambda: [r for r in entries() if r['pid'] in pids]), \
                mock.patch.object(api, 'end', side_effect=terminate):
            started = time.monotonic()
            self.assertTrue(policy.stop(identity, lambda rows, seen: desktop._writers(
                rows, identity, seen, 'win32', ()), api=api, allow_terminate=True, record=record))
        elapsed = time.monotonic() - started
        self.assertEqual(len(ended), 1)  # Root exit closes the job and ends its children.
        self.assertLess(elapsed, 15)
        self.assertFalse(pids & {r['pid'] for r in api.entries()})
        print('windows_native_job_shutdown processes=%d elevated=%s elapsed_ms=%.1f' %
              (len(pids), bool(elevated.value), elapsed * 1000))

    def test_compiled_progress_protocol_closes_when_its_parent_pipe_closes(self):
        from tests.test_native_menu_build import build
        with tempfile.TemporaryDirectory() as temporary:
            resources = Path(temporary)
            (resources / 'installer.json').write_text('{}')
            helper = build.build(resources, 'windows/x86_64')
            icon = Path(__file__).resolve().parents[1] / 'packaging/assets/router-icon.png'
            result = subprocess.run([str(helper), '--progress', str(icon)],
                input=json.dumps(dict(text='Waiting for a test operation.', labels=['Cancel'])) + '\n',
                capture_output=True, text=True, encoding='utf-8', timeout=15,
                creationflags=0x08000000)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout.strip(), 'SCG_ROUTER_DIALOG_RESULT=cancel')


if __name__ == '__main__':
    unittest.main()
