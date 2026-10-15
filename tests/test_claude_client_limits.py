"""Opt-in real-client limits on a local fake upstream; no model calls.

Run separately with SCG_TEST_CLAUDE_CLIENT=1 and CLAUDE_BIN set to the tested
client. The normal unit suite never starts an installed Claude client.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

from tools import capture_claude_shapes as capture
from tools.claude_probe_env import environment


@unittest.skipUnless(os.environ.get('SCG_TEST_CLAUDE_CLIENT') == '1', 'opt-in real-client check')
class ClientLimitsTests(unittest.TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory(prefix='scg-claude-limits-')
        self.addCleanup(root.cleanup)
        self.root = Path(root.name)
        self.sink = capture.Sink()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), capture._handler(self.sink))
        worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(worker.join, 10)
        self.addCleanup(self.server.shutdown)
        self.env = environment(self.root, 'http://127.0.0.1:%d/synthetic/' % self.server.server_port,
                               'synthetic-limit-token', 'low', {
                                   'ENABLE_TOOL_SEARCH': 'true'})
        self.mcp = self.root / 'mcp.json'
        self.mcp.write_text(json.dumps({'mcpServers': {'stubtools': {
            'command': os.sys.executable,
            'args': [str(capture.STUB_MCP), '--tools', '700']}}}))
        version = subprocess.run([capture.CLAUDE_BIN, '--version'], capture_output=True,
                                 text=True, timeout=10)
        self.version = version.stdout.strip()

    def run_client(self, resume=None):
        command = [capture.CLAUDE_BIN, '-p', 'Run the synthetic tool check.',
                   '--model', 'z-ai/glm-5.3-flash', '--strict-mcp-config',
                   '--mcp-config', str(self.mcp), '--allowedTools', 'ToolSearch', capture.STUB_TOOL,
                   '--output-format', 'json']
        if resume:
            command += ['--resume', resume]
        done = subprocess.run(command, cwd=self.root, env=self.env, capture_output=True,
                              text=True, timeout=60)
        return done, json.loads(done.stdout[done.stdout.find('{'):])

    def test_turn_and_output_caps_apply_after_resume(self):
        loop = (('tool_search', 'select:' + capture.STUB_TOOL),) + (
            ('tool_call', capture.STUB_TOOL),) * 10
        self.sink.script = loop
        first, report = self.run_client()
        self.assertEqual(report.get('subtype'), 'error_max_turns')
        self.assertNotEqual(first.returncode, 0)
        self.assertEqual(len(self.sink.requests), 3)
        session = report.get('session_id')
        self.assertTrue(session)
        self.sink.script = loop[:3] + loop
        second, report = self.run_client(session)
        self.assertEqual(report.get('subtype'), 'error_max_turns')
        self.assertNotEqual(second.returncode, 0)
        self.assertEqual(len(self.sink.requests), 6)
        self.assertEqual([row['max_tokens'] for row in self.sink.requests], [2048] * 6)
        print(json.dumps({'check': 'turn-and-output-cap-with-resume', 'client': self.version,
                          'requests': 6, 'turn_cap_per_run': 3, 'output_cap': 2048}))

    def test_http_failure_stops_with_a_bounded_client_recovery(self):
        self.sink.script = (('http_error', 503),) * 12
        done, report = self.run_client()
        self.assertTrue(report.get('is_error'))
        self.assertNotEqual(done.returncode, 0)
        # Client versions may stop immediately or make one separate 503 recovery.
        # Require a real attempt while preserving the two-request upper bound.
        self.assertIn(len(self.sink.requests), (1, 2))
        print(json.dumps({'check': 'bounded-http-503-recovery', 'client': self.version,
                          'requests': len(self.sink.requests)}))


if __name__ == '__main__':
    unittest.main()
