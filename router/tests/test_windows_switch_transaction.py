"""The Windows switch owns consent, verified shutdown, configuration and reopen."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.test_codex_desktop_switch import switcher
from tests.test_windows_codex import API, row


class WindowsSwitchTransactionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.home, self.config, self.app = self.root / 'router', self.root / 'config.toml', self.root / 'Store_A'
        self.home.mkdir()
        self.cli = self.app / 'app/resources/codex.exe'
        self.cli.parent.mkdir(parents=True)
        self.cli.write_bytes(b'MZ fixture')
        (self.app / 'app/ChatGPT.exe').write_bytes(b'MZ fixture')
        (self.app / 'AppxManifest.xml').write_text('<Package><Applications><Application '
            'Id="App" Executable="app/ChatGPT.exe"/></Applications></Package>')
        state = dict(port=4321, token='fixture', clients='codex', openai_mode='subscription')
        (self.home / 'mixed-router-state.json').write_text(json.dumps(state))
        block = switcher._blocks.build(self.home, state, 'subscription', False, 'default')
        switcher._blocks._codex.write_receipt(self.home, self.config, block, None, 'subscription', '')
        self.config.write_text(block + '\n# unrelated setting\n')
        self.before = self.config.read_bytes()
        self.api = API(self.app)
        self.api.rows = {10: row(10, 1, str(self.app / 'app/ChatGPT.exe')),
                         11: row(11, 10, '/runtime/node.exe')}
        self.ops = switcher._platform
        self.enterContext(mock.patch.object(switcher.sys, 'platform', 'win32'))
        self.cohort = SimpleNamespace(ready=mock.Mock(return_value=True))
        self.enterContext(mock.patch.object(switcher, '_installation', self.cohort, create=True))
        self.health = self.enterContext(mock.patch.object(switcher._service, 'health', return_value={'version': '1.3.26'}))
        self.enterContext(mock.patch.object(switcher._service, 'current_version', return_value='1.3.26'))
        self.enterContext(mock.patch.object(self.ops._windows_codex, 'bindings', return_value=self.api))
        self.enterContext(mock.patch.object(switcher.time, 'monotonic', side_effect=lambda: self.api.now))
        self.enterContext(mock.patch.object(switcher.time, 'sleep', side_effect=self.api.sleep))
        self.confirm = self.enterContext(mock.patch.object(self.ops, 'confirm', return_value=True))
        self.run = mock.Mock(side_effect=self.version)
        self.proofs = []

    def version(self, argv, **kwargs):
        self.assertEqual(argv, [str(self.cli), '--version'])
        self.assertEqual(kwargs['creationflags'], 0x08000000)
        return SimpleNamespace(returncode=0, stdout='codex-cli 0.163.0-alpha.11', stderr='')

    def prove(self, root):
        self.assertEqual(self.api.rows, {})
        self.proofs.append(root)
        return True

    def switch(self, **kwargs):
        return switcher.switch(self.home, run=self.run, ready=lambda _: True,
                               prove=kwargs.pop('prove', self.prove), **kwargs)

    def unchanged(self):
        self.assertEqual(self.config.read_bytes(), self.before)
        self.assertEqual(switcher._blocks.current(self.home), 'default')

    def pending(self):
        previous = switcher._blocks.rollback_entry(switcher._receipts.codex_attachment(self.home))
        switcher._blocks.switch(self.home, 'switched')
        switcher._atomic.replace_json(self.home / switcher.MARKER, dict(to='switched', entry=previous))

    def partial_reopen(self, *, pending=False, refuse_shutdown=False):
        if pending:
            self.pending()
        activate, stop = self.api.activate, self.ops.request_stop
        calls, loaded, restoring = [], [], []
        restore = switcher._blocks.restore
        def open_window(app):
            calls.append(app)
            if 10 not in self.api.rows:
                activate(app)
                loaded.append(switcher._blocks.current(self.home))
            self.api.visible = len(calls) > 1
        def restore_settings(*args):
            restoring.append(bool(self.api.rows))
            return restore(*args)
        stops = []
        def close(*args, **kwargs):
            stops.append(True)
            return False if refuse_shutdown and len(stops) > 1 else stop(*args, **kwargs)
        with mock.patch.object(self.api, 'activate', side_effect=open_window), \
                mock.patch.object(self.ops, 'request_stop', side_effect=close), \
                mock.patch.object(switcher._blocks, 'restore', side_effect=restore_settings):
            with self.assertRaises(switcher.SwitchError):
                self.switch()
        return loaded, restoring

    def test_partially_reopened_app_exits_before_rollback_then_loads_original_connection(self):
        loaded, restoring = self.partial_reopen()
        self.unchanged()
        self.assertEqual(restoring, [False])
        self.assertEqual(loaded, ['switched', 'default'])

    def test_failed_proof_restores_original_crlf_bytes(self):
        self.before = self.before.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
        self.config.write_bytes(self.before)
        with self.assertRaises(switcher.SwitchError):
            self.switch(prove=lambda _: False)
        self.unchanged()

    def test_pending_partial_reopen_also_stops_before_restoring(self):
        loaded, restoring = self.partial_reopen(pending=True)
        self.unchanged()
        self.assertEqual(restoring, [False])
        self.assertEqual(loaded, ['switched', 'default'])

    def test_unverified_rollback_shutdown_keeps_the_marker_and_does_not_rewrite(self):
        _, restoring = self.partial_reopen(refuse_shutdown=True)
        self.assertEqual(restoring, [])
        self.assertEqual(switcher._blocks.current(self.home), 'switched')
        self.assertTrue((self.home / switcher.MARKER).exists())

    def test_pending_recovery_honors_matching_and_opposing_explicit_destinations(self):
        for destination in ('switched', 'switched_back'):
            self.pending()
            self.assertEqual(self.switch(target=destination), destination)
            self.assertEqual(switcher._blocks.current(self.home), destination)
            self.assertFalse((self.home / switcher.MARKER).exists())

    def test_consent_ends_surviving_tray_workers_and_switches_both_directions(self):
        self.assertEqual(self.switch(), 'switched')
        self.assertEqual(set(self.api.ended), {10, 11})
        self.assertTrue(self.api.visible)
        prompt = self.confirm.call_args.args[0]
        self.assertIn('fully close', prompt)
        self.assertIn('Running tasks will stop', prompt)
        self.assertEqual(len(self.proofs), 1)
        self.cli.unlink()  # Returning to the subscription never requires its bundled command.
        self.assertEqual(self.switch(), 'switched_back')
        self.assertEqual(len(self.proofs), 1)
        self.assertTrue(self.api.visible)
        facts = json.loads((self.home / 'logs/codex-switch.log').read_text().splitlines()[0])
        self.assertGreater(facts['scan_count'], 1)
        self.assertLess(facts['quit_ms'], 20000)
        self.assertTrue(facts['proof_ok'])
        self.assertNotIn(str(self.root), json.dumps(facts))

    def test_cancel_never_closes_or_terminates_the_app(self):
        self.confirm.return_value = False
        self.assertIsNone(self.switch())
        self.assertEqual((self.api.closed, self.api.ended), ([], []))
        self.unchanged()

    def test_mixed_components_refuse_before_app_lookup_or_pending_recovery(self):
        self.pending()
        before = self.config.read_bytes(), (self.home / switcher.MARKER).read_bytes()
        self.cohort.ready.return_value = False
        with mock.patch.object(self.ops, 'app_identity', wraps=self.ops.app_identity) as identity:
            with self.assertRaisesRegex(switcher.SwitchError, 'update or repair'):
                self.switch()
        identity.assert_not_called()
        self.confirm.assert_not_called()
        self.assertEqual((self.config.read_bytes(), (self.home / switcher.MARKER).read_bytes()), before)
        self.assertEqual(self.api.ended, [])

    def test_forward_switch_refuses_a_different_serving_version_before_closing(self):
        self.health.return_value = {'version': '1.3.21'}
        with self.assertRaisesRegex(switcher.SwitchError, 'not ready'):
            self.switch()
        self.confirm.assert_not_called()
        self.assertEqual(self.api.closed, [])
        self.unchanged()

    def test_coherent_reverse_switch_needs_neither_running_router_nor_cli(self):
        switcher._blocks.switch(self.home, 'switched')
        self.cli.unlink()
        self.health.return_value = None
        self.assertEqual(self.switch(target='switched_back'), 'switched_back')
        self.health.assert_not_called()

    def test_pending_forward_can_recover_back_without_router_or_cli(self):
        self.pending()
        self.cli.unlink()
        self.health.return_value = None
        self.assertEqual(self.switch(target='switched_back'), 'switched_back')
        self.assertEqual(((self.home / switcher.MARKER).exists(), self.api.visible), (False, True))

    def test_exit_race_reaches_config_proof_and_reopens_the_new_connection(self):
        facts, activate = self.api.facts, self.api.activate
        quitting = []
        def closing(window, pid):
            self.api.closed.append(pid)
            quitting.append(True)
        def identity(handle, pid):
            if quitting:
                raise self.ops._windows_codex._native.NativeError('process_identity', code=5)
            return facts(handle, pid)
        def live(handle):
            if quitting and self.api.now >= 0.3:
                self.api.rows.pop(handle, None)
            return handle in self.api.rows
        def reopen(app):
            quitting.clear()
            activate(app)
        with mock.patch.object(self.api, 'facts', side_effect=identity), \
                mock.patch.object(self.api, 'close_window', side_effect=closing), \
                mock.patch.object(self.api, 'alive', side_effect=live), \
                mock.patch.object(self.api, 'activate', side_effect=reopen):
            self.assertEqual(self.switch(), 'switched')
        self.assertEqual(len(self.proofs), 1)
        self.assertTrue(self.api.visible)
        self.assertEqual(self.api.ended, [])
        self.assertEqual(switcher._blocks.current(self.home), 'switched')

    def test_failed_reopen_restores_settings_and_reopens_the_original_connection(self):
        activate, calls = self.api.activate, []
        def first_fails(app):
            calls.append(app)
            if len(calls) == 1:
                raise OSError('synthetic activation failure')
            activate(app)
        with mock.patch.object(self.api, 'activate', side_effect=first_fails):
            with self.assertRaises(switcher.SwitchError):
                self.switch()
        self.unchanged()
        self.assertEqual(len(calls), 2)
        self.assertTrue(self.api.visible)
        self.assertFalse((self.home / switcher.MARKER).exists())

    def test_uncertain_scan_after_window_close_reopens_without_writing(self):
        entries, failed = self.api.entries, []
        def scan():
            if self.api.closed and not failed:
                failed.append(True)
                raise self.ops._windows_codex._native.NativeError('process_snapshot', code=5)
            return entries()
        with mock.patch.object(self.api, 'entries', side_effect=scan):
            with self.assertRaises(switcher.SwitchError):
                self.switch()
        self.unchanged()
        self.assertTrue(self.api.visible)
        self.assertEqual(self.api.ended, [])
        facts = json.loads((self.home / 'logs/codex-switch.log').read_text().splitlines()[-1])
        self.assertEqual((facts['operation'], facts['winerror']), ('process_snapshot', 5))

    def test_store_update_after_write_rolls_back_and_reopens_the_fresh_package(self):
        write = switcher._blocks.switch
        def update(home, target):
            write(home, target)
            replacement = self.app.with_name('Store_B')
            self.app.rename(replacement)
            self.api.root, self.api.package = replacement, 'Codex_version_B'
        with mock.patch.object(switcher._blocks, 'switch', side_effect=update):
            with self.assertRaises(switcher.SwitchError):
                self.switch()
        self.unchanged()
        self.assertTrue(self.api.visible)
        self.assertEqual(self.proofs, [])

    def test_pending_recovery_requires_consent_and_verified_exit(self):
        previous = switcher._blocks.rollback_entry(switcher._receipts.codex_attachment(self.home))
        switcher._blocks.switch(self.home, 'switched')
        switcher._atomic.replace_json(self.home / switcher.MARKER,
                                      dict(to='switched', entry=previous))
        self.confirm.return_value = False
        self.assertIsNone(self.switch(prove=lambda _: False))
        self.assertTrue((self.home / switcher.MARKER).exists())
        self.assertEqual(self.api.closed, [])
        self.confirm.return_value = True
        def refuse(_):
            self.assertEqual(self.api.rows, {})
            return False
        self.assertEqual(self.switch(prove=refuse), 'default')
        self.unchanged()
        self.assertTrue(self.api.visible)
        self.assertFalse((self.home / switcher.MARKER).exists())

    def test_windows_unknown_identity_cannot_rewrite_the_way_back(self):
        switcher._blocks.switch(self.home, 'switched')
        before = self.config.read_bytes()
        with mock.patch.object(self.ops._windows_codex, 'identity', side_effect=OSError('unavailable')):
            with self.assertRaises(switcher.SwitchError):
                self.switch()
        self.assertEqual(self.config.read_bytes(), before)
        self.assertEqual(self.api.ended, [])
        self.confirm.assert_not_called()

    def test_still_running_and_unavailable_checks_have_distinct_safe_messages(self):
        for reason, wording in (('still_running', 'still running'), ('query_failed', 'could not be checked')):
            error = self.ops._windows_codex._native.NativeError('request_stop', reason, 5)
            with mock.patch.object(self.ops, 'request_stop', side_effect=error):
                with self.assertRaisesRegex(switcher.SwitchError, wording):
                    self.switch()
            self.unchanged()
        self.assertEqual(self.api.ended, [])


if __name__ == '__main__':
    unittest.main()
