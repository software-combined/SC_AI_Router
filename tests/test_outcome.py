"""Shared terminal outcomes for HTTP errors and Responses stream failures."""
import dataclasses
import io
import json
import unittest
from types import SimpleNamespace

from ai_router import outcome, provider_defs, sse, stream_errors, upstream


def settled(event):
    frame = sse.frame(json.dumps(event).encode())
    return list(stream_errors.events([frame], {}))[-1].outcome


def wire_frames(body):
    return [json.loads(data) for _, data in sse.blocks(io.BytesIO(body))]


class StreamOutcomeTests(unittest.TestCase):
    def test_terminal_categories_are_distinct(self):
        cases = (
            ({'type': 'response.incomplete', 'response': {
                'incomplete_details': {'reason': 'max_output_tokens'}}},
             outcome.INCOMPLETE),
            ({'type': 'response.failed', 'response': {
                'error': {'code': 'bad_schema'}}}, outcome.UNKNOWN),
            ({'type': 'response.failed', 'response': {
                'error': {'code': 'overloaded'}}}, outcome.TRANSIENT),
            ({'type': 'response.failed', 'response': {
                'error': {'code': 'insufficient_quota'}}}, outcome.QUOTA),
            ({'type': 'response.failed', 'response': {
                'error': {'code': 'rate_limit_exceeded'}}}, outcome.RATE_LIMIT),
            ({'type': 'response.failed', 'response': {
                'error': {'code': 'invalid_api_key'}}}, outcome.AUTH),
            ({'type': 'response.failed', 'response': {
                'error': {'code': 'context_length_exceeded'}}},
             outcome.CONTEXT_OVERFLOW),
            ({'type': 'response.failed', 'response': {
                'error_type': 'invalid_request'}}, outcome.REFUSED),
            ({'type': 'response.failed', 'response': {
                'error_type': 'refusal'}}, outcome.REFUSED),
            ({'type': 'response.failed', 'response': {
                'error_type': 'moderation'}}, outcome.REFUSED),
            ({'type': 'response.failed', 'response': {
                'error_type': 'server_error',
                'error': {'code': 'invalid_prompt'}}}, outcome.REFUSED),
            ({'type': 'response.failed', 'response': {
                'error': {'code': 'billing_hard_limit_reached'}}},
             outcome.QUOTA),
            ({'type': 'response.failed', 'response': {
                'error': {'code': 'credit_balance_too_low'}}}, outcome.QUOTA),
        )
        for event, category in cases:
            with self.subTest(category=category):
                self.assertEqual(settled(event).category, category)
    def test_completed_success_requires_a_completed_response(self):
        cases = (
            ({'type': 'response.completed', 'response': {
                'status': 'completed', 'output': []}}, outcome.SUCCESS),
            ({'type': 'response.completed', 'response': {
                'status': 'completed'}}, outcome.SUCCESS),
            ({'type': 'response.completed', 'response': {
                'status': 'completed', 'output': None}}, outcome.SUCCESS),
            ({'type': 'response.completed', 'error': {'code': 'bad_schema'},
              'response': {'status': 'completed'}}, outcome.UNKNOWN),
            ({'type': 'response.completed', 'response': {
                'status': 'failed', 'error': {'code': 'bad_schema'}}},
             outcome.UNKNOWN),
            ({'type': 'response.completed'}, outcome.UNKNOWN),
            ({'type': 'response.completed', 'response': {}}, outcome.UNKNOWN),
            ({'type': 'response.completed', 'response': {
                'status': 'in_progress'}}, outcome.UNKNOWN),
            ({'type': 'response.completed', 'response': {
                'status': 'completed', 'output': 'not-a-list'}}, outcome.UNKNOWN),
            ({'type': 'response.completed', 'response': {
                'status': []}}, outcome.UNKNOWN),
        )
        for event, category in cases:
            with self.subTest(event=event):
                self.assertEqual(settled(event).category, category)
    def test_terminal_outcome_keeps_prior_output_and_bounded_cause(self):
        frame = sse.frame(json.dumps({
            'type': 'response.output_text.delta', 'delta': 'partial'}).encode())
        terminal = sse.frame(json.dumps({
            'type': 'response.failed', 'response': {
                'error_type': 'server_error'}}).encode())
        event = list(stream_errors.events([frame, terminal], {}))[-1]
        self.assertEqual(event.outcome.category, outcome.TRANSIENT)
        self.assertEqual(event.outcome.code, 'server_error')
        self.assertTrue(event.outcome.output)

    def test_specific_causes_win_over_generic_transient_causes(self):
        cases = (
            ({'type': 'response.failed', 'response': {
                'error_type': 'server_error',
                'error': {'code': 'billing_hard_limit_reached'}}},
             outcome.QUOTA),
            ({'type': 'response.failed', 'response': {
                'error': {'code': 'server_error',
                          'metadata': {'provider_code': 'invalid_prompt'}}}},
             outcome.REFUSED),
            ({'type': 'response.failed', 'response': {
                'error': {'type': 'server_error'}}}, outcome.TRANSIENT),
        )
        for event, category in cases:
            with self.subTest(event=event):
                self.assertEqual(settled(event).category, category)
    def test_nonempty_terminal_output_is_retained_for_replay_gate(self):
        result = settled({'type': 'error', 'error': {'code': 'overloaded'},
                          'output': [{'type': 'message'}]})
        self.assertTrue(result.output)
    def test_context_causes_include_type_nested_and_provider_codes(self):
        cases = (
            {'type': 'response.failed', 'response': {
                'error': {'type': 'context_length_exceeded'}}},
            {'type': 'response.failed', 'response': {
                'error': {'metadata': {'provider_code': 'context_length_exceeded'}}}},
        )
        for event in cases:
            with self.subTest(event=event):
                self.assertEqual(settled(event).category, outcome.CONTEXT_OVERFLOW)
        self.assertEqual(upstream.outcome_of(
            400, b'{"error":{"type":"context_length_exceeded"}}').category,
            outcome.CONTEXT_OVERFLOW)
    def test_outcome_code_names_the_cause_that_won(self):
        result = settled({'type': 'response.failed', 'response': {
            'error': {'code': 'bad_schema',
                      'metadata': {'provider_code': 'server_error'}}}})
        self.assertEqual((result.category, result.code),
                         (outcome.TRANSIENT, 'server_error'))
    def test_context_cause_wins_on_stream_and_http(self):
        payload = {'error': {'code': 'server_error',
                             'metadata': {'provider_code': 'context_length_exceeded'}}}
        stream = settled({'type': 'response.failed', 'response': payload})
        http = upstream.outcome_of(429, json.dumps(payload).encode())
        self.assertEqual((stream.category, stream.code),
                         (outcome.CONTEXT_OVERFLOW, 'context_length_exceeded'))
        self.assertEqual((http.category, http.code),
                         (outcome.CONTEXT_OVERFLOW, 'context_length_exceeded'))
    def test_unknown_prose_is_not_relabelled_as_refusal(self):
        event = {'type': 'response.failed', 'response': {
            'error': {'code': 'bad_schema', 'message': 'private'}}}
        raw = sse.frame(json.dumps(event).encode())
        metrics = {}
        out = b''.join(stream_errors.normalize([raw], metrics))
        self.assertEqual((out, settled(event).category, metrics['failure_class']),
                         (raw, outcome.UNKNOWN, 'unknown'))
    def test_rewritten_terminal_retains_provider_output(self):
        event = {'type': 'response.failed', 'response': {
            'error': {'code': 'invalid_prompt'},
            'output': [{'type': 'message'}]}}
        result = settled(event)
        out = b''.join(stream_errors.normalize([sse.frame(json.dumps(event).encode())], {}))
        self.assertEqual((result.output, wire_frames(out)[0]['response']['output']),
                         (True, [{'type': 'message'}]))
    def test_completed_outcome_reports_output_items(self):
        event = settled({'type': 'response.completed', 'response': {
            'status': 'completed', 'output': [{'type': 'message'}]}})
        self.assertTrue(event.output)
    def test_malformed_completed_is_a_failure_on_the_wire(self):
        raw = sse.frame(json.dumps({
            'type': 'response.completed', 'response': {}}).encode())
        out = b''.join(stream_errors.normalize([raw], {}))
        events = wire_frames(out)
        self.assertEqual([event['type'] for event in events], ['response.failed'])
        self.assertEqual(events[0]['response']['error']['code'], 'UPSTREAM_FAILED')
    def test_terminal_boundary_drops_later_verdicts_and_output(self):
        completed = sse.frame(json.dumps({
            'type': 'response.completed', 'response': {
                'status': 'completed', 'output': []}}).encode())
        failed = sse.frame(json.dumps({
            'type': 'response.failed', 'response': {
                'error': {'code': 'overloaded'}}}).encode())
        answer = sse.frame(json.dumps({
            'type': 'response.output_text.delta', 'delta': 'late'}).encode())
        out = b''.join(stream_errors.normalize([completed, failed], {}))
        self.assertEqual([event['type'] for event in wire_frames(out)], ['response.completed'])
        out = b''.join(stream_errors.normalize([failed, answer], {}))
        self.assertEqual([event['type'] for event in wire_frames(out)], ['response.failed'])
    def test_top_level_stream_type_matches_http_classification(self):
        payload = {'type': 'server_error', 'error': {'message': 'provider failed'}}
        stream = settled({'type': 'response.failed', 'response': payload})
        http = upstream.outcome_of(500, json.dumps(payload).encode())
        self.assertEqual((stream.category, stream.code),
                         (outcome.TRANSIENT, 'server_error'))
        self.assertEqual((http.category, http.code),
                         (outcome.TRANSIENT, 'server_error'))
    def test_unknown_is_a_failure_and_not_replayable(self):
        unknown = settled({'type': 'response.failed', 'response': {
            'error': {'code': 'bad_schema'}}})
        self.assertTrue(unknown.reported_failure)
        self.assertFalse(unknown.replayable)
    def test_http_status_categories(self):
        cases = ((429, b'{}', outcome.RATE_LIMIT), (401, b'{}', outcome.AUTH),
                 (402, b'{}', outcome.QUOTA), (503, b'{}', outcome.TRANSIENT),
                 (400, b'{"error":{"code":"server_error","message":"x"}}',
                  outcome.TRANSIENT),
                 (400, b'{"error":{"code":"billing_hard_limit_reached"}}',
                  outcome.QUOTA),
                 (418, b'<html>', outcome.UNKNOWN))
        for status, raw, category in cases:
            with self.subTest(status=status):
                self.assertEqual(upstream.outcome_of(status, raw).category, category)
    def test_http_outcome_keeps_nested_bounded_code(self):
        body = json.dumps({'error': {'message': 'Provider returned error',
                                     'metadata': {'raw': json.dumps({
                                         'error': {'code': 'inner_code'}})}}}).encode()
        result = upstream.outcome_of(400, body)
        self.assertEqual((result.category, result.code),
                         (outcome.REFUSED, 'inner_code'))
    def test_http_context_overrides_rate_limit_and_skips_retry_after(self):
        body = json.dumps({'error': {
            'code': 'context_length_exceeded'}}).encode()
        response = SimpleNamespace(status=429, getheader=lambda *args: '2')
        self.assertEqual(upstream.outcome_of(429, body).category, outcome.CONTEXT_OVERFLOW)
        self.assertIsNone(upstream.upstream_retry_after(response,
            SimpleNamespace(provider='openrouter'), {'path': '/responses'}, body))
        results = [upstream.describe_failure(None, {'status': status, 'body': body},
                                             {'model': 'm'}) for status in (429, 500)]
        self.assertEqual([(result[0], result[2]) for result in results],
                         [(409, 'context_length_exceeded')] * 2)

    def test_responses_deterministic_refusal_is_not_mapped_to_503(self):
        status, message, code = upstream.describe_failure(
            None, {'status': 500, 'body': b'{"error":{"code":"invalid_prompt"}}'},
            {'model': 'm', 'protocol': provider_defs.RESPONSES})
        self.assertEqual((status, code), (400, 'invalid_prompt'))
        self.assertIn('Do not retry it unchanged', message)

    def test_provider_codes_and_deterministic_http_status_causes_match(self):
        stream_cases = (
            ({'type': 'response.failed', 'response': {
                'error': {'metadata': {'provider_code': 'server_error'}}}},
             outcome.TRANSIENT),
            ({'type': 'response.failed', 'response': {
                'error': {'metadata': {'provider_code': 'billing_hard_limit_reached'}}}},
             outcome.QUOTA),
        )
        for event, category in stream_cases:
            with self.subTest(event=event):
                self.assertEqual(settled(event).category, category)
        for status, raw, category in (
                (500, b'{"error":{"code":"invalid_prompt"}}', outcome.REFUSED),
                (500, b'{"error":{"code":"billing_hard_limit_reached"}}',
                 outcome.QUOTA),
                (500, b'{"error":{"code":"bad_schema","metadata":{"raw":"{\\"error\\":{\\"code\\":\\"billing_hard_limit_reached\\"}}"}}}',
                 outcome.QUOTA),
                (408, b'{"error":{"code":"invalid_prompt"}}', outcome.REFUSED),
                (500, b'{"error":{"message":"invalid_client_tool_schema"}}',
                 outcome.REFUSED),
                (500, b'{"error_type":"invalid_request","error":{}}',
                 outcome.REFUSED)):
            with self.subTest(status=status):
                self.assertEqual(upstream.outcome_of(status, raw).category, category)

    def test_nested_invalid_prompt_is_rewritten_like_outer_invalid_prompt(self):
        metrics = {}
        wire = sse.frame(json.dumps({'type': 'response.failed', 'response': {
            'error': {'code': 'server_error', 'metadata': {'raw': json.dumps({
                'error': {'code': 'invalid_prompt'}})}}}}).encode())
        out = b''.join(stream_errors.normalize([wire], metrics))
        self.assertIn(b'invalid_prompt', out)
        self.assertEqual(metrics['code'], 'UPSTREAM_INVALID_PROMPT')

    def test_429_outcome_precedence_is_shared_and_retry_policy_is_legacy(self):
        quota = '{"error":{"code":"billing_hard_limit_reached"}}'
        auth = '{"error":{"code":"unauthorized"}}'
        cases = (
            (json.dumps({'error': {'code': 'unauthorized',
                                   'metadata': {'raw': quota}}}).encode(),
             outcome.QUOTA),
            (json.dumps({'error': {'code': 'billing_hard_limit_reached',
                                   'metadata': {'raw': auth}}}).encode(),
             outcome.QUOTA),
            (json.dumps({'error': {'code': 'rate_limit_exceeded',
                                   'metadata': {'raw': auth}}}).encode(),
             outcome.AUTH),
            (b'{"error":{"code":"invalid_prompt"}}', outcome.REFUSED),
        )
        for raw, category in cases:
            with self.subTest(raw=raw):
                self.assertEqual(upstream.outcome_of(429, raw).category, category)
        self.assertEqual(upstream.classify_429(auth.encode()), 'transient')
        mixed = json.dumps({'error': {
            'code': 'invalid_api_key',
            'type': 'billing_hard_limit_reached'}}).encode()
        self.assertEqual(upstream.classify_429(mixed), 'auth')

    def test_record_is_immutable_and_bounded(self):
        record = outcome.Outcome(outcome.TRANSIENT, outcome.STREAM, outcome.UPSTREAM)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            record.category = outcome.SUCCESS
        with self.assertRaises(ValueError):
            outcome.Outcome(outcome.UNKNOWN, outcome.STREAM, outcome.UPSTREAM,
                            code='x' * 65)


if __name__ == '__main__':
    unittest.main()
