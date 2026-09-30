"""Isolated candidate verification for models add --probe (brief defect 9)."""
import io
import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from ai_router import candidate, candidate_evidence, registry
from ai_router.credentials import opencode_auth_path
from tests.candidate_fixtures import proof


class VerifySequenceTests(unittest.TestCase):
    def test_structured_result_and_failure_both_close_scope(self):
        scopes = []

        class FakeScope:
            def __init__(self, slug=None, **kwargs):
                self.slug = slug
                self.closed = False
                scopes.append(self)
            def __enter__(self):
                return SimpleNamespace(home=Path('/tmp/scope'), catalog=Path('/tmp/cat'))
            def __exit__(self, *exc):
                self.closed = True
                return False

        record = proof(registry.MODELS[0])
        self.assertEqual(candidate.verify('m/x', _scope=FakeScope,
                         _run_probe=lambda slug, scope, row=None: record), record)
        self.assertIsNone(candidate.verify('m/x', _scope=FakeScope,
                         _run_probe=lambda slug, scope, row=None: None))
        self.assertTrue(all(s.closed for s in scopes))

    def test_verify_forwards_the_row_to_the_probe(self):
        # The add path probes a row that is not in the import-time registry;
        # verify must pass it through so image/compact legs are derived.
        class Scope:
            def __init__(self, slug, **kwargs):
                self.slug = slug
                seen.append(kwargs)
            def __enter__(self):
                return SimpleNamespace(home=Path('/tmp/scope'), catalog=Path('/tmp/cat'))
            def __exit__(self, *exc):
                return False

        seen = []
        candidate.verify('m/x', _scope=Scope,
                         _run_probe=lambda slug, scope, row=None: seen.append(row) or True,
                         row={'modalities': ['text', 'image'], 'context_window': 1})
        row = {'modalities': ['text', 'image'], 'context_window': 1}
        self.assertEqual(seen, [{'row': row, 'bounded': True}, row])

    def test_legs_for_reads_a_fresh_row_dict(self):
        row = {'modalities': ['text', 'image'], 'context_window': 262144}
        self.assertEqual(candidate.legs_for('m/new', row),
                         ['tool', 'stream', 'image', 'compact'])

    def test_run_probe_requires_structured_evidence_and_successful_exit(self):
        scope = SimpleNamespace(home=Path('/tmp/s'), catalog=Path('/tmp/c'))
        record = proof(registry.MODELS[0])
        run = lambda cmd, **kwargs: SimpleNamespace(
            stdout=json.dumps(record), returncode=0)
        self.assertEqual(candidate.run_probe('m/x', scope, _run=run), record)
        run = lambda cmd, **kwargs: SimpleNamespace(stdout='turn failed', returncode=1)
        self.assertIsNone(candidate.run_probe('m/x', scope, _run=run))
        # An interrupted child must not certify its earlier successful routes.
        run = lambda cmd, **kwargs: SimpleNamespace(
            stdout=json.dumps(record), returncode=1)
        failed = candidate.run_probe('m/x', scope, _run=run)
        self.assertTrue(all(r['result'] == 'fail' for r in failed['routes']))
        # A failed Claude Code route explains the exit, so the Codex pass stays
        # recorded (it read as a failure twice on 29 Sep) and promotion stays blocked.
        record['routes'][1]['result'] = 'fail'
        run = lambda cmd, **kwargs: SimpleNamespace(stdout=json.dumps(record), returncode=1)
        kept = candidate.run_probe('m/x', scope, _run=run)
        self.assertEqual([r['result'] for r in kept['routes']], ['pass', 'fail'])
        self.assertTrue(candidate_evidence.problems(registry.MODELS[0], kept))
        scope = SimpleNamespace(home=Path('/tmp/scope-x'), catalog=Path('/tmp/c'))
        seen = []

        def fake_run(cmd, **kwargs):
            seen.append(cmd)
            return SimpleNamespace(stdout='ok', returncode=0)
        candidate.run_probe('m/x', scope, _run=fake_run)
        flat = ' '.join(str(part) for part in seen[0])
        self.assertIn('probe_candidate.py', flat)
        self.assertIn('--home', flat)
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

    def test_boot_passes_ambient_opencode_auth_as_path_reference(self):
        # The isolated router may reference the ambient opencode auth file
        # by path (as the installed router does); the key value itself is
        # never copied.
        seen = {}

        def spy_boot(self):
            seen['opencode_auth'] = self.state.get('opencode_auth')
            raise SystemExit('stop before spawn')

        with mock.patch.object(candidate.IsolatedRouter, '_spawn', spy_boot):
            with mock.patch.dict(os.environ, {'OPENROUTER_API_KEY': ''}):
                scope = candidate.IsolatedRouter()
                try:
                    scope.boot()
                    self.fail('boot did not stop before spawn')
                except SystemExit:
                    pass
                finally:
                    scope.close()
        expected = opencode_auth_path(os.environ)
        self.assertEqual(seen.get('opencode_auth'),
                         str(expected) if expected.exists() else None)

    def test_boot_without_credential_fails_before_billing(self):
        # No ambient auth file either: the isolated probe must fail closed
        # before spawning anything billable.
        with mock.patch('ai_router.credentials.opencode_auth_path',
                        return_value=Path('/nonexistent-auth.json')):
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

    def test_drop_images_row_implies_no_image_leg(self):
        # A row that drops images by design has no media leg to prove: the
        # probe would assert the model saw an image the router replaced with
        # a note, so the row fails a leg it can never pass.
        row = {'modalities': ['text', 'image'], 'context_window': 500000,
               'drop_images': True}
        self.assertEqual(candidate.legs_for('x-ai/grok-4.7', row),
                         ['tool', 'stream', 'compact'])

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
        row = registry.MODELS[0]
        record = proof(row)
        with mock.patch.object(candidate, 'verify', return_value=record) as probed:
            with mock.patch.object(candidate.sys, 'stdout', buf):
                rc = candidate.main([row.slug, '--probe', '--confirm'])
        self.assertEqual(rc, 0)
        probed.assert_called_once_with(row.slug)
        doc = json.loads(buf.getvalue())
        self.assertEqual(doc, record)


if __name__ == '__main__':
    unittest.main()
