"""The shared vocabulary keeps each encrypted predicate's meaning (Plan 183)."""
import unittest

from ai_router import history_items as vocab


class EncryptedPredicateTests(unittest.TestCase):
    def test_an_empty_marker_marks_a_message_but_is_no_sidecar(self):
        # Containment counts the marker; a recoverable reply needs a payload.
        # Merging the two predicates would change one of those call sites.
        empty = {'type': 'encrypted_content', 'encrypted_content': ''}
        reply = {'type': 'agent_message', 'author': '/root/child', 'recipient': '/root',
                 'content': [{'type': 'input_text', 'text': 'done'}, empty]}
        self.assertTrue(vocab.has_encryption_marked_agent_item([reply]))
        self.assertFalse(vocab.holds_encrypted_payload(empty))
        self.assertIsNone(vocab.recoverable_agent_message(reply))
        sidecar = {'type': 'encrypted_content', 'encrypted_content': 'SYNTH-BLOB'}
        self.assertTrue(vocab.holds_encrypted_payload(sidecar))
        self.assertEqual(vocab.recoverable_agent_message({**reply, 'content': [
            reply['content'][0], sidecar]}), [reply['content'][0]])


if __name__ == '__main__':
    unittest.main()
