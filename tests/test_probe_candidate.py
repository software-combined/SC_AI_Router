"""The onboarding probe bounds all sends and requires real-client route evidence."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from ai_router import candidate_evidence, provider_defs, registry, transport
from tools import probe_candidate as probe


def prepared(**payload):
    return transport.Prepared('example.invalid', '/test', {}, json.dumps(payload).encode(),
                              {}, provider_defs.DEFAULT_EXTERNAL)


class BudgetTests(unittest.TestCase):
    def test_summary_and_normal_attempts_exhaust_one_shared_budget(self):
        provider = SimpleNamespace(host='example.invalid', defn=provider_defs.OPENROUTER)
        with tempfile.TemporaryDirectory() as folder:
            budget = probe.Budget(Path(folder), Mock())
            summary = Mock(return_value='summary')
            for _ in range(probe.MAX_CALLS - 1):
                budget(None, prepared(max_tokens=10), {})
            self.assertEqual(budget.summary(summary, provider, 'synthetic-key',
                             {'max_output_tokens': 10}, 5), 'summary')
            self.assertEqual(probe.call_count(Path(folder)), probe.MAX_CALLS)
            with self.assertRaisesRegex(ValueError, 'call budget'):
                budget.summary(summary, provider, 'synthetic-key', {'max_output_tokens': 10}, 5)
            summary.assert_called_once_with(provider, 'synthetic-key', {'max_output_tokens': 10}, 5)

    def test_common_budget_counts_both_protocols_and_failed_attempts(self):
        with tempfile.TemporaryDirectory() as folder:
            send = Mock(side_effect=OSError('synthetic connect failure'))
            budget = probe.Budget(Path(folder), send)
            rows = [prepared(max_output_tokens=10), prepared(max_tokens=10)]

            def attempt(index):
                try:
                    budget(None, rows[index % 2], {})
                except (ValueError, OSError):
                    pass

            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(attempt, range(probe.MAX_CALLS + 8)))
            self.assertEqual(send.call_count, probe.MAX_CALLS)
            self.assertEqual(int((Path(folder) / 'probe-calls').read_text()), probe.MAX_CALLS)

    def test_native_oversized_or_uncapped_requests_never_reach_send(self):
        native = prepared(max_tokens=10)
        native.provider = 'openai'
        oversized = prepared(max_tokens=10, input='x' * probe.MAX_INPUT)
        invalid = [native, oversized, prepared(), prepared(max_tokens=True),
                   prepared(max_tokens=probe.MAX_OUTPUT + 1), prepared(max_tokens=0)]
        with tempfile.TemporaryDirectory() as folder:
            send = Mock()
            budget = probe.Budget(Path(folder), send)
            for row in invalid:
                with self.subTest(provider=row.provider, size=len(row.body)):
                    with self.assertRaises(ValueError):
                        budget(None, row, {})
            send.assert_not_called()
            self.assertFalse((Path(folder) / 'probe-calls').exists())


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.row = registry.by_slug('deepseek/deepseek-v4.1-flash')

    def test_server_fetches_key_permissions_without_refreshing_candidate_rows(self):
        from ai_router import availability, compaction_summary, router, runtime
        server = Mock()
        with patch.object(router, 'Router', return_value=server), \
                patch.object(runtime, 'load_state', return_value={}), \
                patch.object(runtime, 'configure_logging'), \
                patch.object(availability, 'refresh') as refresh, \
                patch.object(probe.signal, 'signal'), patch.object(transport, 'post_with_phases'), \
                patch.object(compaction_summary, '_fetch_summary') as summary:
            probe.serve(Path('/tmp/probe'))
            self.assertIs(compaction_summary._fetch_summary.args[0], summary)
            self.assertIs(compaction_summary._fetch_summary.func.__self__, transport.post_with_phases)
        refresh.assert_called_once_with(
            provider_defs.region_host(provider_defs.DEFAULT_EXTERNAL, 'global'),
            server.credentials.key_for.return_value, Path('/tmp/probe'))
        server.serve_forever.assert_called_once()
        server.server_close.assert_called_once()

    def test_codex_legs_follow_candidate_and_client_home_is_removed(self):
        for images in (True, False):
            row = replace(self.row, modalities=('text', 'image'), drop_images=not images,
                          context_window=262144)
            done = SimpleNamespace(returncode=0,
                                   stdout='{"desktop_runtime_tool_round_trip": "passed"}')
            with patch.object(probe.subprocess, 'run', return_value=done) as run:
                self.assertTrue(probe.codex(row, Path('/tmp/probe'), Path('/tmp/catalog')))
            cmd = run.call_args.args[0]
            self.assertEqual('--image' in cmd, images)
            self.assertIn('--compact', cmd)
            self.assertEqual(cmd[cmd.index('--effort') + 1], row.default_reasoning)
            self.assertFalse(Path(cmd[cmd.index('--codex-home') + 1]).exists())
            with patch.object(probe.subprocess, 'run', return_value=SimpleNamespace(
                    returncode=1, stdout=done.stdout)):
                self.assertFalse(probe.codex(row, Path('/tmp/probe'), Path('/tmp/catalog')))

    def test_both_routes_require_client_and_correlated_router_proof(self):
        row = replace(self.row, upstream_id='different/upstream')
        attempt = {'resolved_model': row.slug, 'model_reports': [
            {'value': row.upstream_id, 'source': 'response.model'}], 'effort_reports': []}
        for missing in (False, True):
            calls = [[], [attempt], [], [] if missing else [attempt]]
            with patch.object(probe, 'attempts', side_effect=calls), \
                    patch.object(probe, 'call_count', side_effect=[0, 4, 4, 7]), \
                    patch.object(probe, 'version', return_value='1.2.3'), \
                    patch.object(probe, 'codex', return_value=True), \
                    patch.object(probe.probe_claude_code, 'probe', return_value={'pass': True}) as claude, \
                    patch.object(probe.subprocess, 'run', return_value=SimpleNamespace(
                        returncode=0, stdout='a' * 40)), patch.object(probe.time, 'sleep'):
                record = probe.probe(row, Path('/tmp/probe'), Path('/tmp/catalog'))
            self.assertEqual(bool(candidate_evidence.problems(row, record)), missing)
            self.assertEqual([r['calls'] for r in record['routes']], [4, 3])
            self.assertEqual(claude.call_args.kwargs['expected_model'], row.upstream_id)
            self.assertEqual(claude.call_args.kwargs['read_count'], 2)
            self.assertEqual(claude.call_args.kwargs['max_budget_usd'], 0.25)

    def test_failed_conformance_prevents_billable_clients(self):
        with patch.object(probe.subprocess, 'run', return_value=SimpleNamespace(
                returncode=1, stdout='')), patch.object(probe, 'codex') as codex, \
                patch.object(probe.probe_claude_code, 'probe') as claude:
            record = probe.probe(self.row, Path('/tmp/probe'), Path('/tmp/catalog'))
        codex.assert_not_called()
        claude.assert_not_called()
        self.assertTrue(candidate_evidence.problems(self.row, record))


if __name__ == '__main__':
    unittest.main()
