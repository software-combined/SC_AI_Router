"""Offline decisions-client contracts; verified envelopes: docs/compatibility.md."""
import http.client
import io
import json
import unittest
import urllib.error
import urllib.request
from unittest import mock

from ai_router import decisions, provider_defs

KEY = 'sk-or-v1-test-key'


class _Reply:
    def __init__(self, body):
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode()

    def read(self, limit):
        return self._body[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _opener(reply, seen=None):
    """urlopen stand-in: records the request, then answers once."""
    def open_(request, timeout=None):
        if seen is not None:
            seen['url'] = request.full_url
            seen['auth'] = request.get_header('Authorization')
            seen['body'] = json.loads(request.data.decode())
            seen['timeout'] = timeout
        if isinstance(reply, Exception):
            raise reply
        return reply if hasattr(reply, '__enter__') else _Reply(reply)
    return open_


def _http_error(code, envelope):
    return urllib.error.HTTPError(
        'https://example.invalid', code, 'refused', {},
        io.BytesIO(json.dumps(envelope).encode()))


NOUL = {'drop_p1': {'type': 'noul', 'instructions': 'Can p1 go?'}}
CHOICE = {'next': decisions.question(
    'choice', 'Pick one.', {'keep': 'keep it', 'drop': 'drop it'})}


class QuestionTests(unittest.TestCase):
    def test_noul_and_choice_build_the_asked_shape(self):
        self.assertEqual(decisions.question('noul', '  Can p1 go?  '),
                         {'type': 'noul', 'instructions': 'Can p1 go?'})
        self.assertEqual(
            decisions.question('choice', 'Pick one.', {'a': 'first'}),
            {'type': 'choice', 'instructions': 'Pick one.',
             'criteria': {'a': 'first'}})

    def test_unverified_and_malformed_questions_are_refused(self):
        with self.assertRaises(decisions.DecisionError) as caught:
            decisions.question('score', 'Score it.')
        self.assertEqual(caught.exception.code, 'unsupported_question')
        for kind in ('noul ', '', None, 7, 'scorecard'):
            with self.subTest(kind=kind):
                with self.assertRaises(decisions.DecisionError) as caught:
                    decisions.question(kind, 'anything')
                self.assertEqual(caught.exception.code, 'bad_question')
        for args in (('noul', '   '), ('noul', None),
                     ('choice', 'Pick.', None), ('choice', 'Pick.', {}),
                     ('choice', 'Pick.', {'a': '  '}),
                     ('noul', 'Go', {'a': 'b'})):
            with self.subTest(args=args):
                with self.assertRaises(decisions.DecisionError) as caught:
                    decisions.question(*args)
                self.assertEqual(caught.exception.code, 'bad_question')


class AskTests(unittest.TestCase):
    def _ask(self, reply, seen=None, **over):
        call = {'state': {'goal': 'x'}, 'questions': NOUL, 'key': KEY}
        call.update(over)
        return decisions.ask(_urlopen=_opener(reply, seen), **call)

    def test_the_request_is_built_from_the_definition(self):
        seen = {}
        answers = self._ask(
            {'answers': {'drop_p1': {'type': 'noul', 'noul': 0.91}}}, seen)
        self.assertEqual(seen['url'],
                         'https://' + provider_defs.OPENROUTER.host
                         + provider_defs.OPENROUTER.decisions_path)
        self.assertEqual(seen['auth'], 'Bearer ' + KEY)
        self.assertNotIn(KEY, seen['url'])
        self.assertNotIn(KEY, json.dumps(seen['body']))
        self.assertEqual(seen['body']['model'],
                         provider_defs.OPENROUTER.decisions_model)
        self.assertEqual(provider_defs.OPENROUTER.decisions_model,
                         'typesafe/jev-1.13-20260917')
        self.assertEqual(seen['body']['questions'], NOUL)
        self.assertEqual(seen['timeout'], decisions.TIMEOUT_S)
        self.assertEqual(answers, {'drop_p1': {'type': 'noul', 'value': 0.91,
                                               'confidence': None,
                                               'probabilities': None}})

    def test_batched_answers_keep_separate_values_and_choice_evidence(self):
        answers = self._ask({
            'answers': {'next': {'type': 'choice', 'choice': 'keep',
                                 'probabilities': {'keep': 0.69, 'drop': 0.31},
                                 'confidence': 0.53},
                        'drop_p1': {'type': 'noul', 'noul': 0.10}}},
            questions=CHOICE | NOUL)
        self.assertEqual(answers['next'],
                         {'type': 'choice', 'value': 'keep', 'confidence': 0.53,
                          'probabilities': {'keep': 0.69, 'drop': 0.31}})
        self.assertEqual(answers['drop_p1']['value'], 0.10)

    def test_the_model_can_be_overridden(self):
        seen = {}
        self._ask({'answers': {'drop_p1': {'type': 'noul', 'noul': 0.5}}},
                  seen, model='typesafe/jev-typed-2')
        self.assertEqual(seen['body']['model'], 'typesafe/jev-typed-2')

    def test_a_provider_without_an_endpoint_is_refused(self):
        with self.assertRaises(decisions.DecisionError) as caught:
            self._ask({}, defn=provider_defs.OPENAI)
        self.assertEqual(caught.exception.code, 'no_endpoint')

    def test_a_missing_key_never_reaches_the_network(self):
        def boom(*args, **kwargs):
            self.fail('the endpoint must not be called without a key')

        for key in (None, '', 7, ' ', KEY + '\n', '\u2603'):
            with self.subTest(key=key):
                with self.assertRaises(decisions.DecisionError) as caught:
                    decisions.ask({'goal': 'x'}, NOUL, key=key, _urlopen=boom)
                self.assertEqual(caught.exception.code, 'missing_key')

    def test_empty_or_foreign_questions_are_refused(self):
        for questions in ({}, None, {'q': {'instructions': 'no type'}},
                          {'q': {'type': 'noul'}}, {'': NOUL['drop_p1']}):
            with self.subTest(questions=questions):
                with self.assertRaises(decisions.DecisionError) as caught:
                    decisions.ask({'goal': 'x'}, questions, key=KEY,
                                  _urlopen=_opener({}))
                self.assertEqual(caught.exception.code, 'bad_question')

    def test_an_oversized_request_is_refused_before_the_network(self):
        def boom(*args, **kwargs):
            self.fail('an oversized request must not be sent')

        with self.assertRaises(decisions.DecisionError) as caught:
            decisions.ask({'blob': 'x' * decisions.MAX_BODY}, NOUL, key=KEY,
                          _urlopen=boom)
        self.assertEqual(caught.exception.code, 'request_too_large')

    def test_an_oversized_answer_is_refused(self):
        with self.assertRaises(decisions.DecisionError) as caught:
            self._ask(b'x' * (decisions.MAX_RESPONSE + 2))
        self.assertEqual(caught.exception.code, 'response_too_large')

    def test_http_520_and_other_failures_are_safe_single_attempts(self):
        cases = ((401, 'unauthorized'), (403, 'unauthorized'), (400, 'refused'), (429, 'refused'),
                 (500, 'upstream_error'), (502, 'upstream_error'), (503, 'upstream_error'),
                 (504, 'upstream_error'), (520, 'upstream_error'), (599, 'upstream_error'))
        for status, code in cases:
            with self.subTest(status=status):
                error = _http_error(status, {'error': {
                    'message': f'HTTP {status}: error code: {status}\n', 'code': status}})
                error.read = mock.Mock(side_effect=AssertionError('must not read'))
                opener = mock.Mock(side_effect=error)
                with self.assertRaises(decisions.DecisionError) as caught:
                    decisions.ask('x', CHOICE, key=KEY, _urlopen=opener)
                self.assertEqual((caught.exception.code, caught.exception.status), (code, status))
                self.assertIn(code, decisions.ERROR_CODES)
                action = 'failed upstream' if status >= 500 else 'refused the request'
                self.assertEqual(str(caught.exception),
                                 f'the decisions endpoint {action} ({status})')
                opener.assert_called_once()
                error.read.assert_not_called()
                self.assertTrue(error.closed)

    def test_a_dead_endpoint_is_unreachable(self):
        for exc in (urllib.error.URLError('refused'), TimeoutError(),
                    http.client.IncompleteRead(b'partial')):
            opener = mock.Mock(side_effect=exc)
            with self.assertRaises(decisions.DecisionError) as caught:
                decisions.ask('x', NOUL, key=KEY, _urlopen=opener)
            self.assertEqual(caught.exception.code, 'unreachable')
            opener.assert_called_once()

    def test_malformed_answers_are_refused_with_their_own_codes(self):
        cases = (
            (b'not json', NOUL, 'malformed_response'),
            (b'\xff', NOUL, 'malformed_response'),
            (b'[' * 10000 + b']' * 10000, NOUL, 'malformed_response'),
            ({'answers': []}, NOUL, 'malformed_response'),
            ({'answers': {'drop_p1': {'type': 'choice', 'choice': 'keep'}}},
             NOUL, 'malformed_response'),
            ({'answers': {'drop_p1': {'type': 'noul', 'noul': 1.4}}},
             NOUL, 'malformed_response'),
            ({'answers': {'drop_p1': {'type': 'noul', 'noul': True}}},
             NOUL, 'malformed_response'),
            ({'answers': {'drop_p1': {'type': 'noul', 'noul': float('nan')}}},
             NOUL, 'malformed_response'),
            ({'answers': {'other': {'type': 'noul', 'noul': 0.5}}},
             NOUL, 'incomplete_answers'),
            ({'answers': {'drop_p1': {'type': 'noul', 'noul': 0.5},
                          'spare': {'type': 'noul', 'noul': 0.5}}},
             NOUL, 'unknown_answer'),
            ({'answers': {'next': {'type': 'choice', 'choice': 'maybe'}}},
             CHOICE, 'malformed_response'),
            ({'answers': {'next': {'type': 'choice', 'choice': 'keep',
                                   'confidence': 'high'}}},
             CHOICE, 'malformed_response'),
            ({'answers': {'next': {'type': 'choice', 'choice': 'keep',
                                   'probabilities': {'keep': 'lots'}}}},
             CHOICE, 'malformed_response'),
        )
        for payload, questions, code in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(decisions.DecisionError) as caught:
                    self._ask(payload, questions=questions)
                self.assertEqual(caught.exception.code, code)
                self.assertIn(caught.exception.code, decisions.ERROR_CODES)

    def test_no_refusal_ever_echoes_the_key(self):
        for reply in (_http_error(401, {'error': {'message': KEY}}),
                      _http_error(520, {'error': {'message': KEY}}),
                      urllib.error.URLError(KEY), b'not json',
                      {'answers': {'drop_p1': {'type': 'noul', 'noul': .5},
                                   KEY: {'type': 'noul', 'noul': .5}}}):
            with self.subTest(reply=type(reply).__name__):
                with self.assertRaises(decisions.DecisionError) as caught:
                    self._ask(reply)
                self.assertNotIn(KEY, str(caught.exception))

    def test_partial_or_malformed_choice_evidence_is_refused(self):
        good = {'type': 'choice', 'choice': 'keep', 'confidence': .83,
                'probabilities': {'keep': .89, 'drop': .11}}
        for patch in ({'choice': []}, {'choice': {}}, {'confidence': None},
                      {'choice': 'drop'},
                      {'probabilities': None}, {'probabilities': {}},
                      {'probabilities': {'keep': .89}},
                      {'probabilities': {'keep': .89, 'other': .11}},
                      {'confidence': float('nan')}, {'confidence': True}):
            with self.subTest(patch=patch):
                with self.assertRaises(decisions.DecisionError) as caught:
                    self._ask({'answers': {'next': good | patch}}, questions=CHOICE)
                self.assertEqual(caught.exception.code, 'malformed_response')
        answer = self._ask({'answers': {'next': good}}, questions=CHOICE)['next']
        self.assertEqual(answer['confidence'], .83)  # Not the choice probability.

    def test_invalid_request_options_never_reach_the_network(self):
        cyclic = []
        cyclic.append(cyclic)
        for patch in ({'state': None}, {'state': 1}, {'state': {'x': object()}},
                      {'state': {'x': float('nan')}}, {'state': cyclic},
                      {'timeout': None}, {'timeout': 0}, {'timeout': True},
                      {'timeout': float('inf')}, {'timeout': 6}, {'model': []}):
            opener = mock.Mock(side_effect=AssertionError('network reached'))
            with self.subTest(option=next(iter(patch))):
                with self.assertRaises(decisions.DecisionError) as caught:
                    decisions.ask(**({'state': 'x', 'questions': NOUL,
                                      'key': KEY, '_urlopen': opener} | patch))
                self.assertEqual(caught.exception.code, 'bad_request')
                opener.assert_not_called()

    def test_duplicate_json_members_are_not_silently_overwritten(self):
        with self.assertRaises(decisions.DecisionError) as caught:
            self._ask(b'{"answers":{"drop_p1":{"type":"noul","noul":0,"noul":1}}}')
        self.assertEqual(caught.exception.code, 'malformed_response')

    def test_default_transport_refuses_redirect_without_read_or_second_hop(self):
        def redirect(handler, request):
            return handler.parent.error('https', request, body, status, 'redirect',
                                        {'location': 'https://example.invalid/'})
        for status in (301, 302, 303, 307, 308):
            body = mock.Mock()
            with mock.patch.object(urllib.request.HTTPSHandler, 'https_open', redirect):
                with self.assertRaises(decisions.DecisionError) as caught:
                    decisions.ask('x', NOUL, key=KEY)
            self.assertEqual(caught.exception.code, 'refused')
            self.assertEqual(caught.exception.status, status)
            body.read.assert_not_called()
            body.close.assert_called_once()

    def test_adapter_has_only_the_opt_in_compaction_consumer(self):
        from tests.test_import_graph import _graph
        _, graph, _, _, _ = _graph()
        self.assertEqual(graph['ai_router.decisions'], {'ai_router.provider_defs'})
        self.assertEqual([name for name, targets in graph.items()
                          if 'ai_router.decisions' in targets], ['ai_router.jev_compaction'])


if __name__ == '__main__':
    unittest.main()
