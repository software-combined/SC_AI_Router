"""A missing owned block repairs only under the original attachment's authority."""
import contextlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.install_fixtures import install_mod
from tests.test_native_setup import module


class AttachmentRecoveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.home, self.config = self.root / 'router', self.root / 'config.toml'
        self.home.mkdir()
        self.state = dict(port=1234, token='fixture', clients='codex', openai_mode='subscription')
        (self.home / 'mixed-router-state.json').write_text(json.dumps(self.state))
        (self.home / 'current').write_text('1.0.0')
        (self.home / 'releases/1.0.0').mkdir(parents=True)
        self.recovery, self.maintenance = module('codex_recovery'), module('update_reconcile')
        runtime = mock.Mock()
        runtime.reconcile.return_value = 'inactive'
        modules = {'codex_recovery': self.recovery, 'runtime_rebind': runtime}
        real_load = self.maintenance.load
        self.enterContext(mock.patch.object(self.maintenance, 'load', side_effect=lambda name:
                          modules[name] if name in modules else real_load(name)))
        self.svc = install_mod._svc
        self.enterContext(mock.patch.object(self.svc, 'health', return_value={
            'status': 'ok', 'version': '1.0.0'}))
        self.enterContext(mock.patch.object(install_mod, 'health', return_value={
            'status': 'ok', 'version': '1.0.0'}))
        self.enterContext(mock.patch.object(self.svc.notice, 'show_pending', return_value=False))
        self.attach()

    def attach(self, mode='subscription', variant='default'):
        blocks = self.recovery.load('codex_switch_config')
        block = blocks.build(self.home, self.state, mode, False, variant)
        block = blocks._codex._insert_root_lines(block, ['model = "old-model"'])
        install_mod._codex_config.write_receipt(
            self.home, self.config, block, None, mode, 'original settings', variant=variant,
            reviewer={'removed': ['approvals_reviewer = "auto"']})
        self.config.write_bytes(b'# owner comment\r\nmodel = "current-model"\r\n'
                                b'model_reasoning_effort = "high"\r\n[projects.test]\r\ntrusted = true')
        self.before = self.config.read_bytes()
        self.receipt = self.home / 'activation.json'
        self.evidence = json.loads(self.receipt.read_text())['clients']['codex']

    def run_recovery(self):
        return self.maintenance.run(self.home, self.svc)

    def test_missing_block_restores_mode_and_preserves_choices_bytes_and_evidence(self):
        for mode, variant in (('subscription', 'default'), ('none', 'default'),
                              ('subscription', 'switched'), ('subscription', 'switched_back')):
            with self.subTest(mode=mode, variant=variant):
                self.attach(mode, variant)
                self.assertEqual(self.run_recovery()['attachment'], 'repaired')
                after = self.config.read_bytes()
                self.assertTrue(after.endswith(self.before))
                self.assertNotIn(b'old-model', after)
                self.assertEqual(after.count(b'current-model'), 1)
                entry = json.loads(self.receipt.read_text())['clients']['codex']
                for key in ('previous_sha256', 'reviewer', 'openai_mode', 'variant'):
                    self.assertEqual(entry.get(key), self.evidence.get(key))
                self.assertEqual(self.run_recovery()['attachment'], 'unchanged')
                self.assertEqual(self.config.read_bytes(), after)

    def test_conflicts_damaged_receipts_and_invalid_configuration_never_write(self):
        for text in ('# BEGIN local mixed model picker\n', 'model_provider = "foreign"\n',
                     'model_providers.other = {base_url="https://example.invalid"}\n',
                     'model = [', 'openai_base_url = "https://example.invalid"\n'):
            with self.subTest(text=text):
                self.attach()
                self.config.write_text(text)
                before = self.config.read_bytes(), self.receipt.read_bytes()
                self.assertEqual(self.run_recovery()['attachment'], 'conflict')
                self.assertEqual((self.config.read_bytes(), self.receipt.read_bytes()), before)
        self.attach()
        doc = json.loads(self.receipt.read_text())
        doc['clients']['codex']['inserted_block'] += 'foreign = true\n'
        self.receipt.write_text(json.dumps(doc))
        before = self.config.read_bytes(), self.receipt.read_bytes()
        self.assertEqual(self.run_recovery()['attachment'], 'conflict')
        self.assertEqual((self.config.read_bytes(), self.receipt.read_bytes()), before)

    def test_busy_switch_removal_detach_and_unhealthy_router_disable_repair(self):
        with self.svc.install_lock(self.home):
            self.assertEqual(self.run_recovery()['attachment'], 'deferred')
        for marker in ('codex-switch-pending.json', '.router-removed'):
            with self.subTest(marker=marker):
                path = self.home / marker
                path.touch()
                self.assertEqual(self.run_recovery()['attachment'], 'deferred')
                path.unlink()
        with mock.patch.object(self.svc, 'health', return_value=None):
            self.assertEqual(self.run_recovery()['attachment'], 'unhealthy')
        self.receipt.write_text('{"version":2,"clients":{}}')
        self.assertEqual(self.run_recovery()['attachment'], 'inactive')
        self.assertEqual(self.config.read_bytes(), self.before)

    def test_concurrent_config_edit_and_receipt_failure_preserve_owner_data(self):
        atomic = self.recovery.load('atomic_write')
        real = atomic.replace_text
        def concurrent(path, text, **kwargs):
            if Path(path) == self.config:
                self.config.write_bytes(self.before + b'\n# concurrent owner edit')
            return real(path, text, **kwargs)
        with mock.patch.object(self.recovery, 'load', wraps=self.recovery.load) as load:
            load.side_effect = lambda name: atomic if name == 'atomic_write' else module(name)
            with mock.patch.object(atomic, 'replace_text', side_effect=concurrent):
                self.assertEqual(self.run_recovery()['attachment'], 'conflict')
        self.assertEqual(self.config.read_bytes(), self.before + b'\n# concurrent owner edit')
        self.attach()
        def receipt_failure(path, text, **kwargs):
            if Path(path) == self.receipt:
                raise OSError('fixture write failure')
            return real(path, text, **kwargs)
        with mock.patch.object(self.recovery, 'load', side_effect=lambda name:
                               atomic if name == 'atomic_write' else module(name)), \
                mock.patch.object(atomic, 'replace_text', side_effect=receipt_failure):
            self.assertEqual(self.run_recovery()['attachment'], 'failed')
        self.assertEqual(self.config.read_bytes(), self.before)

    def test_regular_and_express_unchanged_checks_run_after_nested_locks_close(self):
        updater = install_mod._updater
        args = install_mod.build_parser().parse_args(['--home', str(self.home), '--update'])
        def unchanged(*_):
            with self.svc.install_lock(self.home) as held:
                self.assertTrue(held)
            return 0
        for express in (False, True):
            with self.subTest(express=express):
                self.attach()
                args.express_only = express
                with mock.patch.object(updater, '_apply_update', side_effect=unchanged):
                    self.assertEqual(install_mod.do_update(args, _sleep=lambda _: None), 0)
                self.assertIn(b'# BEGIN local mixed model picker', self.config.read_bytes())
        rows = [json.loads(line) for line in (self.home / 'logs/maintenance.jsonl').read_text().splitlines()]
        self.assertTrue(any(r.get('task') == 'express' and r.get('event') == 'completed' for r in rows))

    def test_unchanged_feed_replies_repair_on_regular_and_express_checks(self):
        updater, feed = install_mod._updater, 'file:///fixture/latest.json'
        latest = dict(version='1.0.0', url='file:///fixture/bundle.tar.gz', express=True)
        for express, status in ((False, 200), (True, 200), (False, 304), (True, 304)):
            with self.subTest(express=express, status=status):
                self.attach()
                state = dict(self.state)
                updater._status.verified(state, latest, feed, 'stable', 'same')
                (self.home / 'mixed-router-state.json').write_text(json.dumps(state))
                (self.home / 'update-etag').write_text('same')
                args = install_mod.build_parser().parse_args(
                    ['--home', str(self.home), '--update', '--feed', feed])
                args.express_only = express
                with mock.patch.object(updater._models, 'refresh'), \
                        mock.patch.object(updater._resources, 'ready', return_value=True), \
                        mock.patch.object(updater._resources, 'deliver'):
                    self.assertEqual(install_mod.do_update(args, _sleep=lambda _: None,
                        _read_feed=lambda *_: (status, json.dumps(latest).encode(), 'same'),
                        _announce=lambda *_: None), 0)
                self.assertIn(b'# BEGIN local mixed model picker', self.config.read_bytes())

    def test_missing_file_is_recreated_without_changing_uninstall_evidence(self):
        self.config.unlink()
        self.assertEqual(self.run_recovery()['attachment'], 'repaired')
        entry = json.loads(self.receipt.read_text())['clients']['codex']
        self.assertEqual(entry['previous_sha256'], self.evidence['previous_sha256'])
        self.assertIn('old-model', self.config.read_text())

    def test_unsafe_recovery_exposes_attention_and_verified_repair_clears_only_its_component(self):
        self.config.write_text('model_provider = "foreign"\n')
        self.assertEqual(self.run_recovery()['attachment'], 'conflict')
        state = json.loads((self.home / 'mixed-router-state.json').read_text())
        self.assertEqual(state['component_repairs']['assistants'], 'failed')
        state['component_repairs']['controls'] = 'failed'
        (self.home / 'mixed-router-state.json').write_text(json.dumps(state))
        self.config.write_bytes(self.before)
        self.assertEqual(self.run_recovery()['attachment'], 'repaired')
        state = json.loads((self.home / 'mixed-router-state.json').read_text())
        self.assertEqual(state['component_repairs'], {'assistants': 'ready', 'controls': 'failed'})

    def test_unchanged_reconcile_does_not_take_the_installation_lock(self):
        self.assertEqual(self.run_recovery()['attachment'], 'repaired')
        before = self.config.read_bytes(), self.receipt.read_bytes()
        with mock.patch.object(self.svc, 'install_lock', side_effect=AssertionError('no mutation')):
            self.assertEqual(self.run_recovery()['attachment'], 'unchanged')
        self.assertEqual((self.config.read_bytes(), self.receipt.read_bytes()), before)

    def test_unchanged_checks_can_finish_while_a_foreground_operation_owns_the_lock(self):
        self.assertEqual(self.run_recovery()['attachment'], 'repaired')
        with self.svc.install_lock(self.home) as held:
            self.assertTrue(held)
            self.assertEqual(self.run_recovery()['attachment'], 'unchanged')

    def test_restart_notice_and_runtime_inspection_leave_the_installation_lock_free(self):
        available = []
        def inspect_lock(*_, **__):
            with self.svc.install_lock(self.home) as held:
                available.append(held)
            return 'inactive'
        runtime = self.maintenance.load('runtime_rebind')
        runtime.reconcile.side_effect = inspect_lock
        with mock.patch.object(self.svc.notice, 'show_pending', side_effect=inspect_lock):
            self.assertEqual(self.run_recovery()['attachment'], 'repaired')
            self.assertEqual(self.run_recovery()['attachment'], 'unchanged')
        self.assertTrue(available)
        self.assertTrue(all(available))

    def test_supported_detach_between_preflight_and_lock_prevents_repair(self):
        original = self.svc.install_lock
        @contextlib.contextmanager
        def detach(*args, **kwargs):
            with original(*args, **kwargs) as held:
                doc = json.loads(self.receipt.read_text())
                del doc['clients']['codex']
                self.receipt.write_text(json.dumps(doc))
                yield held
        with mock.patch.object(self.svc, 'install_lock', side_effect=detach):
            self.assertEqual(self.run_recovery()['attachment'], 'inactive')
        self.assertEqual(self.config.read_bytes(), self.before)

    def test_healthy_unchanged_regular_and_express_feeds_never_take_install_lock(self):
        self.assertEqual(self.run_recovery()['attachment'], 'repaired')
        updater, feed = install_mod._updater, 'file:///fixture/latest.json'
        latest = dict(version='1.0.0', url='file:///fixture/bundle.tar.gz', express=True)
        original = self.svc.install_lock
        def only_update_lock(home, name='install.lock', **kwargs):
            self.assertNotEqual(name, 'install.lock')
            return original(home, name, **kwargs)
        for express, status in ((False, 200), (True, 200), (False, 304), (True, 304)):
            with self.subTest(express=express, status=status):
                state = json.loads((self.home / 'mixed-router-state.json').read_text())
                updater._status.verified(state, latest, feed, 'stable', 'same')
                (self.home / 'mixed-router-state.json').write_text(json.dumps(state))
                (self.home / 'update-etag').write_text('same')
                args = install_mod.build_parser().parse_args(
                    ['--home', str(self.home), '--update', '--feed', feed])
                args.express_only = express
                with mock.patch.object(self.svc, 'install_lock', side_effect=only_update_lock), \
                        mock.patch.object(updater._models, 'refresh'), \
                        mock.patch.object(updater._resources, 'ready', return_value=True), \
                        mock.patch.object(updater._resources, 'deliver') as deliver:
                    self.assertEqual(install_mod.do_update(args, _sleep=lambda _: None,
                        _read_feed=lambda *_: (status, json.dumps(latest).encode(), 'same'),
                        _announce=lambda *_: None), 0)
                    deliver.assert_not_called()


if __name__ == '__main__':
    unittest.main()
