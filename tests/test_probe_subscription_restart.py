"""The live restart probe must cap every native upstream attempt."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from ai_router import provider_defs, transport
from tools.probe_subscription_restart import Budget, MAX_CALLS, MAX_INPUT, main


class RestartProbeTests(unittest.TestCase):
    def test_live_flag_is_required(self):
        with self.assertRaises(SystemExit) as exc:
            main([])
        self.assertEqual(exc.exception.code, 2)

    def test_retry_attempts_cannot_exceed_the_call_budget(self):
        send = Mock(return_value='sent')
        budget = Budget(send)
        conn = SimpleNamespace(timeout=30, sock=None)
        prepared = transport.Prepared('synthetic.invalid', '/responses', {},
            b'{"model": "gpt-synthetic"}', {}, provider_defs.OPENAI.id)
        for _ in range(MAX_CALLS):
            self.assertEqual(budget(conn, prepared, {}), 'sent')
        with self.assertRaises(ValueError):
            budget(conn, prepared, {})
        self.assertEqual(send.call_count, MAX_CALLS)

    def test_input_budget_is_checked_before_an_upstream_call(self):
        send = Mock()
        budget = Budget(send)
        prepared = transport.Prepared('synthetic.invalid', '/responses', {},
                                      b'x' * (MAX_INPUT + 1), {}, provider_defs.OPENAI.id)
        with self.assertRaises(ValueError):
            budget(SimpleNamespace(timeout=30, sock=None), prepared, {})
        send.assert_not_called()
        self.assertEqual(budget.calls, 0)

    def test_external_route_cannot_spend_the_native_probe_budget(self):
        send = Mock()
        budget = Budget(send)
        prepared = transport.Prepared('synthetic.invalid', '/responses', {}, b'{}',
                                      {}, provider_defs.DEFAULT_EXTERNAL)
        with self.assertRaises(ValueError):
            budget(SimpleNamespace(timeout=30, sock=None), prepared, {})
        send.assert_not_called()
        self.assertEqual(budget.calls, 0)


if __name__ == '__main__':
    unittest.main()
