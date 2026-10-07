"""Child evidence is exact, content-free and never hides failed attempts."""
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import threading
import unittest
import subprocess
import sys
from unittest import mock

from ai_router import inspect_requests, router
from tests.fakes import FakeUpstream, install_fake
from tests.harness import post, start_server, test_state
from tests.test_request_evidence import setup, done

CHILD = '01a11428-40c9-7730-9d3d-8f1717622c04'
OTHER = '01a11428-4166-7140-8b03-4f784b1bcd1e'
PARENT = '01a11351-9d60-7133-b848-8b3232e8667b'
MODEL = 'deepseek/deepseek-v4.1-flash'
CANARY = 'PRIVATE HEADER TOOL CONTENT'
START = datetime(2026, 10, 7, 0, tzinfo=timezone.utc)
END = datetime(2026, 10, 7, 1, tzinfo=timezone.utc)


def record(ident, child=CHILD, timestamp='2026-10-07T00:30:00+00:00', **changes):
    attempt = {'attempt': 1, 'requested_model': MODEL, 'upstream_model': MODEL,
               'model_status': 'provider_reported_match', 'requested_effort': 'high',
               'model_reports': [{'value': MODEL, 'source': 'response.completed.response.model'}],
               'effort_reports': [], 'effort_status': 'unverified', 'reports_limited': False}
    return {'event': 'attempt_ledger', 'request_id': ident * 32, 'thread_id': child,
            'parent_thread_id': PARENT, 'ts': timestamp, 'operation': '/responses',
            'outcome': 'success', 'attempt_evidence': [attempt], **changes}


class AgentIdentityTests(unittest.TestCase):
    def rows(self, *records, **kwargs):
        with tempfile.TemporaryDirectory() as home:
            logs = Path(home) / 'logs'
            logs.mkdir()
            (logs / 'router.jsonl').write_text('\n'.join(map(json.dumps, records)) + '\n')
            return inspect_requests.recent(home, thread_id=CHILD, parent_thread_id=PARENT,
                                           since=START, until=END, **kwargs)

    def test_headers_reach_the_ledger_without_other_metadata(self):
        wire = setup(MODEL) + done(MODEL)
        install_fake(self, lambda: FakeUpstream(200, wire, [('Content-Type', 'text/event-stream')]))
        server = start_server(test_state(None))
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        finished = threading.Event()
        class Handler(router.Handler):
            def do_POST(self):
                try:
                    super().do_POST()
                finally:
                    finished.set()
        server.RequestHandlerClass = Handler
        with mock.patch.object(router, 'log_event') as logged:
            response = post(server.server_port, '/test-token/responses',
                {'model': MODEL, 'stream': True, 'input': [{'role': 'user', 'content': CANARY}]},
                {'Thread-Id': CHILD, 'X-Codex-Parent-Thread-Id': PARENT,
                 'X-Codex-Turn-Metadata': CANARY})
            self.assertEqual(response.status, 200)
            response.read()
            self.assertTrue(finished.wait(2))
        ledger, = [c.kwargs for c in logged.call_args_list if c.args[0] == 'attempt_ledger']
        self.assertEqual((ledger['thread_id'], ledger['parent_thread_id']), (CHILD, PARENT))
        self.assertNotIn(CANARY, json.dumps([c.kwargs for c in logged.call_args_list]))

    def test_exact_child_parent_and_assignment_window_not_arrival_or_model(self):
        rows = self.rows(record('a', OTHER), record('b'), record('c', parent_thread_id=OTHER),
                         record('d', timestamp='2026-10-06T00:30:00+00:00'),
                         record('e', timestamp='2026-10-07T02:30:00+00:00'),
                         record('f', thread_id=None))
        self.assertEqual([r['request_id'] for r in rows], ['b' * 32])

    def test_malformed_ids_are_not_retained_or_matched(self):
        from ai_router.request_evidence import client_threads
        for value in (CANARY, CHILD + '\n' + CANARY, CHILD.upper(), 'a' * 1000):
            self.assertIsNone(client_threads({'thread-id': value})['thread_id'])
        rows = self.rows(record('a', parent_thread_id=CANARY))
        self.assertEqual(rows, [])

    def summary(self, *records):
        return inspect_requests.agent_summary(self.rows(*records), MODEL, 'high', limit=20)

    def test_model_report_and_absent_effort_are_separate(self):
        summary = self.summary(record('a'))
        self.assertEqual(summary['model_status'], 'provider_reported_match')
        self.assertEqual(summary['effort_status'], 'unverified')
        self.assertEqual(summary['coverage'], 'retained_records_only')
        self.assertEqual(summary['model_reports'][0]['request_id'], 'a' * 32)

    def test_mismatch_is_not_hidden_by_a_matching_retry(self):
        row = record('a')
        bad = dict(row['attempt_evidence'][0], attempt=1, model_status='mismatch',
                   model_reports=[{'value': 'another/model', 'source': 'response.model'}])
        row['attempt_evidence'] = [bad, dict(row['attempt_evidence'][0], attempt=2)]
        summary = self.summary(row)
        self.assertEqual(summary['model_status'], 'mismatch')
        self.assertEqual(len(summary['model_reports']), 2)

    def test_missing_truncated_or_failed_records_do_not_claim_complete_match(self):
        for changes in ({'model_reports': [], 'model_status': 'unverified'}, {'reports_limited': True}):
            row = record('a')
            row['attempt_evidence'][0].update(changes)
            self.assertEqual(self.summary(row)['model_status'], 'unverified')
        row = record('a', outcome='unknown')
        self.assertEqual(self.summary(row)['model_status'], 'unverified')
        self.assertEqual(self.summary()['model_status'], 'unverified')

    def test_helpers_are_separate_and_effort_echo_is_only_provider_reported(self):
        row = record('a')
        row['attempt_evidence'][0].update(effort_status='provider_reported_match',
            effort_reports=[{'value': 'high', 'source': 'response.reasoning.effort'}])
        summary = self.summary(row, record('b', operation='/responses/compact'))
        self.assertEqual(summary['helper_requests'], 1)
        self.assertEqual(summary['requests'], 1)
        self.assertEqual(summary['effort_status'], 'provider_reported_match')

    def test_changed_model_effort_and_contradictory_reports_stay_visible(self):
        for field, value, expected in (('requested_model', 'another/model', 'model_status'),
                                       ('requested_effort', 'low', 'effort_status'),
                                       ('model_status', 'contradictory', 'model_status')):
            row = record('a')
            row['attempt_evidence'][0][field] = value
            self.assertIn(self.summary(row)[expected], ('mismatch', 'contradictory'))

    def test_cli_summary_keeps_mismatch_and_rejects_filter_and_unsafe_window(self):
        with tempfile.TemporaryDirectory() as home:
            logs = Path(home) / 'logs'
            logs.mkdir()
            bad = record('a')
            bad['attempt_evidence'][0].update(model_status='mismatch',
                model_reports=[{'value': 'another/model', 'source': 'response.model'}])
            (logs / 'router.jsonl.1').write_text(json.dumps(bad) + '\n')
            (logs / 'router.jsonl').write_text(json.dumps(record('b')) + '\n')
            command = [sys.executable, '-m', 'ai_router.inspect_requests', '--home', home,
                '--agent-summary', '--thread-id', CHILD, '--parent-thread-id', PARENT,
                '--model', MODEL, '--expected-effort', 'high', '--since', START.isoformat(),
                '--until', END.isoformat(), '--json']
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            summary = json.loads(result.stdout)
            self.assertEqual(summary['summary']['model_status'], 'mismatch')
            self.assertEqual(len(summary['records']), 2)
            capped = subprocess.run(command + ['--limit', '1'], capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(capped.stdout)['summary']['model_status'], 'unverified')
            for extra in (['--identity', 'unverified'], ['--until', START.isoformat(),
                '--since', END.isoformat()], ['--since', '2026-10-07T00:00:00'],
                ['--thread-id', CANARY]):
                result = subprocess.run(command + extra, capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)
                self.assertNotIn(CANARY, result.stdout + result.stderr)

    def test_full_page_cannot_hide_an_older_mismatch_behind_a_match(self):
        bad = record('a')
        bad['attempt_evidence'][0].update(model_status='mismatch',
            model_reports=[{'value': 'another/model', 'source': 'response.model'}])
        newer = [record('b'), record('c')]
        for row in newer:
            row['attempt_evidence'][0].update(effort_status='provider_reported_match',
                effort_reports=[{'value': 'high', 'source': 'response.reasoning.effort'}])
        rows = self.rows(bad, *newer, limit=2)
        summary = inspect_requests.agent_summary(rows, MODEL, 'high', limit=2)
        self.assertEqual(summary['model_status'], 'unverified')
        self.assertEqual(summary['effort_status'], 'unverified')
        self.assertTrue(summary['limit_reached'])
        for status in ('mismatch', 'contradictory'):
            bad['attempt_evidence'][0]['model_status'] = status
            visible = inspect_requests.agent_summary(self.rows(newer[0], bad, limit=2),
                                                     MODEL, 'high', limit=2)
            self.assertEqual(visible['model_status'], status)
            self.assertTrue(visible['limit_reached'])


if __name__ == '__main__':
    unittest.main()
