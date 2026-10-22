"""Switch Codex on a Mac: faked app lifecycle, real blocks, receipt and proof code.

`switched` is strict: one app with its CLI, a graceful quit and a proof, any
doubt refused first or undone exactly (the owner's latest model pick kept).
Switching back depends on nothing it can lose: no proof, no app it can find.
"""
import importlib.util
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests._platform import unix_only
from tests.test_codex_config_proof import FAKE

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'codex_desktop_switch_test', ROOT / 'packaging' / 'codex_desktop_switch.py')
switcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(switcher)
blocks, platform = switcher._blocks, switcher._platform
PICK = 'model = "z-ai/glm-5.3"'
JARGON = ('nonce', 'loopback', 'catalogue', 'owner-only', '127.0.0.1', 'token',
          'endpoint', 'process', 'daemon', 'config', 'http')


class FakeApp:
    """The ChatGPT app as the flow sees it; `identity` raises when not found."""

    def __init__(self, root, confirm=True, stops=True, identity=None):
        self.root, self.answer, self.stops, self.identity = root, confirm, stops, identity
        self.calls = []

    def app_identity(self, platform_name, run=None, app=None):
        if self.identity is not None:
            raise self.identity
        return {'root': str(self.root)}

    def confirm(self, message, platform_name, run=None):
        self.calls.append(('confirm', message))
        return self.answer

    def request_stop(self, platform_name, run=None, app=None, *, identity=None):
        self.calls.append(('stop', app.bundle_id))
        if isinstance(self.stops, Exception):
            raise self.stops
        return self.stops

    def open_app(self, platform_name, run=None, app=None, *, identity=None):
        self.calls.append(('open', app.bundle_id))
        return SimpleNamespace(returncode=0)

    def show_message(self, message, platform_name, run=None):
        self.calls.append(('notice', message))


class Interrupted(BaseException):
    """A run cut short: nothing in the flow catches it."""


@unix_only
class SwitchFlowTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.home, self.config = self.root / 'router', self.root / 'codex' / 'config.toml'
        self.app = self.root / 'Apps' / 'ChatGPT.app'
        self.cli = self.app / switcher._proof.BUNDLED[0]
        self.cli.parent.mkdir(parents=True)
        self.cli.write_text(FAKE)
        self.cli.chmod(0o755)
        self.home.mkdir()
        self.config.parent.mkdir()
        for patcher in (mock.patch.object(switcher.sys, 'platform', 'darwin'),
                        mock.patch.dict(os.environ)):
            patcher.start()
            self.addCleanup(patcher.stop)
        os.environ.pop('CODEX_BIN', None)
        self.attach('subscription')
        self.proofs = []

    def attach(self, mode):
        state = {'port': 4321, 'token': 'tok', 'openai_mode': mode}
        (self.home / 'mixed-router-state.json').write_text(json.dumps(state))
        block = blocks.build(self.home, state, mode, False, 'default')
        blocks._codex.write_receipt(self.home, self.config, block, None, mode, '')
        # Codex has since rewritten the owner's pick inside the block.
        self.live = blocks._codex._insert_root_lines(block, [PICK])
        self.config.write_text(self.live + '\nowner_setting = 1\n')

    def prove(self, answer=True):
        def prove(root):
            self.proofs.append((root, self.config.read_text()))
            return answer
        return prove

    def real_prove(self, **plan):
        """The shipped proof, asking a fake CLI inside the fake app."""
        os.environ.update(FAKE_RECORD=str(self.root / 'env.json'), FAKE_PLAN=json.dumps(plan))
        return lambda root: switcher._proof.prove(root, codex_home=self.root / 'home',
                                                  timeout=10)

    def fake(self, **kwargs):
        return FakeApp(self.app, **kwargs)

    def run_switch(self, app, answer=True, ready=True, prove=None):
        return switcher.switch(self.home, platform_ops=app, ready=lambda home: ready,
                               prove=prove or self.prove(answer))

    def assert_undone(self, before, app):
        """Back exactly as it was, the receipt now recording the live block."""
        self.assertEqual(self.config.read_text(), before)
        entry = blocks._codex.codex_attachment(self.home)
        self.assertEqual((entry['inserted_block'], entry.get('variant')), (self.live, None))
        self.assertFalse((self.home / switcher.MARKER).exists())
        if app is not None:
            self.assertEqual(app.calls[-1], ('open', 'com.openai.codex'))

    def test_round_trip_proves_only_switched_and_reopens_the_app(self):
        for want in ('switched', 'switched_back', 'switched'):
            with self.subTest(want=want):
                app, proofs = self.fake(), len(self.proofs)
                self.assertEqual(self.run_switch(app), want)
                self.assertEqual(app.calls, [('confirm', switcher.PROMPTS[want]),
                                             ('stop', 'com.openai.codex'),
                                             ('open', 'com.openai.codex')])
                self.assertEqual(len(self.proofs), proofs + (want == 'switched'))
                if want == 'switched':
                    self.assertEqual(self.proofs[-1][0], str(self.app))
                    self.assertIn('model_provider = "scg_router"', self.proofs[-1][1])
                self.assertIn(PICK, self.config.read_text())
                self.assertEqual(blocks.current(self.home), want)
                self.assertFalse((self.home / switcher.MARKER).exists())

    def test_cancel_quit_refusal_and_unknown_status_change_nothing(self):
        before = self.config.read_text(), (self.home / 'activation.json').read_text()
        app = self.fake(confirm=False)
        self.assertIsNone(self.run_switch(app))
        self.assertEqual([call[0] for call in app.calls], ['confirm'])
        for stops, message in ((False, switcher.STAYED_OPEN),
                               (OSError('status unknown'), switcher.FAILED)):
            with self.subTest(stops=stops):
                app = self.fake(stops=stops)
                with self.assertRaisesRegex(switcher.SwitchError, re.escape(message)):
                    self.run_switch(app)
                self.assertEqual([c[0] for c in app.calls].count('open'), stops is False)
        self.assertEqual((self.config.read_text(),
                          (self.home / 'activation.json').read_text()), before)
        self.assertEqual(self.proofs, [])

    def test_switched_refuses_any_doubt_before_asking(self):
        (self.app.parent / 'Old.app').mkdir()
        for app, ready, message in (
                (self.fake(), False, 'still checking'),
                (self.fake(identity=FileNotFoundError('not installed')), True, 'could not check'),
                (self.fake(identity=OSError('two copies')), True, 'could not check'),
                (FakeApp(self.app.parent / 'Old.app'), True, 'missing a bundled tool')):
            with self.subTest(message=message, identity=app.identity):
                with self.assertRaisesRegex(switcher.SwitchError, message):
                    self.run_switch(app, ready=ready)
                self.assertEqual(app.calls, [])
        self.attach('none')
        app = self.fake()
        with self.assertRaisesRegex(switcher.SwitchError, 'nothing to switch'):
            self.run_switch(app)
        self.assertEqual(app.calls, [])

    def test_switched_proof_objections_are_undone_and_the_app_reopened(self):
        for plan in ({'errors': ['configRequirements/read']},
                     {'requirements': {'modelProvider': 'openai'}}, {'exit': True}):
            with self.subTest(plan=plan):
                before, app = self.config.read_text(), self.fake()
                with self.assertRaisesRegex(switcher.SwitchError, 'nothing changed'):
                    self.run_switch(app, prove=self.real_prove(**plan))
                self.assert_undone(before, app)

    def test_the_way_back_needs_no_proof_and_no_app_it_can_find(self):
        for plan in ({'errors': ['configRequirements/read']},
                     {'requirements': {'modelProvider': 'openai'}}):
            with self.subTest(plan=plan):
                blocks.switch(self.home, 'switched')
                app = self.fake()
                self.assertEqual(self.run_switch(app, prove=self.real_prove(**plan)),
                                 'switched_back')
                self.assertEqual([call[0] for call in app.calls], ['confirm', 'stop', 'open'])
        for app in (self.fake(identity=OSError('two copies')),
                    self.fake(identity=FileNotFoundError('not installed')),
                    self.fake(stops=OSError('status unknown'))):
            with self.subTest(identity=app.identity, stops=app.stops):
                blocks.switch(self.home, 'switched')
                self.assertEqual(self.run_switch(app, answer=False), 'switched_back')
                asked = switcher.QUIT_FIRST if app.identity else switcher.PROMPTS['switched_back']
                self.assertEqual(app.calls[0], ('confirm', asked))
                self.assertNotIn('open', [call[0] for call in app.calls])
                self.assertEqual(app.calls[-1], ('notice', switcher.BACK_OPEN_AGAIN))
        # A quit that fails still refuses: the person can close the app and retry.
        blocks.switch(self.home, 'switched')
        with self.assertRaisesRegex(switcher.SwitchError, 'did not close'):
            self.run_switch(self.fake(stops=False))
        self.attach('none')
        blocks.switch(self.home, 'switched')
        self.assertEqual(self.run_switch(self.fake(), answer=False), 'switched_back')
        self.assertEqual(self.proofs, [])

    def test_hand_edits_refuse_before_asking_and_leave_no_marker(self):
        edited = self.config.read_text().replace('openai_base_url', 'openai_base_url_edited')
        self.config.write_text(edited)
        for attempt in range(2):
            app = self.fake()
            with self.assertRaisesRegex(switcher.SwitchError, 'changed by hand'):
                self.run_switch(app)
            self.assertEqual(app.calls, [])
            self.assertEqual(self.config.read_text(), edited)
            self.assertFalse((self.home / switcher.MARKER).exists())
        # A switch that refuses before writing anything needs no undo either.
        self.attach('subscription')
        (self.home / 'mixed-router-state.json').unlink()
        before, app = self.config.read_text(), self.fake()
        with self.assertRaisesRegex(switcher.SwitchError, re.escape(switcher.FAILED)):
            self.run_switch(app)
        self.assertEqual(self.config.read_text(), before)
        self.assertEqual(app.calls[-1], ('open', 'com.openai.codex'))
        self.assertFalse((self.home / switcher.MARKER).exists())

    def cut_short(self, after_writes):
        real = blocks.switch

        def switch(home, target):
            if after_writes:
                real(home, target)
            raise Interrupted()
        with mock.patch.object(blocks, 'switch', side_effect=switch):
            with self.assertRaises(Interrupted):
                self.run_switch(self.fake())
        self.assertTrue((self.home / switcher.MARKER).exists())

    def test_run_cut_short_is_kept_or_rolled_back_next_time(self):
        before = self.config.read_text()
        for after_writes, proves, want in ((False, True, 'default'), (True, False, 'default'),
                                           (True, True, 'switched')):
            with self.subTest(after_writes=after_writes, proves=proves):
                self.cut_short(after_writes)
                self.assertIsNone(self.run_switch(self.fake(confirm=False), answer=proves))
                self.assertEqual(blocks.current(self.home), want)
                if want == 'default':
                    self.assert_undone(before, None)
        # A way back cut short after its writes is kept without a proof; one cut
        # short before them is rolled back and offered again straight away.
        for after_writes, want in ((True, 'switched_back'), (False, 'switched')):
            with self.subTest(way_back=True, after_writes=after_writes):
                blocks.switch(self.home, 'switched')
                self.cut_short(after_writes)
                proofs, app = len(self.proofs), self.fake(confirm=False)
                self.assertIsNone(self.run_switch(app, answer=False))
                self.assertEqual((blocks.current(self.home), len(self.proofs)), (want, proofs))
                self.assertEqual(app.calls[0][1], switcher.PROMPTS[
                    'switched' if want == 'switched_back' else 'switched_back'])
        (self.home / switcher.MARKER).write_text('{')
        with self.assertRaisesRegex(switcher.SwitchError, 'could not be finished'):
            self.run_switch(self.fake())
        self.assertTrue((self.home / switcher.MARKER).exists())

    def test_busy_installer_and_other_platforms_refuse(self):
        with switcher._service.install_lock(self.home) as held:
            self.assertTrue(held)
            with self.assertRaisesRegex(switcher.SwitchError, 'updating'):
                self.run_switch(self.fake())
        with mock.patch.object(switcher.sys, 'platform', 'freebsd'):
            with self.assertRaisesRegex(switcher.SwitchError, 'on Mac'):
                self.run_switch(self.fake())

    def test_wording_is_plain_and_names_the_app(self):
        texts = list(switcher.PROMPTS.values()) + [
            value for name, value in vars(switcher).items()
            if name.isupper() and isinstance(value, str) and ' ' in value]
        for text in texts:
            with self.subTest(text=text):
                self.assertFalse([word for word in JARGON if word in text.lower()])
        for prompt in switcher.PROMPTS.values():
            self.assertIn('the ChatGPT app (Codex)', prompt)
            self.assertIn('restart', prompt)
        self.assertTrue(switcher.QUIT_FIRST.startswith('Quit the ChatGPT app (Codex) first'))

    def test_main_shows_the_refusal_and_hides_unexpected_errors(self):
        for error, shown in ((switcher.SwitchError('Plain words.'), 'Plain words.'),
                             (RuntimeError('/private/detail'), switcher.FAILED)):
            with self.subTest(shown=shown), \
                    mock.patch.object(switcher, 'switch', side_effect=error), \
                    mock.patch.object(platform, 'show_message') as show:
                self.assertEqual(switcher.main(['--home', str(self.home)]), 1)
                self.assertEqual(show.call_args.args[0], shown)


if __name__ == '__main__':
    unittest.main()
