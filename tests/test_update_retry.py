"""Rejected update checks retry without turning a healthy install into a repair."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.install_fixtures import install_mod_factory
from tests.test_native_setup import module


class QuietRetryTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (self.home / 'current').write_text('1.0.0')
        (self.home / 'releases/1.0.0').mkdir(parents=True)
        self.save({})
        self.install = install_mod_factory()
        self.updater = self.install._updater
        self.warning = module('update_warning')
        self.latest = dict(version='1.0.0', serial=9, express=True,
            url='https://dist.softwarecombined.com/bundles/test.tar.gz')
        self.verifier = module('feed_verify')
        self.seed, public = self.verifier.generate_keypair()
        self.enterContext(mock.patch.object(self.updater, '_FEED_VERIFY_KEY', public))
        self.enterContext(mock.patch.object(self.updater._models, 'refresh'))
        self.enterContext(mock.patch.object(self.updater._resources, 'ready', return_value=True))
        self.child = self.enterContext(mock.patch.object(self.updater._svc, 'run'))
        self.spawn = self.enterContext(mock.patch.object(self.warning.subprocess, 'Popen'))
        self.enterContext(mock.patch.object(self.updater, '_offer_notices',
            side_effect=lambda home: self.warning.offer(home)))
        self.enterContext(mock.patch.dict('os.environ', {'ROUTER_NO_NOTICE': '0'}))

    def save(self, extra):
        (self.home / 'mixed-router-state.json').write_text(json.dumps(dict(
            port=1, token='synthetic', clients='none', **extra)))

    def state(self):
        return json.loads((self.home / 'mixed-router-state.json').read_text())

    def check(self, *, express=True, valid=True):
        args = self.install.build_parser().parse_args(['--home', str(self.home),
            '--update'] + (['--express-only'] if express else []))
        body = json.dumps(self.latest).encode()
        signature = self.verifier.sign_hex(self.seed, body if valid else b'previous feed').encode()
        def fetch(url):
            self.assertTrue(url.endswith('.json.sig'), 'unchanged check must not download a bundle')
            return signature
        with contextlib.redirect_stdout(io.StringIO()):
            return self.install.do_update(args, _fetch=fetch,
                _read_feed=lambda *_: (200, body, 'verified'),
                _sleep=lambda _: None, _announce=lambda *_: None)

    def test_publication_mismatch_then_verified_unchanged_check_recovers_quietly(self):
        for express, enabled in ((True, True), (True, False), (False, True)):
            with self.subTest(express=express, enabled=enabled):
                self.save({})
                self.latest['express'] = enabled
                with self.assertRaises(self.updater.UpdateError) as caught:
                    self.check(express=express, valid=False)
                self.assertEqual(caught.exception.error_code, 'feed_signature')
                self.assertEqual(self.state()['last_error'], 'feed_signature')
                self.spawn.assert_not_called()
                self.assertEqual(self.check(express=express), 0)
                state = self.state()
                self.assertNotIn('last_error', state)
                self.assertEqual(state['update_failure_streak'], 0)
                self.assertEqual(state['latest_verified']['version'], '1.0.0')
                self.assertNotIn('last_applied_version', state)
                self.assertEqual((self.home / 'current').read_text(), '1.0.0')
                self.child.assert_not_called()
                self.spawn.assert_not_called()

    def test_persistent_bad_signatures_remain_blocked_and_visible_without_repair(self):
        for _ in range(3):
            with self.assertRaises(self.updater.UpdateError):
                self.check(valid=False)
        facts = self.updater._status.summary(self.state(), '1.0.0')
        self.assertEqual(facts['last_error'], 'feed_signature')
        self.assertTrue(facts['retry_pending'])
        self.assertFalse(facts['offer_repair'])
        self.assertNotIn('latest_verified', self.state())
        self.child.assert_not_called()
        self.spawn.assert_not_called()

    def test_valid_feed_cannot_clear_pending_installation_or_failed_components(self):
        self.save(dict(last_error='feed_signature', installation_repair_required=True,
            component_repairs={'controls': 'failed'}, update_failures={'1.0.0': 3}))
        self.assertEqual(self.check(), 0)
        state = self.state()
        self.assertNotIn('last_error', state)
        self.assertTrue(state['installation_repair_required'])
        self.assertEqual(state['component_repairs']['controls'], 'failed')
        self.assertEqual(state['update_failures'], {'1.0.0': 3})
        self.assertTrue(self.updater._status.summary(state, '1.0.0')['offer_repair'])
        self.spawn.assert_called_once()

    def test_new_rejections_cannot_turn_a_feed_failure_into_verified_success(self):
        for field, value, reason in (('serial', 8, 'feed_serial'),
                ('url', 'https://untrusted.example/bundle', 'feed_untrusted')):
            with self.subTest(field=field):
                self.save(dict(last_error='feed_signature'))
                (self.home / 'feed-serial').write_text('9')
                previous = self.latest[field]
                self.latest[field] = value
                with self.assertRaises(self.updater.UpdateError) as caught:
                    self.check()
                self.assertEqual(caught.exception.error_code, reason)
                self.assertNotIn('latest_verified', self.state())
                self.latest[field] = previous
        self.spawn.assert_not_called()
        self.child.assert_not_called()


class RetryPresentationTests(unittest.TestCase):
    def test_all_check_failures_stay_quiet_without_inventing_an_install_fault(self):
        status = module('update_status')
        for error in status.ERROR_CODES:
            if error.startswith('installer_'):
                continue
            with self.subTest(error=error):
                facts = status.summary(dict(last_error=error, update_failure_streak=7))
                self.assertFalse(facts['offer_repair'])
                self.assertIsNone(facts['required_action'])
                self.assertEqual(facts['last_error'], error)
                self.assertIn(error, module('diagnostics')._update_line(facts))

    def test_retry_state_survives_control_and_support_redaction(self):
        control, operator = module('desktop_control'), module('operator_surface')
        raw = dict(version='1.0.0', running_version='1.0.0', clients={},
            routing_healthy=True, update=dict(retry_pending=True, last_error='feed_signature'))
        installer = SimpleNamespace(_sync_seams=lambda: None,
            _diag=SimpleNamespace(_status_document=lambda _: raw))
        original = control.load
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(control,
                'load', side_effect=lambda name: installer if name == 'install' else original(name)):
            facts = control.snapshot(Path(temporary))
        self.assertTrue(facts['update']['retry_pending'])
        menu = module('desktop_model').menu(facts)
        text = json.dumps(menu)
        self.assertIn('Updates will retry automatically', text)
        self.assertNotIn('Updates need repair', text)
        self.assertNotIn('Repair now', text)
        self.assertTrue(operator._support_document(raw)['update']['retry_pending'])

    def test_check_setup_explains_retry_without_starting_interactive_repair(self):
        setup, dialog = module('native_setup'), mock.Mock()
        facts = dict(serving=True, onboarding=dict(clients={}, ready=True),
                     update=dict(retry_pending=True))
        with mock.patch.object(setup, 'status', return_value=facts):
            setup._check(Path('/synthetic/resources'), Path('/synthetic/home'), dialog)
        self.assertIn('retry automatically', dialog.message.call_args.args[0])
        self.assertNotIn('repair', dialog.message.call_args.args[0].lower())
        dialog.confirm_result.assert_not_called()
