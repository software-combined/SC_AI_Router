"""Restart diagnostics use offline regressions and refuse native live execution."""
import unittest
from unittest import mock

from tools import probe_subscription_restart as probe


class RestartProbeTests(unittest.TestCase):
    def test_live_mode_refuses_before_launching_a_process_or_reading_a_home(self):
        with mock.patch.object(probe.subprocess, 'call') as launch, \
                mock.patch.object(probe.Path, 'home', side_effect=AssertionError('credential access')):
            with self.assertRaises(SystemExit) as exc:
                probe.main(['--live'])
            self.assertEqual(exc.exception.code, 2)
            launch.assert_not_called()

    def test_offline_command_dispatches_only_the_restart_regression_suite(self):
        with mock.patch.object(probe.subprocess, 'call', return_value=0) as launch:
            self.assertEqual(probe.main([]), 0)
        self.assertEqual(launch.call_args.args[0],
                         [probe.sys.executable, '-m', 'unittest', 'tests.test_subscription_restart'])


if __name__ == '__main__':
    unittest.main()
