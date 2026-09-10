"""Isolated candidate verification for models add --probe (brief defect 9)."""
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from ai_router import candidate


class VerifySequenceTests(unittest.TestCase):
    def test_pass_and_fail_drive_promotion(self):
        scopes = []

        class FakeScope:
            def __init__(self):
                self.closed = False
                scopes.append(self)
            def __enter__(self):
                return SimpleNamespace(home=Path('/tmp/scope'), catalog=Path('/tmp/cat'))
            def __exit__(self, *exc):
                self.closed = True
                return False

        self.assertTrue(candidate.verify('m/x', _scope=FakeScope,
                                         _run_probe=lambda slug, scope: True))
        self.assertTrue(candidate.verify('m/x', _scope=FakeScope,
                                         _run_probe=lambda slug, scope: slug == 'm/x'))
        self.assertFalse(candidate.verify('m/x', _scope=FakeScope,
                                          _run_probe=lambda slug, scope: False))
        self.assertTrue(all(s.closed for s in scopes))

    def test_run_probe_matches_round_trip_marker(self):
        scope = SimpleNamespace(home=Path('/tmp/s'), catalog=Path('/tmp/c'))
        run = lambda cmd, **kwargs: SimpleNamespace(
            stdout='{"desktop_runtime_tool_round_trip": "passed"}')
        self.assertTrue(candidate.run_probe('m/x', scope, _run=run))
        run = lambda cmd, **kwargs: SimpleNamespace(stdout='turn failed')
        self.assertFalse(candidate.run_probe('m/x', scope, _run=run))
        scope = SimpleNamespace(home=Path('/tmp/scope-x'), catalog=Path('/tmp/c'))
        seen = []

        def fake_run(cmd, **kwargs):
            seen.append(cmd)
            return SimpleNamespace(stdout='ok')
        candidate.run_probe('m/x', scope, _run=fake_run)
        flat = ' '.join(str(part) for part in seen[0])
        self.assertIn('--router-state', flat)
        self.assertIn('scope-x', flat)
        self.assertIn('--catalog', flat)

    def test_wait_healthy_sleeps_between_polls(self):
        scope = candidate.IsolatedRouter()
        try:
            scope.state = {'port': 1, 'token': 't'}
            calls = {'n': 0}

            class Resp:
                def __init__(self, body):
                    self.status, self.body = 200, body
                def read(self):
                    return self.body
                def __enter__(self):
                    return self
                def __exit__(self, *exc):
                    return False

            def fake_urlopen(url, timeout=None):
                calls['n'] += 1
                if calls['n'] < 3:
                    return Resp(b'{"status": "starting"}')
                return Resp(b'{"status": "ok"}')

            sleeps = []
            with mock.patch.object(candidate.urllib.request, 'urlopen', fake_urlopen), \
                    mock.patch.object(candidate.time, 'sleep', sleeps.append), \
                    mock.patch.object(candidate.time, 'monotonic',
                                      side_effect=[0, 0, 1, 2, 3, 100]):
                self.assertTrue(scope._wait_healthy())
            self.assertEqual(calls['n'], 3)
            self.assertEqual(sleeps, [0.5, 0.5])
        finally:
            scope.close()

    def test_boot_failure_tears_down_child_and_home(self):
        scope = candidate.IsolatedRouter()
        tmpdir = scope.tmp.name
        terminated = []

        class FakeProc:
            def terminate(self):
                terminated.append(True)
            def wait(self, timeout=None):
                return 0

        with mock.patch.dict(os.environ, {'OPENROUTER_API_KEY': 'test-key'}), \
                mock.patch.object(candidate.subprocess, 'run',
                                  return_value=SimpleNamespace(returncode=0)), \
                mock.patch.object(candidate.subprocess, 'Popen',
                                  return_value=FakeProc()), \
                mock.patch.object(candidate.IsolatedRouter, '_wait_healthy',
                                  return_value=False):
            with self.assertRaisesRegex(SystemExit, 'failed to start'):
                scope.boot()
        self.assertEqual(terminated, [True])
        self.assertIsNone(scope.process)
        self.assertFalse(Path(tmpdir).exists())

    def test_restart_keeps_home_port_token(self):
        scope = candidate.IsolatedRouter()
        home = Path(scope.tmp.name)
        terminated = []

        class FakeProc:
            def terminate(self):
                terminated.append(True)
            def wait(self, timeout=None):
                return 0

        scope.process = FakeProc()
        scope.state = {'port': 5, 'token': 't'}
        scope.catalog = home / 'candidate-catalogue.json'
        spawned = []
        try:
            with mock.patch.dict(os.environ, {'OPENROUTER_API_KEY': 'test-key'}), \
                    mock.patch.object(candidate.subprocess, 'Popen',
                                      side_effect=lambda *a, **k: spawned.append(k) or FakeProc()), \
                    mock.patch.object(candidate.IsolatedRouter, '_wait_healthy',
                                      return_value=True):
                scope.restart()
                self.assertTrue(home.exists())
                self.assertEqual(scope.state, {'port': 5, 'token': 't'})
                self.assertEqual(scope.catalog, home / 'candidate-catalogue.json')
        finally:
            scope.process = None
            scope.close()
        self.assertEqual(terminated, [True])
        self.assertEqual(len(spawned), 1)
        self.assertEqual(spawned[0]['env']['ROUTER_HOME'], str(home))

    def test_boot_without_credential_fails_before_billing(self):
        with mock.patch.dict(os.environ, {'OPENROUTER_API_KEY': ''}):
            scope = candidate.IsolatedRouter()
            try:
                with self.assertRaisesRegex(SystemExit, 'credential'):
                    scope.boot()
            finally:
                scope.close()
            self.assertIsNone(scope.process)


if __name__ == '__main__':
    unittest.main()
