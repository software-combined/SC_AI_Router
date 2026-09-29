"""Switch Codex offers: once per ChatGPT usage-limit episode, and the way back.

The updater offers Switch Codex when the router has recorded a usage-limit
episode from an affected Codex desktop build, and the way back once Codex is
switched and the episode has ended or the installed ChatGPT app is at or
above FIXED_IN. These pin who is offered what, that each offer is made once
per episode, and that no dialog or write failure ever reaches the updater.
"""
import contextlib
import importlib.util
import json
import os
import plistlib
import shutil
import stat
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from ai_router import usage_episodes

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ('Codex Desktop/0.158.0-alpha.2.1 (Mac OS 26.5.0; arm64) unknown '
           '(Codex Desktop; %s)')
T0, HOUR = 1_790_000_000, 3600


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


offers = _load('router_test_codex_switch_offer', 'packaging/codex_switch_offer.py')
updater = _load('router_test_offer_updater', 'packaging/updater.py')


def stamp(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec='seconds')


class _Home(unittest.TestCase):
    """A subscription Codex install with Switch Codex, and no real dialog ever."""

    def setUp(self):
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        self.home = Path(home)
        (self.home / 'Switch Codex.app').mkdir()
        self.spawned = []
        for target, name, value in (
                (offers, 'APP', self.home / 'Switch Codex.app'),
                (offers, 'CHATGPT_APP', self.home / 'ChatGPT.app'),
                (offers, 'which', lambda _tool: '/usr/bin/osascript'),
                (offers._notice, '_spawn', self._spawn),
                (offers._notice, '_pid_alive', lambda _pid: True),
                (offers._notice, 'PROBE_GRACE_S', 0)):
            self.enterContext(mock.patch.object(target, name, value))
        self.attach()

    def _spawn(self, cmd):
        self.spawned.append(cmd)
        return 4242

    def attach(self, mode='subscription', variant=None):
        entry = {'config_path': str(self.home / 'config.toml'),
                 'inserted_block': '# managed block\n', 'openai_mode': mode}
        if variant:
            entry['variant'] = variant
        offers._codex.receipt_path_for(self.home).write_text(json.dumps(
            {'version': offers._codex.RECEIPT_VERSION, 'clients': {'codex': entry}}))

    def record(self, now=T0, resets=T0 + HOUR, version='26.924.22138'):
        """One desktop refusal, written by the router's own recorder."""
        error = {'type': 'usage_limit_reached'}
        if resets is not None:
            error['resets_at'] = resets
        usage_episodes.record(
            SimpleNamespace(server=SimpleNamespace(credentials=SimpleNamespace(home=self.home))),
            SimpleNamespace(provider='openai', headers={'User-Agent': DESKTOP % version}),
            json.dumps({'error': error}).encode(), now=now)

    def write_episode(self, version):
        (self.home / offers.EPISODE_FILE).write_text(json.dumps(
            {'seen_at': stamp(T0), 'resets_at': stamp(T0 + HOUR), 'client_version': version}))

    def reset(self):
        for name in (offers.EPISODE_FILE, offers.OFFERS_FILE):
            (self.home / name).unlink(missing_ok=True)
        self.attach()

    def run_pass(self, now=T0 + 60, platform_name='darwin'):
        return offers.offer(self.home, now=now, platform_name=platform_name)

    def offered(self):
        path = self.home / offers.OFFERS_FILE
        return json.loads(path.read_text()) if path.exists() else None


class OfferTests(_Home):
    def test_an_affected_desktop_episode_is_offered_once(self):
        self.record()
        self.assertEqual(self.run_pass(), offers.SWITCH)
        self.assertIsNone(self.run_pass(T0 + 120))
        self.assertEqual(len(self.spawned), 1)
        script = self.spawned[0][-1]
        self.assertIn(json.dumps(offers.MESSAGES[offers.SWITCH]), script)
        self.assertIn('/usr/bin/open " & quoted form of ' + json.dumps(str(offers.APP)), script)
        self.assertEqual(self.offered(), {'seen_at': stamp(T0), 'offered': ['switch']})
        if os.name != 'nt':
            mode = stat.S_IMODE(os.stat(self.home / offers.OFFERS_FILE).st_mode)
            self.assertEqual(mode, 0o600)
        # A later episode is a new limit period and gets its own offer.
        self.record(now=T0 + HOUR + 10, resets=T0 + 2 * HOUR)
        self.assertEqual(self.run_pass(T0 + HOUR + 20), offers.SWITCH)
        self.assertEqual(len(self.spawned), 2)

    def test_the_router_record_is_read_as_the_router_writes_it(self):
        self.assertEqual(offers.EPISODE_FILE, usage_episodes.NAME)
        self.assertEqual(offers.WINDOW_S, usage_episodes.WINDOW_S)
        self.record(resets=None)
        self.assertEqual(offers.episode(self.home), {
            'seen_at': stamp(T0), 'end': T0 + offers.WINDOW_S, 'version': (26, 924, 22138)})
        for text in ('not json', '[]', json.dumps({'seen_at': stamp(T0), 'resets_at': 7}),
                     json.dumps({'seen_at': stamp(T0), 'client_version': '26.924 beta'})):
            with self.subTest(text=text):
                (self.home / offers.EPISODE_FILE).write_text(text)
                self.assertIsNone(offers.episode(self.home))

    def test_no_offer_outside_its_audience(self):
        cases = (
            ('unaffected build', lambda: self.record(version='26.917.51855'), {}),
            ('CLI version', lambda: self.write_episode('0.158.0'), {}),
            ('no desktop version', lambda: self.write_episode(None), {}),
            ('no ChatGPT subscription', lambda: (self.attach(mode='none'), self.record()), {}),
            ('Codex not attached', lambda: (
                offers._codex.receipt_path_for(self.home).unlink(), self.record()), {}),
            ('Linux', self.record, {'platform_name': 'linux'}),
            ('Windows', self.record, {'platform_name': 'win32'}),
            ('already switched', lambda: (self.attach(variant='switched'), self.record()), {}),
            ('episode over', self.record, {'now': T0 + HOUR}),
        )
        for name, setup, kwargs in cases:
            with self.subTest(name):
                self.reset()
                setup()
                self.assertIsNone(self.run_pass(**kwargs))
        with self.subTest('no Switch Codex app'), \
                mock.patch.object(offers, 'APP', self.home / 'Missing.app'):
            self.reset()
            self.record()
            self.assertIsNone(self.run_pass())
        self.assertEqual(self.spawned, [])
        self.assertIsNone(self.offered())

    def test_the_way_back_follows_the_end_of_the_episode(self):
        self.attach(variant='switched')
        self.record()
        self.assertIsNone(self.run_pass(T0 + 60))
        self.assertEqual(self.run_pass(T0 + HOUR), offers.BACK)
        self.assertIsNone(self.run_pass(T0 + HOUR + 60))
        self.assertEqual(len(self.spawned), 1)
        self.assertIn(json.dumps(offers.MESSAGES[offers.BACK]), self.spawned[0][-1])
        self.assertEqual(self.offered(), {'seen_at': stamp(T0), 'offered': ['back']})

    def test_a_fixed_build_ends_the_offers_and_gets_the_way_back_at_once(self):
        self.record()  # an episode from an affected 26.924.22138 build
        with mock.patch.object(offers, 'FIXED_IN', '26.924.22138'):
            self.assertIsNone(self.run_pass())  # recorded from a build at FIXED_IN
        contents = self.home / 'ChatGPT.app' / 'Contents'
        contents.mkdir(parents=True)
        (contents / 'Info.plist').write_bytes(
            plistlib.dumps({'CFBundleShortVersionString': '26.1001.5'}))
        with mock.patch.object(offers, 'FIXED_IN', '26.1001.5'):
            self.assertIsNone(self.run_pass())  # the installed app no longer needs it
            self.attach(variant='switched')
            self.assertEqual(self.run_pass(), offers.BACK)  # the episode is still on
            self.assertIsNone(self.run_pass(T0 + 120))
        self.assertEqual(len(self.spawned), 1)

    def test_a_missing_or_undrawn_dialog_leaves_the_offer_pending(self):
        self.record()
        with mock.patch.object(offers, 'which', lambda _tool: None):
            self.assertIsNone(self.run_pass())
        self.assertEqual((self.spawned, self.offered()), ([], None))
        with mock.patch.object(offers._notice, '_pid_alive', lambda _pid: False):
            self.assertIsNone(self.run_pass(T0 + 120))
        self.assertEqual(self.offered()['offered'], [])
        self.assertEqual(self.run_pass(T0 + 180), offers.SWITCH)
        self.assertEqual(len(self.spawned), 2)

    def test_a_failed_write_or_dialog_never_raises(self):
        self.record()
        with mock.patch.object(offers._atomic, 'replace_json',
                               side_effect=OSError('read-only home')):
            self.assertIsNone(self.run_pass())
        self.assertEqual(self.spawned, [], 'an offer it cannot remember is never shown')
        with mock.patch.object(offers._notice, '_spawn', side_effect=OSError('no tool')):
            self.assertIsNone(self.run_pass())
        self.assertEqual(self.offered()['offered'], [])
        receipt = offers._codex.receipt_path_for(self.home)
        for text in ('not json', json.dumps({'version': offers._codex.RECEIPT_VERSION, 'clients': {
                'codex': {'inserted_block': 'x', 'openai_mode': 'subscription',
                          'variant': 'sideways'}}})):
            with self.subTest(receipt=text[:12]):
                receipt.write_text(text)
                self.assertIsNone(self.run_pass())
        self.assertEqual(self.spawned, [])


class UpdaterPassTests(unittest.TestCase):
    def setUp(self):
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        self.home = Path(home)

    def run_update(self, express, apply=None, held=None):
        """One do_update pass with the pass itself stubbed; the offer seam it called."""
        args = SimpleNamespace(home=str(self.home), express_only=express, feed=None)
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(
                updater, '_apply_update', apply or mock.Mock(return_value=0)))
            self.offer = stack.enter_context(mock.patch.object(updater, '_offer_codex_switch'))
            if held is not None:
                lock = mock.MagicMock()
                lock.return_value.__enter__.return_value = held
                stack.enter_context(mock.patch.object(updater._svc, 'install_lock', lock))
            updater.do_update(args, _sleep=lambda _seconds: None)
        return self.offer

    def test_every_pass_ends_with_the_offer(self):
        for express in (True, False):
            with self.subTest(express=express):
                self.run_update(express).assert_called_once_with(self.home)
        failing = mock.Mock(side_effect=updater.UpdateError('feed_invalid', 'bad feed'))
        with self.assertRaises(updater.UpdateError):
            self.run_update(True, apply=failing)
        self.offer.assert_called_once_with(self.home)
        # A parent that did not get the lock leaves the offer to the one that did.
        self.run_update(True, held=False).assert_not_called()

    def test_the_offer_cannot_disturb_a_pass(self):
        for failure in (OSError('missing'), SystemExit('edited'), RuntimeError('boom')):
            with self.subTest(failure=type(failure).__name__), \
                    mock.patch.object(updater._svc, 'load', side_effect=failure):
                self.assertIsNone(updater._offer_codex_switch(self.home))
        module = SimpleNamespace(offer=mock.Mock(side_effect=RuntimeError('boom')))
        with mock.patch.object(updater._svc, 'load', return_value=module) as load:
            self.assertIsNone(updater._offer_codex_switch(self.home))
        self.assertEqual(Path(load.call_args.args[1]).name, 'codex_switch_offer.py')
        module.offer.assert_called_once_with(self.home)


if __name__ == '__main__':
    unittest.main()
