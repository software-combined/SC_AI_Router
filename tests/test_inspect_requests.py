"""The installed inspector reads rotated evidence and never prints other data."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class InspectRequestsTests(unittest.TestCase):
    def test_cli_filters_rotated_attempts_and_drops_content(self):
        with tempfile.TemporaryDirectory() as directory:
            logs = Path(directory) / 'logs'
            logs.mkdir()
            def row(ident, status, model='~fixture/model'):
                return {'event': 'attempt_ledger', 'ts': '2026-09-28T01:00:00+00:00',
                    'request_id': ident * 32, 'router_version': '0.6.136',
                    'operation': '/responses', 'protocol': 'responses', 'route': 'openrouter',
                    'outcome': 'success', 'sends': 1, 'prompt': 'PRIVATE CONTENT',
                    'attempt_evidence': [{'attempt': 1, 'reason': 'initial',
                        'requested_model': model, 'upstream_model': model,
                        'model_status': status, 'model_reports': [],
                        'effort_status': 'unverified', 'arguments': 'PRIVATE CONTENT'}]}
            (logs / 'router.jsonl.1').write_text(json.dumps(row('a', 'unverified')) + '\n')
            (logs / 'router.jsonl').write_text('\n'.join((
                json.dumps({'event': 'request_completed', 'served_model': 'PRIVATE CONTENT'}),
                '{malformed', json.dumps(row('b', 'mismatch')),
                json.dumps(row('c', 'unverified', 'another/model')))) + '\n')
            command = [sys.executable, '-m', 'ai_router.inspect_requests',
                       '--home', directory, '--minutes', '0', '--json']
            result = subprocess.run(command + ['--model', '~fixture/model'],
                                    capture_output=True, text=True, check=True)
            found = json.loads(result.stdout)
            self.assertEqual([r['request_id'] for r in found], ['b' * 32, 'a' * 32])
            self.assertNotIn('PRIVATE CONTENT', result.stdout)
            selected = subprocess.run(command + ['--identity', 'mismatch'],
                                      capture_output=True, text=True, check=True)
            self.assertEqual([r['request_id'] for r in json.loads(selected.stdout)], ['b' * 32])
            selected = subprocess.run(command + ['--request-id', 'a' * 32],
                                      capture_output=True, text=True, check=True)
            self.assertEqual(len(json.loads(selected.stdout)), 1)
            readable = subprocess.run(command[:-1] + ['--request-id', 'b' * 32],
                                      capture_output=True, text=True, check=True)
            self.assertIn('mismatch', readable.stdout)
            self.assertIn('~fixture/model', readable.stdout)
            self.assertNotIn('PRIVATE CONTENT', readable.stdout)

    def test_absent_logs_are_an_empty_read_without_creating_state(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-m', 'ai_router.inspect_requests',
                '--home', directory, '--json'], capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(result.stdout), [])
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
