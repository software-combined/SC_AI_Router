"""Real Win32 process contracts use only children created by this test."""
import os
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

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
