"""The subscription route sends the router's own compaction summary readably.

Defect guarded: a thread that compacted on an OpenRouter model keeps the
router's `ocx1:` compaction item, and Codex replays it on later subscription
turns. The ChatGPT backend cannot read it, so the first attempt failed with
HTTP 400 `invalid_encrypted_content` before the bounded retry rewrote it, and
a turn that also carried a native encrypted child reply failed outright
because the retry refuses an encrypted field it does not own.

Run from the copy root:
  <python> -X utf8 -m unittest tests.test_subscription_router_compaction -v
"""
import copy
import http.client
import json
import unittest
from compression import zstd

from ai_router import compaction, subscription_history
from tests.fakes import FakeUpstream, install_fake
from tests.harness import isolated_home, start_server


SUMMARY = 'the summary the router wrote for this thread'
ROUTER_COMPACTION = {'type': 'compaction', 'id': 'cmp_1',
                     'encrypted_content': compaction.encode_summary(SUMMARY)}
PROJECTED = {'type': 'message', 'role': 'user',
             'content': [{'type': 'input_text',
                          'text': compaction.SUMMARY_PREFIX + '\n\n' + SUMMARY}]}
CHILD_REPLY = {'type': 'agent_message', 'author': '/root/child', 'recipient': '/root',
               'content': [{'type': 'input_text', 'text': 'done'},
                           {'type': 'encrypted_content',
                            'encrypted_content': 'NATIVE-CHILD-BLOB'}]}
MESSAGE = {'type': 'message', 'role': 'user',
           'content': [{'type': 'input_text', 'text': 'carry on'}]}
BODY = json.dumps({'model': 'gpt-6-astra',
                   'input': [ROUTER_COMPACTION, CHILD_REPLY, MESSAGE]}).encode()


class NormalizeTests(unittest.TestCase):
    def test_a_native_compaction_blob_keeps_the_same_payload(self):
        payload = {'input': [MESSAGE, {'type': 'compaction', 'id': 'cmp_2',
                                       'encrypted_content': 'NATIVE-BLOB'}]}
        self.assertIs(subscription_history.normalize(payload), payload)

    def test_a_second_pass_changes_nothing(self):
        once = subscription_history.normalize({'input': [MESSAGE, ROUTER_COMPACTION]})
        self.assertEqual(once['input'], [MESSAGE, PROJECTED])
        self.assertIs(subscription_history.normalize(once), once)

    def test_reasoning_and_the_router_summary_change_in_one_pass(self):
        reasoning = {'type': 'reasoning', 'id': 'rs_1', 'summary': [],
                     'content': [{'type': 'reasoning_text', 'text': 'PRIVATE-CANARY'}]}
        payload = {'input': [reasoning, ROUTER_COMPACTION, MESSAGE]}
        before = copy.deepcopy(payload)
        self.assertEqual(subscription_history.normalize(payload)['input'],
                         [PROJECTED, MESSAGE])
        self.assertEqual(payload, before, 'client history is never edited')


class HandlerTests(unittest.TestCase):
    def setUp(self):
        isolated_home(self)
        self.server = start_server({'port': 0, 'token': 'test-token',
                                    'openai_models': ['gpt-6-astra']})
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.recorded = install_fake(self, lambda: FakeUpstream(200, b'{"output": []}', []))

    def send(self, body, headers=None):
        """POST one turn; return the single upstream body as JSON and its headers."""
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
        self.addCleanup(conn.close)
        conn.request('POST', '/test-token/responses', body,
                     {'Content-Type': 'application/json',
                      'Authorization': 'Bearer synthetic', **(headers or {})})
        response = conn.getresponse()
        response.read()
        self.assertEqual(response.status, 200)
        self.assertEqual(len(self.recorded), 1, 'exactly one upstream dispatch')
        sent, sent_headers = self.recorded[0][3], self.recorded[0][4]
        self.assertNotIn(b'ocx1:', sent)
        return json.loads(sent), sent_headers

    def test_the_first_attempt_is_readable_and_keeps_the_native_reply(self):
        sent, _ = self.send(BODY)
        self.assertEqual(sent['input'], [PROJECTED, CHILD_REPLY, MESSAGE])

    def test_a_compressed_turn_is_resent_as_identity_json(self):
        sent, headers = self.send(zstd.compress(BODY), {'Content-Encoding': 'zstd'})
        self.assertEqual(sent['input'], [PROJECTED, CHILD_REPLY, MESSAGE])
        self.assertNotIn('content-encoding', {key.lower() for key in headers})


if __name__ == '__main__':
    unittest.main()
