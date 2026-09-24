"""A client may move its model-switch or context-reset marker (Plan 184 step 1).

ponytail: the canary that loads a captured client marker needs Plan 182's
capture fixture; until it lands, `tools/probe_history_switch.py` and
`tools/probe_context_recovery.py` check the installed client offline.
"""
import json
import unittest

from ai_router import context_recovery, providers
from ai_router.history_portability import portable_history
from ai_router.tool_adapter import SEARCH_NAME

SWITCH = '<model_switch>\nThe user was previously using a different model.\n</model_switch>'
WINDOW = ('<context_window>\n'
          'Current context window id: 22222222-2222-4222-8222-222222222222\n'
          'Previous context window id: 11111111-1111-4111-8111-111111111111\n'
          '</context_window>')
FOREIGN = {'type': 'reasoning', 'id': 'rs_foreign', 'summary': [], 'encrypted_content': 'FOREIGN',
           'content': [{'type': 'reasoning_text', 'text': 'earlier model thinking'}]}
NOTE = {'type': 'message', 'role': 'developer', 'content': [
    {'type': 'input_text', 'text': context_recovery.RECOVERY_GUIDANCE}]}


def variants(text):
    """The client's own shape (Codex 0.155) first, then each tolerated one."""
    block = {'type': 'input_text', 'text': text}
    other = {'type': 'input_text', 'text': 'Other client guidance.'}
    return {'content[0]': {'type': 'message', 'role': 'developer', 'content': [block]},
            'string': {'type': 'message', 'role': 'developer', 'content': text},
            'content[1]': {'type': 'message', 'role': 'developer', 'content': [other, block]},
            'system': {'type': 'message', 'role': 'system', 'content': [block]},
            'leading whitespace': {'type': 'message', 'role': 'developer', 'content': [
                {'type': 'input_text', 'text': '\n  ' + text}]}}


class SwitchMarkerTests(unittest.TestCase):
    def test_every_variant_is_a_marker(self):
        for name, marker in variants(SWITCH).items():
            with self.subTest(marker='switch', variant=name):
                self.assertEqual(portable_history([FOREIGN, marker], SEARCH_NAME, 'native'),
                                 [marker])
        for name, window in variants(WINDOW).items():
            with self.subTest(marker='window', variant=name):
                self.assertEqual(context_recovery.normalize({'input': [window]})['input'],
                                 [window, NOTE])

    def test_a_tag_later_in_a_text_is_not_a_marker(self):
        for text in (SWITCH, WINDOW):
            for name, quoted in variants('Quoted from a log: ' + text).items():
                with self.subTest(text=text[:15], variant=name):
                    items = [FOREIGN, quoted]
                    self.assertIs(portable_history(items, SEARCH_NAME, 'native'), items)
                    payload = {'input': items}
                    self.assertIs(context_recovery.normalize(payload), payload)

    def test_variants_replay_exactly_like_the_client_shape(self):
        def replay(marker):
            def thread():
                return [dict(FOREIGN, summary=[{'type': 'summary_text', 'text': 'earlier plan'}]),
                        marker,
                        {'type': 'reasoning', 'id': 'rs_native', 'summary': [],
                         'encrypted_content': 'NATIVE'},
                        {'type': 'agent_message', 'author': '/root/child', 'recipient': '/root',
                         'content': [{'type': 'input_text', 'text': 'done'}]},
                        {'type': 'message', 'role': 'user', 'content': [
                            {'type': 'input_text', 'text': 'next'}]}]
            payload = {'model': 'gpt-6-astra', 'input': thread()}
            prepared = providers.SubscriptionProvider().prepare(
                'gpt-6-astra', '/responses', payload, json.dumps(payload).encode(), {}, None)
            return (portable_history(thread(), SEARCH_NAME, 'native'),
                    json.loads(prepared.body)['input'])

        shapes = variants(SWITCH)
        client = shapes.pop('content[0]')
        history, sent = replay(client)
        # The boundary engaged on both paths: the foreign item is gone.
        self.assertNotIn('rs_foreign', json.dumps([history, sent]))
        for name, marker in shapes.items():
            with self.subTest(variant=name):
                self.assertEqual(replay(marker), (
                    [marker if item == client else item for item in history],
                    [marker if item == client else item for item in sent]))
