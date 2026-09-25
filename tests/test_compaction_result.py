import unittest

from ai_router.compaction_result import IncompleteSummary, extract_summary


def _output(text='summary'):
    return {'output': [{'type': 'message', 'content': [
        {'type': 'output_text', 'text': text}]}]}


class CompactionResultTests(unittest.TestCase):
    def test_legacy_payload_without_status_is_valid(self):
        self.assertEqual(extract_summary(200, _output()), 'summary')

    def test_truncated_output_has_a_typed_failure(self):
        payload = _output('partial')
        payload.update({'status': 'incomplete',
                        'incomplete_details': {'reason': 'max_output_tokens'}})
        with self.assertRaises(IncompleteSummary):
            extract_summary(200, payload)

    def test_truncated_message_item_status_is_a_typed_failure(self):
        payload = _output('partial')
        payload['status'] = 'incomplete'
        payload['incomplete_details'] = {'reason': 'max_output_tokens'}
        payload['output'][0]['status'] = 'incomplete'
        with self.assertRaises(IncompleteSummary):
            extract_summary(200, payload)

    def test_empty_truncated_output_is_retried(self):
        with self.assertRaises(IncompleteSummary):
            extract_summary(200, {
                'status': 'incomplete',
                'incomplete_details': {'reason': 'max_output_tokens'},
                'output': []})
        with self.assertRaisesRegex(ValueError, 'empty'):
            extract_summary(200, {'output': []})

    def test_failed_and_nonterminal_statuses_are_rejected_with_text(self):
        for status in ('failed', 'incomplete', 'in_progress'):
            with self.subTest(status=status):
                payload = _output('must not pass')
                payload['status'] = status
                with self.assertRaises(ValueError):
                    extract_summary(200, payload)
        payload = _output('must not pass')
        payload['status'] = 'completed'
        payload['output'][0]['status'] = 'incomplete'
        with self.assertRaises(ValueError):
            extract_summary(200, payload)

    def test_embedded_error_is_rejected_with_text(self):
        payload = _output('must not pass')
        payload['error'] = {'code': 'provider_error'}
        with self.assertRaises(ValueError):
            extract_summary(200, payload)

    def test_malformed_and_non_200_payloads_fail_closed(self):
        with self.assertRaisesRegex(ValueError, 'output list'):
            extract_summary(200, {'output': 'wrong'})
        with self.assertRaises(OSError):
            extract_summary(500, {'error': 'busy'})
        with self.assertRaises(OSError):
            extract_summary(500, {
                **_output('partial'),
                'incomplete_details': {'reason': 'max_output_tokens'}})
        with self.assertRaises(OSError):
            extract_summary(409, {
                **_output('partial'),
                'status': 'incomplete',
                'incomplete_details': {'reason': 'max_output_tokens'}})


if __name__ == '__main__':
    unittest.main()
