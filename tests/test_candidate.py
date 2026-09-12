"""Isolated candidate verification for models add --probe (brief defect 9)."""
import io
import json
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
            def __init__(self, slug=None):
                self.slug = slug
                self.closed = False
                scopes.append(self)
            def __enter__(self):
                return SimpleNamespace(home=Path('/tmp/scope'), catalog=Path('/tmp/cat'))
            def __exit__(self, *exc):
                self.closed = True
                return False

        self.assertTrue(candidate.verify('m/x', _scope=FakeScope,
                                         _run_probe=lambda slug, scope, row=None: True))
        self.assertTrue(candidate.verify('m/x', _scope=FakeScope,
                                         _run_probe=lambda slug, scope, row=None: slug == 'm/x'))
        self.assertFalse(candidate.verify('m/x', _scope=FakeScope,
                                          _run_probe=lambda slug, scope, row=None: False))
        self.assertTrue(all(s.closed for s in scopes))

    def test_verify_forwards_the_row_to_the_probe(self):
        # The add path probes a row that is not in the import-time registry;
        # verify must pass it through so image/compact legs are derived.
        class Scope:
            def __init__(self, slug):
                self.slug = slug
            def __enter__(self):
                return SimpleNamespace(home=Path('/tmp/scope'), catalog=Path('/tmp/cat'))
            def __exit__(self, *exc):
                return False

        seen = []
        candidate.verify('m/x', _scope=Scope,
                         _run_probe=lambda slug, scope, row=None: seen.append(row) or True,
                         row={'modalities': ['text', 'image'], 'context_window': 1})
        self.assertEqual(seen, [{'modalities': ['text', 'image'], 'context_window': 1}])

    def test_legs_for_reads_a_fresh_row_dict(self):
        row = {'modalities': ['text', 'image'], 'context_window': 262144}
        self.assertEqual(candidate.legs_for('m/new', row),
                         ['tool', 'stream', 'image', 'compact'])

    def test_run_probe_matches_round_trip_marker(self):
        scope = SimpleNamespace(home=Path('/tmp/s'), catalog=Path('/tmp/c'))
        run = lambda cmd, **kwargs: SimpleNamespace(
            stdout='{"desktop_runtime_tool_round_trip": "passed"}', returncode=0)
        self.assertTrue(candidate.run_probe('m/x', scope, _run=run))
        run = lambda cmd, **kwargs: SimpleNamespace(stdout='turn failed', returncode=1)
        self.assertFalse(candidate.run_probe('m/x', scope, _run=run))
        # A later leg (image/compact) can fail after the marker is printed;
        # the exit status must still fail the probe.
        run = lambda cmd, **kwargs: SimpleNamespace(
            stdout='{"desktop_runtime_tool_round_trip": "passed"}', returncode=1)
        self.assertFalse(candidate.run_probe('m/x', scope, _run=run))
        scope = SimpleNamespace(home=Path('/tmp/scope-x'), catalog=Path('/tmp/c'))
        seen = []

        def fake_run(cmd, **kwargs):
            seen.append(cmd)
            return SimpleNamespace(stdout='ok', returncode=0)
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


class LegsTests(unittest.TestCase):
    def test_legs_follow_the_row(self):
        self.assertEqual(candidate.legs_for('z-ai/glm-5.3-flash'),
                         ['tool', 'stream', 'image', 'compact'])
        self.assertEqual(candidate.legs_for('nope/nothing'),
                         ['tool', 'stream'])

    def test_run_probe_passes_implied_flags(self):
        scope = SimpleNamespace(home=Path('/tmp/s'), catalog=Path('/tmp/c'))
        seen = []

        def fake_run(cmd, **kwargs):
            seen.append(cmd)
            return SimpleNamespace(
                stdout='{"desktop_runtime_tool_round_trip": "passed"}', returncode=0)

        with mock.patch.object(candidate, 'legs_for',
                               return_value=['tool', 'stream', 'image', 'compact']):
            self.assertTrue(candidate.run_probe('m/x', scope, _run=fake_run))
        flat = ' '.join(str(part) for part in seen[0])
        self.assertIn('--image', flat)
        self.assertIn('--compact', flat)

    def test_main_without_confirm_bills_nothing(self):
        buf = io.StringIO()
        with mock.patch.object(candidate, 'verify',
                               side_effect=AssertionError('must not bill')):
            with mock.patch.object(candidate.sys, 'stdout', buf):
                rc = candidate.main(['z-ai/glm-5.3-flash'])
        self.assertEqual(rc, 0)
        doc = json.loads(buf.getvalue())
        self.assertEqual(doc['legs'], ['tool', 'stream', 'image', 'compact'])
        self.assertFalse(doc['billed'])

    def test_main_with_probe_and_confirm_bills(self):
        buf = io.StringIO()
        with mock.patch.object(candidate, 'verify', return_value=True) as probed:
            with mock.patch.object(candidate.sys, 'stdout', buf):
                rc = candidate.main(['m/x', '--probe', '--confirm'])
        self.assertEqual(rc, 0)
        probed.assert_called_once_with('m/x')
        doc = json.loads(buf.getvalue())
        self.assertEqual(doc['result'], 'passed')


if __name__ == '__main__':
    unittest.main()
