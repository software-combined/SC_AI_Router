"""Plan 119 Step 1: unreadable encrypted briefs fail closed before dispatch.

A synthetic agent_message item with a routing label plus an encrypted block
must raise PreparationError before credentials or any outbound connection
are touched. Ordinary user messages keep preparing cleanly. No paid calls,
no real credentials, no user data.
"""
import json
import unittest

from ai_router import providers
from tests.harness import stub_credentials as _stub_credentials


def _external_responses():
    """OpenRouter Codes adapter; Plan 141 makes adapters per-provider."""
    from ai_router import provider_defs as _defs
    return providers.ExternalResponsesProvider(_defs.OPENROUTER)


MARKER = 'SYNTH-OPAQUE-066-4b1d'
OPAQUE_MARKER = 'SYNTH-OPAQUE-REPLY-a82f'


def _opaque_item(marker=MARKER):
    return {'type': 'agent_message', 'author': '/root',
            'content': [{'type': 'input_text', 'text': 'audit the network domain'},
                        {'type': 'encrypted_content', 'text': marker}]}


def _inbound_mixed():
    return {'type': 'agent_message', 'author': '/root/router_adversarial',
            'recipient': '/root',
            'content': [{'type': 'input_text', 'text': 'SYNTH-READABLE-REPLY'},
                        {'type': 'encrypted_content', 'encrypted_content': OPAQUE_MARKER}]}


def _prepare(items):
    provider = _external_responses()
    return provider.prepare('z-ai/glm-5.3', '/responses',
        {'model': 'z-ai/glm-5.3', 'input': items}, b'raw', {}, _stub_credentials())


class AgentContainmentTests(unittest.TestCase):
    def test_opaque_initial_brief_is_rejected_before_dispatch(self):
        with self.assertRaisesRegex(ValueError, 'encrypted agent'):
            _prepare([{'type': 'message', 'role': 'user', 'content': 'plain control'},
                      _opaque_item()])

    def test_opaque_follow_up_brief_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'encrypted agent'):
            _prepare([{'type': 'message', 'role': 'user', 'content': 'first turn'},
                      {'type': 'message', 'role': 'assistant', 'content': 'ack'},
                      {'type': 'message', 'role': 'user', 'content': 'follow up'},
                      _opaque_item('SYNTH-OPAQUE-066-followup')])

    def test_mixed_plaintext_and_opaque_brief_is_rejected(self):
        # The hidden block could carry a scope restriction the label omits.
        with self.assertRaisesRegex(ValueError, 'encrypted agent'):
            _prepare([_opaque_item()])

    def test_item_and_block_key_shapes_are_rejected(self):
        # The guard matches encrypted_content by key as well as block type;
        # each wire shape needs its own case or a broken disjunct slips past.
        shapes = [{'type': 'agent_message', 'author': '/root',
                   'encrypted_content': MARKER},
                  {'type': 'agent_message', 'author': '/root',
                   'content': [{'type': 'input_text', 'text': 'label'},
                               {'type': 'text', 'encrypted_content': MARKER}]}]
        for item in shapes:
            with self.subTest(shape=json.dumps(item)[:60]):
                with self.assertRaisesRegex(ValueError, 'encrypted agent'):
                    _prepare([item])

    def test_plaintext_only_requests_still_prepare(self):
        prepared = _prepare([{'type': 'message', 'role': 'user', 'content': 'plain control'}])
        items = json.loads(prepared.body)['input']
        self.assertTrue(any(i.get('content') == 'plain control' for i in items))

    def test_rejection_mentions_no_task_text_or_ciphertext(self):
        try:
            _prepare([_opaque_item()])
            self.fail('expected PreparationError')
        except ValueError as exc:
            self.assertNotIn(MARKER, str(exc))
            self.assertNotIn('network domain', str(exc))

    def test_inbound_mixed_reply_recovers_without_ciphertext(self):
        prepared = _prepare([_inbound_mixed()])
        body = json.dumps(json.loads(prepared.body))
        self.assertIn('SYNTH-READABLE-REPLY', body)
        self.assertIn('Encrypted content was withheld', body)
        self.assertNotIn(OPAQUE_MARKER, body)
        self.assertNotIn('encrypted_content', body)

    def test_self_peer_outbound_and_empty_inbound_stay_fail_closed(self):
        inbound = _inbound_mixed()
        shapes = [
            {**inbound, 'author': '/root'},
            {**inbound, 'author': '/root/sibling', 'recipient': '/root/other'},
            {**inbound, 'recipient': '/root/router_adversarial'},
            {**inbound, 'content': [inbound['content'][1]]},
            {**inbound, 'content': [inbound['content'][0],
                                    {'type': 'input_image', 'image_url': 'synthetic'}]},
            {**inbound, 'content': [{'type': 'input_text', 'text': '  '},
                                    inbound['content'][1]]},
            {**inbound, 'content': [inbound['content'][0],
                                    {'type': 'encrypted_content'}]},
            {**inbound, 'content': [inbound['content'][0],
                                    {'type': 'encrypted_content', 'text': 'only-label'}]},
        ]
        for item in shapes:
            with self.subTest(author=item.get('author'), recipient=item.get('recipient')):
                with self.assertRaises(ValueError):
                    _prepare([item])


class AgentSummaryTests(unittest.TestCase):
    def test_plaintext_agent_label_survives_summary_input(self):
        from ai_router import compaction as comp
        items = [{'type': 'agent_message', 'author': '/root',
                  'content': [{'type': 'input_text', 'text': 'review the router'}]}]
        summary = comp.transcript_for_summary(items)
        self.assertIn('review the router', summary)

    def test_opaque_agent_item_contributes_no_summary_text(self):
        from ai_router import compaction as comp
        summary = comp.transcript_for_summary([_opaque_item()])
        self.assertNotIn(MARKER, summary)
        self.assertNotIn('network domain', summary)

    def test_recoverable_reply_keeps_readable_text_out_of_the_sidecar(self):
        from ai_router import compaction as comp
        summary = comp.transcript_for_summary([_inbound_mixed()])
        self.assertIn('SYNTH-READABLE-REPLY', summary)
        self.assertIn('result may be incomplete', summary)
        self.assertNotIn(OPAQUE_MARKER, summary)


if __name__ == '__main__':
    unittest.main()
