"""Terminal ownership on the ChatGPT helper fallback's stream."""
import json
import unittest

from tests import test_subscription_fallback as fallback_suite
from tests.fakes import install_fake
from tests.harness import auth_file, post, start_server, test_state


class SubscriptionStreamFallbackTests(unittest.TestCase):
    def test_twin_stream_failure_has_one_provider_terminal(self):
        failed = (b'data: {"type":"response.failed",'
                  b'"response":{"error":{"code":"overloaded"}}}\n\n')
        install_fake(self, fallback_suite._sequence(
            (429, b'{}', []),
            (200, failed, [('Content-Type', 'text/event-stream')])))
        state = test_state(auth_file(self))
        state['openai_models'] = ['gpt-6-luna', 'gpt-5.5']
        state['openai_helper_fallback'] = True
        server = start_server(state)
        self.addCleanup(server.shutdown)
        with self.assertLogs('codex_router', level='INFO') as logs:
            response = post(server.server_port, '/test-token/responses',
                            {'model': fallback_suite.HELPER, 'input': [],
                             'stream': True}, fallback_suite.HEADERS)
            self.assertEqual(response.status, 200)
            body = response.read()
        frames = [json.loads(line[6:]) for line in body.splitlines()
                  if line.startswith(b'data: ')]
        self.assertEqual(
            sum(event['type'] == 'response.failed' for event in frames), 1)
        events = [json.loads(record.getMessage()) for record in logs.records]
        failure = next(event for event in events
                       if event.get('event') == 'request_failed')
        self.assertEqual(failure['terminal_source'], 'upstream')


if __name__ == '__main__':
    unittest.main()
