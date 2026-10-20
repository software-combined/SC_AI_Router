"""Failure warnings persist independently of routing and use one daily dialog."""
import contextlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_native_setup import module

NOW = '2026-10-18T13:05:00Z'


class WarningPolicyTests(unittest.TestCase):
    def test_first_failure_is_visible_and_second_failure_offers_repair(self):
        status = module('update_status')
        state = {}
        status.record(state, 'feed_unreachable', now=NOW)
        facts = status.summary(state, now=status.seconds(NOW))
        self.assertEqual(facts['required_action'], 'repair')
        self.assertFalse(facts['offer_repair'])
        status.record(state, 'feed_unreachable', now=NOW)
        self.assertTrue(status.summary(state, now=status.seconds(NOW))['offer_repair'])

    def test_blocked_install_and_each_failed_component_offer_immediately(self):
        status = module('update_status')
        for state in ({'last_error': 'download_signin_required'},
                {'update_failures': {'1.3.2.185': 3}},
                *({'component_repairs': {name: 'failed'}} for name in status.COMPONENTS)):
            self.assertTrue(status.summary(state, '1.2.6.174')['offer_repair'], state)

    def test_two_missed_intervals_plus_fifteen_minutes_is_the_boundary(self):
        status = module('update_status')
        state = dict(last_check_at=NOW)
        deadline = status.seconds(NOW) + 8 * 3600 + 15 * 60
        self.assertIsNone(status.summary(state, now=deadline - 1)['required_action'])
        facts = status.summary(state, now=deadline)
        self.assertTrue(facts['missed_scheduled_checks'])
        self.assertTrue(facts['offer_repair'])
        self.assertIsNone(status.summary({'last_check_at': 'damaged'}, now=deadline)['required_action'])

    def test_success_clears_only_verified_components_and_formats_valid_times(self):
        status = module('update_status')
        state = dict(last_error='feed_unreachable', component_repairs={'assistants': 'failed'})
        status.record(state, '', now=NOW)
        self.assertTrue(status.summary(state, now=status.seconds(NOW))['offer_repair'])
        self.assertEqual(status.display_time('2026-99-18T13:05:00Z'), 'Unknown')
        self.assertNotEqual(status.display_time(NOW), 'Unknown')


class WarningDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.owner = module('update_warning')
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.state = self.home / 'mixed-router-state.json'
        self.state.write_text('{"last_error":"installer_failed","custom":"preserved"}')
        self.before = self.state.read_bytes()
        self.doc = dict(running_version='1.2.6.174', channel='beta', clients={'codex': {}},
            update=dict(offer_repair=True, latest_known_version='1.3.2.185', last_successful_check_at=NOW))
        self.dialog = mock.Mock()
        original = self.owner.load
        for patcher in (mock.patch.object(self.owner, 'load', side_effect=lambda name:
                self.dialog if name == 'native_dialog' else original(name)),
                mock.patch.object(self.owner, 'snapshot', return_value=self.doc),
                mock.patch.object(self.owner, 'repair'),
                mock.patch.dict(os.environ, {'ROUTER_NO_NOTICE': '0'})):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.now = original('update_status').seconds(NOW)

    def test_no_gui_retains_the_warning_and_next_opening_can_offer_repair(self):
        self.dialog.confirm_result.return_value = None
        self.owner.show(self.home, self.now)
        self.assertFalse((self.home / self.owner.RECEIPT).exists())
        self.dialog.confirm_result.return_value = True
        self.owner.show(self.home, self.now)
        self.owner.repair.assert_called_once_with(self.home)
        self.assertEqual(self.state.read_bytes(), self.before)
        text = self.dialog.confirm_result.call_args.args[0]
        self.assertIn('Codex', text)
        self.assertNotIn('Claude', text)
        self.assertIn('1.2.6.174', text)
        self.assertIn('1.3.2.185', text)

    def test_later_uses_the_daily_limit_without_clearing_pending_state(self):
        self.dialog.confirm_result.return_value = False
        self.owner.show(self.home, self.now)
        self.owner.show(self.home, self.now + 24 * 3600 - 1)
        self.assertEqual(self.dialog.confirm_result.call_count, 1)
        self.owner.show(self.home, self.now + 24 * 3600)
        self.assertEqual(self.dialog.confirm_result.call_count, 2)
        self.owner.repair.assert_not_called()
        self.assertEqual(self.state.read_bytes(), self.before)

    def test_an_open_warning_and_a_repair_that_already_succeeded_never_start_another(self):
        with self.owner.load('service').install_lock(self.home, '.update-warning.lock'):
            self.owner.show(self.home, self.now)
        self.dialog.confirm_result.assert_not_called()
        self.dialog.confirm_result.return_value = True
        self.owner.snapshot.side_effect = [self.doc, {'update': {'offer_repair': False}}]
        self.owner.show(self.home, self.now)
        self.owner.repair.assert_not_called()

    def test_failed_presentation_and_spawn_are_isolated_from_updates(self):
        self.dialog.confirm_result.side_effect = OSError('no desktop session')
        self.assertEqual(self.owner.main(['--home', str(self.home)]), 0)
        self.assertFalse((self.home / self.owner.RECEIPT).exists())
        with mock.patch.object(self.owner.subprocess, 'Popen', side_effect=OSError('no session')):
            self.owner.offer(self.home)
        self.assertEqual(self.state.read_bytes(), self.before)

    def test_detached_worker_has_no_browser_or_notification_fallback(self):
        with mock.patch.object(self.owner.subprocess, 'Popen') as spawn:
            self.owner.offer(self.home)
        command = spawn.call_args.args[0]
        self.assertEqual(command[-2:], ['--home', str(self.home)])
        self.assertEqual(Path(command[1]).name, 'update_warning.py')
        self.assertEqual(spawn.call_args.kwargs['stdout'], self.owner.subprocess.DEVNULL)


class WarningDialogTests(unittest.TestCase):
    def test_each_platform_uses_repair_now_later_with_title_and_product_icon(self):
        dialog = module('native_dialog')
        for platform in ('darwin', 'win32', 'linux'):
            result = mock.Mock(returncode=0, stdout='button returned:Repair now', stderr='')
            with mock.patch.object(dialog.sys, 'platform', platform), \
                    mock.patch.object(dialog.dialog, 'tool', return_value='dialog'), \
                    mock.patch.dict(os.environ, {'DISPLAY': ':synthetic'}):
                run = mock.Mock(return_value=result)
                self.assertTrue(dialog.confirm_result('Repair updates?', run=run,
                                                     labels=('Repair now', 'Later')))
                text = ' '.join(run.call_args.args[0])
                for expected in ('Repair now', 'Later', 'SCG Router', 'router-icon.png'):
                    self.assertIn(expected, text)


class WarningUpdaterTests(unittest.TestCase):
    def test_notification_runs_after_failure_state_is_recorded(self):
        from tests.install_fixtures import install_mod_factory
        installer = install_mod_factory()
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / 'mixed-router-state.json').write_text('{}')
            args = installer.build_parser().parse_args(['--home', str(home)])
            seen = []
            def offer(path):
                with installer._svc.install_lock(path, 'update.lock') as held:
                    seen.append((json.loads((path / 'mixed-router-state.json').read_text())['last_error'], held))
            with mock.patch.object(installer._updater, '_offer_notices', side_effect=offer):
                with self.assertRaises(OSError):
                    installer.do_update(args, _sleep=lambda _: None,
                        _read_feed=mock.Mock(side_effect=OSError('offline')))
            self.assertEqual(seen, [('feed_unreachable', False)])


class WarningMenuTests(unittest.TestCase):
    def facts(self):
        return dict(status='Running', version='1.3.2.185', running_version='1.2.6.174',
            update=dict(required_action='repair', channel='beta', source='a' * 64,
                latest_known_version='1.3.2.185', last_successful_check='18 Oct 2026 AEDT',
                last_successful_check_at='2026-10-18T12:05:00Z',
                component_repairs={'assistants': 'failed', 'controls': 'failed'}))

    def test_healthy_routing_still_shows_durable_update_and_component_warnings(self):
        model = module('desktop_model')
        doc = model.menu(self.facts(), available='1.3.2.185')
        text = json.dumps(doc)
        for label in ('Running version 1.2.6.174', 'Latest known beta version 1.3.2.185',
                      'Updates need repair', 'Assistant connections need repair', 'Router controls need repair'):
            self.assertIn(label, text)
        actions = dict(model.chooser(doc['menu'])[1])
        self.assertIn('Repair now', actions['setup.resume'])
        self.assertNotIn('updates.install', actions)
        facts = self.facts()
        facts['update']['component_repairs'] = {'controls_launchers': 'failed'}
        self.assertIn('Router controls need repair', json.dumps(model.menu(facts)))

    def test_window_check_cache_is_bound_to_installed_version_channel_and_source(self):
        model, facts = module('desktop_model'), self.facts()
        checked = dict(installed=facts['version'], channel='beta', source='a' * 64,
                       latest='1.3.2.186', checked_at=NOW, at='Fresh manual check')
        self.assertIn('Latest known beta version 1.3.2.186',
                      json.dumps(model.menu(facts, checked_update=checked)))
        for key, changed in (('installed', '1.2.6.174'), ('channel', 'stable'), ('source', 'b' * 64)):
            bad = dict(checked, **{key: changed})
            self.assertNotIn('1.3.2.186', json.dumps(model.menu(facts, checked_update=bad)))
        self.assertIn('Updates need repair', json.dumps(model.menu(facts, checked_update=checked)))

    def test_persisted_verification_supersedes_an_older_manual_check(self):
        model, facts = module('desktop_model'), self.facts()
        facts['update'].update(required_action='update', component_repairs={},
            latest_known_version='1.3.2.186', last_successful_check='Later scheduled check',
            last_successful_check_at='2026-10-18T14:05:00Z')
        checked = dict(installed=facts['version'], channel='beta', source='a' * 64,
                       latest='1.3.2.185', checked_at=NOW, at='Old manual check')
        doc = model.menu(facts, checked_update=checked)
        self.assertIn('Install update 1.3.2.186', dict(model.chooser(doc['menu'])[1])['updates.install'])
        self.assertIn('Last successful check Later scheduled check', json.dumps(doc))
        self.assertNotIn('Old manual check', json.dumps(doc))
        # A later verified check also supersedes a cache advertising a higher version.
        checked['latest'] = '1.3.2.187'
        self.assertNotIn('1.3.2.187', json.dumps(model.menu(facts, checked_update=checked)))

    def test_read_only_check_never_calls_a_failed_install_up_to_date(self):
        from types import SimpleNamespace
        control, dialog = module('desktop_control'), mock.Mock()
        original = control.load
        checked = dict(installed='1.3.2.185', latest='1.3.2.185', available=None,
                       channel='beta', source='a' * 64, required_action='repair')
        with mock.patch.object(control, '_installer', return_value=SimpleNamespace(
                returncode=0, stdout=json.dumps(checked))), \
                mock.patch.object(control, 'load', side_effect=lambda name:
                    dialog if name == 'native_dialog' else original(name)):
            result = control.execute('/synthetic/home', '/synthetic/resources', 'updates.check')
        self.assertIn('need repair', dialog.message.call_args.args[0])
        self.assertNotIn('up to date', dialog.message.call_args.args[0])
        self.assertIsNone(result['available'])
        self.assertEqual(result['checked_update']['source'], 'a' * 64)

    def test_control_window_fallback_displays_the_same_verified_version_and_warning_rows(self):
        menu, model, dialog = module('desktop_menu'), module('desktop_model'), mock.Mock()
        control = mock.Mock()
        control.snapshot.return_value = self.facts()
        dialog.choose.return_value = None
        service = mock.Mock()
        service.install_lock.return_value = contextlib.nullcontext(True)
        owners = dict(desktop_model=model, desktop_control=control, native_dialog=dialog,
                      native_shortcuts=module('native_shortcuts'), service=service)
        with mock.patch.object(menu, 'load', side_effect=owners.__getitem__):
            menu.fallback(Path('/synthetic/home'), Path('/synthetic/resources'))
        text, choices = dialog.choose.call_args.args
        for label in ('Running version 1.2.6.174', 'Latest known beta version 1.3.2.185',
                      'Last successful check 18 Oct 2026 AEDT', 'Updates need repair'):
            self.assertIn(label, text)
        self.assertIn('Repair now', dict(choices)['setup.resume'])


class WarningRepairCommandTests(unittest.TestCase):
    def test_repair_uses_the_retained_controller_and_public_saved_channel(self):
        owner = module('update_warning')
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            controller = home / 'control/1.3.2.185/packaging/install.py'
            controller.parent.mkdir(parents=True)
            controller.write_text('# synthetic verified controller')
            (home / 'control-version').write_text('1.3.2.185')
            (home / 'channel').write_text('beta')
            run = mock.Mock()
            owner.repair(home, run=run)
            args = run.call_args.args[0]
            self.assertEqual(args[1], str(controller))
            self.assertIn('https://dist.softwarecombined.com/beta/latest.json', args)
            self.assertIn('--repair', args)
            self.assertNotIn('--setup', args)
