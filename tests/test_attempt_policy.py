import unittest
from types import SimpleNamespace
from unittest import mock

from ai_router import (attempt_policy, errors, ingress, outcome, provider_defs,
                       providers, relay, router as router_mod, stream_relay,
                       subscription_fallback)
from ai_router.transport import Prepared
from tests import test_subscription_fallback as fallback_suite
from tests.fakes import FakeUpstream, install_fake

EXTERNAL = providers.ExternalResponsesProvider(provider_defs.OPENROUTER)
SUBSCRIPTION = providers.SubscriptionProvider()
PREPARED = Prepared('openrouter.ai', '/responses', {}, b'{}', set(), 'openrouter')


class LedgerTests(unittest.TestCase):
    def ledger(self, provider=EXTERNAL, protocol=provider_defs.RESPONSES):
        return attempt_policy.Ledger(provider, {'protocol': protocol, 'request_id': 'req-1',
                                                'path': '/responses'})

    def test_budgets_and_send_reasons(self):
        self.assertEqual((
            sum(attempt_policy.budget(EXTERNAL.defn, provider_defs.RESPONSES).values()),
            sum(attempt_policy.budget(SUBSCRIPTION.defn, provider_defs.RESPONSES).values()),
            attempt_policy.budget(EXTERNAL.defn, provider_defs.MESSAGES)),
            (3, 2, {'initial': 1}))
        ledger = self.ledger()
        with mock.patch.object(attempt_policy.http.client, 'HTTPSConnection', mock.MagicMock()), \
                mock.patch.object(attempt_policy.transport, 'post_with_phases',
                                  return_value=(FakeUpstream(200, b''), 0)):
            for reason in (attempt_policy.INITIAL, attempt_policy.REPAIR,
                           attempt_policy.STREAM_REPLAY):
                ledger.send(PREPARED, {}, reason)
            with self.assertRaises(RuntimeError):
                ledger.send(PREPARED, {}, attempt_policy.STREAM_REPLAY)
        self.assertEqual([a[2] for a in ledger.attempts],
                         ['initial', 'repair', 'stream_replay'])
        ledger.close()

    def test_transient_replay_and_client_abort(self):
        ledger = self.ledger()
        record = stream_relay.StreamRecord()
        record.outcome = outcome.Outcome(outcome.TRANSIENT, outcome.STREAM, outcome.UPSTREAM, 'overloaded')
        self.assertTrue(ledger.replay(record, b'{"tools": []}'))
        self.assertEqual(ledger.decisions, ['stream_replay:approved'])
        self.assertTrue(ledger.outcome.replayable)
        cancelled = attempt_policy.raised(BrokenPipeError(32, 'Broken pipe'), True, None, record, True)
        self.assertEqual((cancelled.category, cancelled.source),
                         (outcome.CANCELLED, outcome.CLIENT))

    def test_admission_failures_have_stable_outcomes(self):
        cases = (
            (errors.OversizeBusy(), outcome.RATE_LIMIT, 'OVERSIZE_BUSY'),
            (errors.InvalidSize('Decoded request is too large'),
             outcome.REFUSED, 'BODY_TOO_LARGE'),
            (errors.InvalidSize('Invalid request size'),
             outcome.REFUSED, 'INVALID_REQUEST_SIZE'),
        )
        for exc, category, code in cases:
            with self.subTest(code=code):
                settled = attempt_policy.raised(
                    exc, False, SimpleNamespace(status=400), None)
                self.assertEqual((settled.category, settled.phase,
                                  settled.source, settled.code,
                                  settled.side_effects),
                                 (category, outcome.STATUS, outcome.ROUTER,
                                  code, False))

    def test_response_seen_keeps_status_phase_after_body_read_failure(self):
        settled = attempt_policy.raised(
            ValueError('unreadable error body'), False, None, None,
            response_seen=True)
        self.assertEqual((settled.category, settled.phase, settled.source),
                         (outcome.UNKNOWN, outcome.STATUS, outcome.ROUTER))

    def test_post_replay_client_disconnect_supersedes_recorded_verdict(self):
        record = stream_relay.StreamRecord()
        record.stream_retry = 1
        record.outcome = outcome.Outcome(
            outcome.TRANSIENT, outcome.STREAM, outcome.UPSTREAM, 'overloaded')
        self.assertFalse(attempt_policy.keep_recorded_verdict(record, True))
        self.assertTrue(attempt_policy.keep_recorded_verdict(record, False))
        record.outcome = outcome.Outcome(
            outcome.SUCCESS, outcome.STREAM, outcome.UPSTREAM)
        self.assertTrue(attempt_policy.keep_recorded_verdict(record, False))

    def test_transition_budget_and_owned_cleanup(self):
        ledger = self.ledger(SUBSCRIPTION)
        ledger.settle(outcome.Outcome(outcome.RATE_LIMIT, outcome.STATUS, outcome.UPSTREAM))
        ledger.transition(EXTERNAL, provider_defs.RESPONSES)
        self.assertEqual((ledger.outcome, ledger.permits(attempt_policy.HELPER_FALLBACK)),
                         (None, False))
        created = []

        def connection(*args, **kwargs):
            conn = mock.MagicMock()
            created.append(conn)
            return conn

        with mock.patch.object(attempt_policy.http.client, 'HTTPSConnection', connection), \
                mock.patch.object(attempt_policy.transport, 'post_with_phases',
                                  side_effect=OSError('synthetic')):
            with self.assertRaises(OSError):
                ledger.send(PREPARED, {}, ledger.opening)
        ledger.close()
        self.assertTrue(created[0].close.called)

    def test_ledger_facts_cover_success_and_failure_contracts(self):
        cases = (
            (outcome.Outcome(outcome.SUCCESS, outcome.STREAM, outcome.UPSTREAM), True),
            (outcome.Outcome(outcome.UNKNOWN, outcome.STREAM, outcome.ROUTER), False),
        )
        for settled, terminal in cases:
            with self.subTest(category=settled.category):
                ledger = self.ledger()
                record = stream_relay.StreamRecord()
                record.forwarded_bytes = 7
                record.client_terminal = 'router' if terminal else None
                ledger.settle(settled)
                ledger.observe(record)
                facts = ledger.facts()
                self.assertEqual(
                    set(facts),
                    {'request_id', 'operation', 'protocol', 'route', 'sends',
                     'attempts', 'decisions', 'transitions', 'committed',
                     'terminal_source', 'outcome', 'outcome_phase',
                     'outcome_source', 'outcome_code', 'outcome_output',
                     'outcome_side_effects', 'router_version', 'attempt_evidence'})
                self.assertTrue(facts['committed'])
                self.assertEqual(facts['terminal_source'],
                                 record.client_terminal)
                self.assertEqual(facts['outcome'], settled.category)

    def test_transition_budget_is_explicit(self):
        ledger = self.ledger(SUBSCRIPTION)
        ledger.transition(EXTERNAL, provider_defs.RESPONSES)
        self.assertFalse(ledger.permits(attempt_policy.HELPER_FALLBACK))
        self.assertFalse(ledger.decide(attempt_policy.HELPER_FALLBACK))
        self.assertEqual(ledger.decisions[-1], 'helper_fallback:budget')


class HelperFallbackTests(unittest.TestCase):
    _server = fallback_suite.RefusedHelperTurnTests._server
    _turn = fallback_suite.RefusedHelperTurnTests._turn
    _refusal = fallback_suite.RefusedHelperTurnTests._refusal

    def facts(self, responder, enabled=True):
        install_fake(self, responder)
        server = self._server(openai_helper_fallback=enabled)
        with mock.patch.object(router_mod, 'log_event') as logged:
            response = self._turn(server, fallback_suite.HEADERS)
            response.read()
        ledger = [c.kwargs for c in logged.call_args_list
                  if c.args[0] == 'attempt_ledger'][0]
        return (response.status, [a[2] for a in ledger['attempts']],
                ledger['decisions'], ledger['transitions'])

    def test_one_route_transition_is_bounded(self):
        cases = ((self._refusal(), False, 503, ['initial'], ['helper_fallback:no_plan'], 0),
                 (self._refusal(), True, 200, ['initial', 'helper_fallback'], ['helper_fallback:approved'], 1),
                 (fallback_suite._sequence((429, b'{}', [])), True, 503, ['initial', 'helper_fallback'], ['helper_fallback:approved', 'helper_fallback:no_plan'], 1))
        for responder, enabled, status, sends, decisions, transitions in cases:
            with self.subTest(enabled=enabled):
                self.assertEqual(self.facts(responder, enabled),
                                 (status, sends, decisions, transitions))

    def test_failed_refusal_delivery_never_marks_committed(self):
        unavailable = SimpleNamespace(
            target=SimpleNamespace(slug='openai/gpt-6-luna'),
            prepared=mock.Mock(side_effect=LookupError('no key')))
        cases = (
            SimpleNamespace(provider='openai', fallback=None),
            SimpleNamespace(provider='openai', fallback=unavailable),
        )
        for prepared in cases:
            with self.subTest(fallback=prepared.fallback):
                ledger = attempt_policy.Ledger(
                    SUBSCRIPTION,
                    {'protocol': provider_defs.RESPONSES, 'request_id': 'req-1',
                     'path': '/responses', 'model': 'gpt-5.6-luna'})
                handler = SimpleNamespace(error=mock.Mock(return_value=False))
                self.assertIsNone(subscription_fallback.refused(
                    handler, prepared, '2', {'model': 'gpt-5.6-luna'}, 0.0,
                    ledger=ledger))
                facts = ledger.facts()
                self.assertFalse(facts['committed'])
                self.assertIsNone(facts['terminal_source'])

    def test_error_writer_must_report_delivery(self):
        handler = SimpleNamespace(error=lambda *args, **kwargs: None)
        ledger = attempt_policy.Ledger(
            EXTERNAL, {'protocol': provider_defs.RESPONSES})
        self.assertIsNone(relay._error(handler, ledger, ValueError()))
        self.assertFalse(ledger.committed)
        handler = SimpleNamespace(error=lambda *args, **kwargs: False,
                                  response_committed=True)
        ledger = attempt_policy.Ledger(
            EXTERNAL, {'protocol': provider_defs.RESPONSES})
        self.assertFalse(relay._error(handler, ledger, ValueError()))
        self.assertTrue(ledger.committed)
        ledger = attempt_policy.Ledger(
            EXTERNAL, {'protocol': provider_defs.RESPONSES})
        handler = SimpleNamespace(error=lambda *args, **kwargs: None)
        subscription_fallback._answer_refusal(handler, ledger, object(), None)
        self.assertFalse(ledger.committed)


class DeliveryExceptionTests(unittest.TestCase):
    class _Writer:
        def __init__(self, exc):
            self.exc = exc

        def write(self, _):
            raise self.exc

        def flush(self):
            pass

    def _handler(self, exc):
        handler = SimpleNamespace(
            wfile=self._Writer(exc), close_connection=False,
            response_committed=False,
            send_response=lambda *args: None,
            send_header=lambda *args: None,
            end_headers=lambda: None)
        handler.send_json = (
            lambda status, obj, headers=None:
            ingress.send_json(handler, status, obj, headers))
        handler.error = (
            lambda err, retry_after=None:
            handler.send_json(err.status, err.body()))
        return handler

    def _ledger(self, category=outcome.REFUSED):
        ledger = attempt_policy.Ledger(
            EXTERNAL, {'protocol': provider_defs.RESPONSES})
        ledger.settle(outcome.Outcome(category, outcome.STATUS,
                                      outcome.UPSTREAM, 'provider_verdict'))
        return ledger

    def test_real_socket_abort_settles_client_cancellation(self):
        for exc in (BrokenPipeError(32, 'Broken pipe'),
                    ConnectionResetError(54, 'Connection reset by peer')):
            for commit in (relay._error, subscription_fallback._answer_refusal):
                with self.subTest(error=type(exc).__name__, commit=commit.__name__):
                    ledger = self._ledger()
                    handler = self._handler(exc)
                    if commit is relay._error:
                        commit(handler, ledger, errors.upstream_failed())
                    else:
                        commit(handler, ledger, errors.upstream_rate_limited(), None)
                    self.assertEqual((ledger.outcome.category, ledger.outcome.source),
                                     (outcome.CANCELLED, outcome.CLIENT))
                    self.assertTrue(ledger.committed)

    def test_contained_value_error_keeps_the_provider_outcome(self):
        for commit in (relay._error, subscription_fallback._answer_refusal):
            with self.subTest(commit=commit.__name__):
                ledger = self._ledger()
                handler = self._handler(ValueError('I/O operation on closed file'))
                if commit is relay._error:
                    commit(handler, ledger, errors.upstream_failed())
                else:
                    commit(handler, ledger, errors.upstream_rate_limited(), None)
                self.assertEqual((ledger.outcome.category, ledger.outcome.source,
                                  ledger.outcome.code),
                                 (outcome.REFUSED, outcome.UPSTREAM,
                                  'provider_verdict'))
                self.assertTrue(ledger.committed)
