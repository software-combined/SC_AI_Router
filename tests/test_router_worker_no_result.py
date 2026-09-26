"""Router worker reporting for missing and unusable final results."""
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / 'plugins/scg-subagents/skills/router-workers/scripts/'
          'router_worker.py')
spec = importlib.util.spec_from_file_location('router_worker_no_result', SCRIPT)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class RouterWorkerNoResultTest(unittest.TestCase):
    def test_missing_result_keeps_the_workers_stderr_as_the_error(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(
                    worker, 'router',
                    return_value=('http://127.0.0.1:9/fake-token/', 'fake-token')), \
                    patch.object(worker, 'offered',
                                 return_value=[{'id': 'z-ai/glm-5.3-flash'}]), \
                    patch.object(worker, 'run_worker',
                                 return_value=('', 'transport failed: connection reset',
                                               None)), \
                    patch.object(worker, 'RUNS', Path(temporary) / 'runs'), \
                    patch.dict('os.environ',
                               {'CLAUDE_CODE_EXECPATH': '/fake/claude'}), \
                    contextlib.redirect_stdout(output):
                code = worker.main([
                    '--model', 'z-ai/glm-5.3-flash', '--effort', 'max',
                    '--task', 'brief', '--cwd', temporary])
        result = json.loads(output.getvalue())
        self.assertEqual(code, 1)
        self.assertFalse(result['ok'])
        self.assertEqual(result['error'], 'transport failed: connection reset')

    def test_result_event_without_an_answer_keeps_the_workers_stderr(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(
                    worker, 'router',
                    return_value=('http://127.0.0.1:9/fake-token/', 'fake-token')), \
                    patch.object(worker, 'offered',
                                 return_value=[{'id': 'z-ai/glm-5.3-flash'}]), \
                    patch.object(worker, 'run_worker',
                                 return_value=('{"type":"result","is_error":false}\n',
                                               'transport failed: connection reset',
                                               None)), \
                    patch.object(worker, 'RUNS', Path(temporary) / 'runs'), \
                    patch.dict('os.environ',
                               {'CLAUDE_CODE_EXECPATH': '/fake/claude'}), \
                    contextlib.redirect_stdout(output):
                code = worker.main([
                    '--model', 'z-ai/glm-5.3-flash', '--effort', 'max',
                    '--task', 'brief', '--cwd', temporary])
        result = json.loads(output.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(result['error'], 'transport failed: connection reset')


class RouterWorkerAnswerTest(unittest.TestCase):
    def test_successful_retry_wording_is_a_usable_answer(self):
        answer = ('The Read tool returned no output on the first attempt, but a '
                  'retry succeeded and the final result was verified.')
        self.assertIsNone(worker.answer_error(answer))

    def test_explicit_cross_tool_recovery_is_a_usable_answer(self):
        answer = ('I could not read the file with Read, so I used Glob and '
                  'verified the result.')
        self.assertIsNone(worker.answer_error(answer))

    def test_explicit_reread_recovery_is_a_usable_answer(self):
        answer = ('The Read tool returned no output, so I re-read the file and '
                  'verified the result.')
        self.assertIsNone(worker.answer_error(answer))

    def test_separate_recovery_sentence_is_a_usable_answer(self):
        answer = ('The Read tool returned no output. I used Glob and verified '
                  'the file.')
        self.assertIsNone(worker.answer_error(answer))

    def test_separate_expected_empty_sentence_is_a_usable_answer(self):
        answer = ('The Read tool returned no output. I verified the expected '
                  'empty state.')
        self.assertIsNone(worker.answer_error(answer))

    def test_expected_empty_result_wording_is_a_usable_answer(self):
        answer = ('The Read tool returned nothing unexpected; the file matches '
                  'the expected empty state.')
        self.assertIsNone(worker.answer_error(answer))

    def test_expected_empty_verification_is_a_usable_answer(self):
        answer = ('The Read tool returned no output for the intentionally empty '
                  'fixture, so I verified the expected empty state with the '
                  'passing suite.')
        self.assertIsNone(worker.answer_error(answer))

    def test_plain_empty_fixture_verification_is_a_usable_answer(self):
        for answer in (
                'The Read tool returned no output for an empty file. I verified '
                'the fixture.',
                'Fixed the parser and the full suite passes. The Read tool did '
                'not return any content from the intentionally empty fixture.'):
            with self.subTest(answer=answer):
                self.assertIsNone(worker.answer_error(answer))

    def test_returned_no_errors_is_a_usable_answer(self):
        self.assertIsNone(worker.answer_error(
            'The Read tool returned no errors and the file matched the fixture.'))

    def test_recognized_missing_result_wording_is_rejected(self):
        for answer in (
                'The file tool produced no data.',
                'The Read tool did not return any content.',
                'The Read tool failed to return content.',
                'The tool result was missing.',
                'The Read tool returned nothing.',
                'The Read tool returned nothing from the file.'):
            with self.subTest(answer=answer):
                self.assertEqual(worker.answer_error(answer),
                                 'tool_result_missing')

    def test_unverified_failure_wording_is_not_treated_as_recovery(self):
        answer = 'The Read tool returned no output and the result was not verified.'
        self.assertEqual(worker.answer_error(answer), 'tool_result_missing')

    def test_summary_rejects_explicit_tool_failure(self):
        summary = worker.summarise(json.dumps(
            {'type': 'result',
             'result': 'I could not complete the task because the Read tool '
                       'failed.',
             'is_error': False, 'num_turns': 2, 'usage': {}}))
        self.assertFalse(summary['finished'])
        self.assertEqual(summary['error'], 'tool_result_missing')

    def test_failure_wording_with_recovery_tokens_is_rejected(self):
        for answer in (
                'This version of the Read tool returned no output.',
                'The Read tool returned no output and was never verified.',
                'This version cannot verify the change because the Read tool '
                'returned no output.',
                'The Read tool returned no output; this version is unverified.',
                'Earlier the Read tool returned no output. This version isn\'t verified.',
                'Earlier the Read tool returned no output. This version can\'t be verified.'):
            with self.subTest(answer=answer):
                self.assertEqual(worker.answer_error(answer),
                                 'tool_result_missing')

    def test_historical_failure_with_later_denial_is_rejected(self):
        answer = ('Earlier the Read tool returned no output. The final suite '
                  'passes. The requested file result is not verified.')
        self.assertEqual(worker.answer_error(answer), 'tool_result_missing')

    def test_historical_failure_with_standalone_denial_tail_is_rejected(self):
        for answer in (
                'Earlier the Read tool returned no output. The final suite '
                'passes. Not verified.',
                'Earlier the Read tool returned no output. The final suite '
                'passes. Remains unavailable.'):
            with self.subTest(answer=answer):
                self.assertEqual(worker.answer_error(answer),
                                 'tool_result_missing')

    def test_failed_retry_with_later_success_is_rejected(self):
        for answer in (
                'Earlier the Read tool returned no output. A retry failed. '
                'The final result passed.',
                'Earlier the Read tool returned no output. The retry failed. '
                'The final suite passes.'):
            with self.subTest(answer=answer):
                self.assertEqual(worker.answer_error(answer),
                                 'tool_result_missing')

    def test_historical_failure_with_unavailable_result_is_rejected(self):
        for answer in (
                'Earlier the Read tool returned no output. The final suite '
                'passes. The requested file contents remain unavailable.',
                'Earlier the Read tool returned no output. The final suite '
                'passes and the requested file contents remain unavailable.'):
            with self.subTest(answer=answer):
                self.assertEqual(worker.answer_error(answer),
                                 'tool_result_missing')

    def test_unrelated_success_wording_does_not_excuse_a_tool_failure(self):
        for answer in (
                'The Read tool returned no output, so the current build works.',
                'The Read tool returned no output; the passing suite works.',
                'The Read tool returned no output, so the final result is verified.',
                'The Read tool returned no output; retry failed, but the final '
                'result passed.',
                'The Read tool returned no output, so I re-read the file and it '
                'returned no output.',
                'The Read tool returned no output, but the cache retry succeeded.',
                'The Read tool returned no output. The cache retry succeeded.',
                'Earlier the Read tool returned no output. This version returns '
                'the expected result. This version isn\'t verified.'):
            with self.subTest(answer=answer):
                self.assertEqual(worker.answer_error(answer),
                                 'tool_result_missing')

    def test_unrelated_recovery_does_not_excuse_the_requested_failure(self):
        answer = ('The Read tool returned no output. I re-read the unrelated '
                  'file and verified it.')
        self.assertEqual(worker.answer_error(answer), 'tool_result_missing')

    def test_historical_recovered_failures_are_usable_answers(self):
        for answer in (
                'Fixed the parser. In the earlier diagnostics, the Read tool '
                'returned no output. The final suite passes.',
                'The Read tool returned no output on an earlier attempt, but '
                'the final result is verified.',
                'Earlier the Read tool returned no output. I re-read the file '
                'and verified the expected result. The patch does not change '
                'public behavior.'):
            with self.subTest(answer=answer):
                self.assertIsNone(worker.answer_error(answer))

    def test_unrelated_negative_statement_does_not_undo_recovery(self):
        for answer in (
                'Earlier the Read tool returned no output. I re-read the file '
                'and verified the expected result. The patch does not change '
                'public behavior.',
                'Earlier the Read tool returned no output. I re-read the file '
                'and verified the expected result. Production deployment '
                'remains unverified.'):
            with self.subTest(answer=answer):
                summary = worker.summarise(json.dumps(
                    {'type': 'result', 'result': answer, 'is_error': False,
                     'num_turns': 2, 'usage': {}}))
                self.assertTrue(summary['finished'])
                self.assertIsNone(summary['error'])

    def test_retry_success_without_issues_is_a_usable_answer(self):
        answer = ('The Read tool returned no output on the first attempt, but a '
                  'retry succeeded without issues.')
        self.assertIsNone(worker.answer_error(answer))

    def test_verb_first_tool_failure_is_rejected(self):
        self.assertEqual(worker.answer_error('I could not read the file.'),
                         'tool_result_missing')

    def test_summary_rejects_collision_and_verb_first_failures(self):
        for answer in (
                'This version of the Read tool returned no output.',
                'The Read tool returned no output and was never verified.',
                'I could not read the file.',
                'The Read tool returned no output; retry failed, but the final '
                'result passed.'):
            with self.subTest(answer=answer):
                summary = worker.summarise(json.dumps(
                    {'type': 'result', 'result': answer, 'is_error': False,
                     'num_turns': 2, 'usage': {}}))
                self.assertFalse(summary['finished'])
                self.assertEqual(summary['error'], 'tool_result_missing')

    def test_summary_accepts_expected_empty_result_wording(self):
        summary = worker.summarise(json.dumps(
            {'type': 'result',
             'result': 'The Read tool returned nothing unexpected; the file '
                       'matches the expected empty state.',
             'is_error': False, 'num_turns': 2, 'usage': {}}))
        self.assertTrue(summary['finished'])
        self.assertIsNone(summary['error'])


if __name__ == '__main__':
    unittest.main()
