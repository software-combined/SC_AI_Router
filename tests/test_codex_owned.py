"""Receipt-owned Codex edits tolerate client formatting, never foreign routes."""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from tests.install_fixtures import install_mod


class CodexOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / 'router'
        self.home.mkdir()
        self.config = self.root / 'user/.codex/config.toml'
        self.config.parent.mkdir(parents=True)
        self.owner = install_mod._codex_config
        self.block = self.owner.build_block(
            self.home, {'port': 4321, 'token': 'synthetic-route'}, 'subscription')
        self.entry = {'config_path': str(self.config), 'inserted_block': self.block,
                      'openai_mode': 'subscription'}
        self.config.write_text(self.block + '\n[features]\nexample = true\n')

    def drift(self, extra=''):
        text = self.config.read_text().replace('openai_base_url = ', 'openai_base_url=')
        text = text.replace(self.owner.END, '# keep this note\n' + extra + self.owner.END)
        self.config.write_text(text)
        return text

    def test_spacing_and_comments_are_owned_but_foreign_url_is_not(self):
        text = self.drift()
        self.assertIn(self.owner.live_block(text, self.block), text)
        foreign = text.replace('127.0.0.1:4321', '127.0.0.1:9876')
        self.assertNotIn(self.owner.live_block(foreign, self.block), foreign)

    def test_update_preserves_added_root_setting_and_comment(self):
        self.drift('person_setting = "keep me"\n')
        with contextlib.redirect_stdout(io.StringIO()):
            block, _, _, _ = self.owner.attach_config(self.config, self.block, self.entry)
        after = self.config.read_text()
        self.assertEqual(tomllib.loads(after)['person_setting'], 'keep me')
        self.assertIn('# keep this note', after)
        self.assertNotIn('person_setting', block)
        self.assertTrue(tomllib.loads(after)['features']['example'])

    def test_removal_plan_preserves_user_data_and_has_no_side_effects(self):
        before = self.drift('person_setting = "keep me"\n')
        old, after = self.owner.removal_plan(self.config, self.entry)
        self.assertEqual(old, before)
        self.assertEqual(self.config.read_text(), before)
        self.assertNotIn('openai_base_url', after)
        self.assertNotIn(self.owner.BEGIN, after)
        self.assertIn('# keep this note', after)
        self.assertEqual(tomllib.loads(after),
                         {'person_setting': 'keep me', 'features': {'example': True}})

    def test_duplicate_route_key_or_markers_refuse_without_writes(self):
        for extra in ('openai_base_url = "foreign"\n', self.owner.BEGIN + '\n'):
            with self.subTest(extra=extra):
                text = self.block.replace(self.owner.END, extra + self.owner.END)
                self.config.write_text(text)
                with self.assertRaises(SystemExit):
                    self.owner.removal_plan(self.config, self.entry)
                self.assertEqual(self.config.read_text(), text)

    def test_multiline_user_value_inside_region_refuses_without_writes(self):
        before = self.drift('person_setting = [\n "keep me",\n]\n')
        with self.assertRaises(SystemExit):
            self.owner.removal_plan(self.config, self.entry)
        self.assertEqual(self.config.read_text(), before)

    def test_remover_ignores_stale_temp_and_preserves_symlink(self):
        before = self.drift('person_setting = "keep me"\n')
        target = self.config.with_name('owned-target.toml')
        self.config.rename(target)
        try:
            self.config.symlink_to(target.name)
        except OSError:
            self.skipTest('symlinks unavailable')
        self.config.with_name('config.toml.mixed-router-restore').write_text('old interrupted write')
        (self.home / 'activation.json').write_text(json.dumps(
            {'version': 2, 'clients': {'codex': self.entry}}))
        command = Path(__file__).resolve().parents[1] / 'tools/disable.py'
        result = subprocess.run([sys.executable, str(command)], capture_output=True,
                                text=True, env=dict(os.environ, ROUTER_HOME=str(self.home),
                                ROUTER_RESTORE_ONLY='1', HOME=str(self.root / 'user')))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.config.is_symlink())
        self.assertNotEqual(target.read_text(), before)
        self.assertEqual(tomllib.loads(target.read_text())['person_setting'], 'keep me')

    def test_parser_bridge_uses_stdin_and_returns_no_values(self):
        owned = self.owner._owned
        real_run = subprocess.run
        seen = []

        def bridge(command, **kwargs):
            seen.append((command, kwargs))
            return real_run(command, **kwargs)

        with mock.patch.object(owned, 'run', bridge), \
                mock.patch.object(owned, 'HAS_TOML', False), \
                mock.patch.object(owned, 'parser_python', return_value=sys.executable):
            live = self.owner.live_block(self.drift(), self.block)
        self.assertIn(live, self.config.read_text())
        self.assertNotIn('synthetic-route', ' '.join(seen[0][0]))
        self.assertIn('synthetic-route', seen[0][1]['input'])

    def test_an_added_setting_is_not_silently_claimed_by_a_new_block(self):
        before = self.drift('model_catalog_json = "my-models.json"\n')
        new = self.block.replace(self.owner.END,
                                 'model_catalog_json = "router-models.json"\n' + self.owner.END)
        with self.assertRaises(SystemExit):
            self.owner.attach_config(self.config, new, self.entry)
        self.assertEqual(self.config.read_text(), before)

    def test_compare_before_write_does_not_overwrite_a_concurrent_edit(self):
        before, after = self.owner.removal_plan(self.config, self.entry)
        changed = before + '# saved by another writer\n'
        self.config.write_text(changed)
        writer = mock.Mock()
        with self.assertRaisesRegex(SystemExit, 'concurrently'):
            self.owner._owned.write(self.config, before, after, writer)
        writer.assert_not_called()
        self.assertEqual(self.config.read_text(), changed)

    def test_crlf_removal_keeps_unrelated_text_bytes(self):
        before = self.block.replace('\n', '\r\n') + '\r\n[features]\r\nexample = true\r\n'
        self.config.write_bytes(before.encode())
        old, after = self.owner.removal_plan(self.config, self.entry)
        self.assertEqual(old, before)
        self.assertEqual(after, '\r\n[features]\r\nexample = true\r\n')

    def test_an_edit_during_validation_is_not_overwritten(self):
        before, after = self.owner.removal_plan(self.config, self.entry)
        changed = before + '# another writer during verification\n'
        writer = mock.Mock()
        with mock.patch.object(self.owner._owned, 'inspect',
                               side_effect=lambda *_: self.config.write_text(changed)):
            with self.assertRaisesRegex(SystemExit, 'concurrently'):
                self.owner._owned.write(self.config, before, after, writer)
        writer.assert_not_called()
        self.assertEqual(self.config.read_text(), changed)

    def test_python39_attach_uses_the_installers_explicit_runtime(self):
        from tests.test_install_config import _install
        owned = self.owner._owned
        with mock.patch.object(install_mod, 'find_python', return_value=sys.executable), \
                mock.patch.object(owned, 'HAS_TOML', False), \
                mock.patch.object(owned.shutil, 'which', return_value=None):
            config, _, _, _ = _install(self, self.root, self.home, '1.0.0',
                                      '--python', sys.executable)
        self.assertIn('openai_base_url', tomllib.loads(config.read_text()))

    def test_failed_switch_preserves_symlink_and_restores_its_target(self):
        from tests.test_codex_switch_config import switch
        target = self.config.with_name('dotfile.toml')
        self.config.rename(target)
        try:
            self.config.symlink_to(target.name)
        except OSError:
            self.skipTest('symlinks unavailable')
        before = target.read_bytes()
        (self.home / 'mixed-router-state.json').write_text(json.dumps(
            {'port': 4321, 'token': 'synthetic-route'}))
        switch._codex.write_client_receipt(self.home, 'codex', self.entry)
        with mock.patch.object(switch._codex, 'write_client_receipt',
                               side_effect=OSError('receipt unavailable')):
            with self.assertRaises(OSError):
                switch.switch(self.home, 'switched')
        self.assertTrue(self.config.is_symlink())
        self.assertEqual(target.read_bytes(), before)

    def test_failed_proof_restore_preserves_symlink_and_displaced_setting(self):
        from tests.test_codex_switch_config import switch
        before = self.config.read_text() + '\n'
        before = before.replace('[features]', 'model_provider = "ollama"\n[features]')
        target = self.config.with_name('dotfile.toml')
        target.write_text(before)
        self.config.unlink()
        try:
            self.config.symlink_to(target.name)
        except OSError:
            self.skipTest('symlinks unavailable')
        (self.home / 'mixed-router-state.json').write_text(json.dumps(
            {'port': 4321, 'token': 'synthetic-route'}))
        switch._codex.write_client_receipt(self.home, 'codex', self.entry)
        switch.switch(self.home, 'switched')
        self.config.write_text(self.config.read_text().replace(
            self.owner.END, 'person_setting = "keep me"\n' + self.owner.END))
        switch.restore(self.home, self.entry, 'switched')
        self.assertTrue(self.config.is_symlink())
        self.assertEqual(tomllib.loads(target.read_text())['model_provider'], 'ollama')
        self.assertEqual(tomllib.loads(target.read_text())['person_setting'], 'keep me')
        self.assertIn('[features]\nexample = true', target.read_text())

    def test_removal_uses_explicit_runtime_when_caller_is_python39(self):
        runtime = sys.executable
        calls = []
        def invoke(command, **kwargs):
            calls.append(command)
            return subprocess.run(command, **kwargs)
        (self.home / 'activation.json').write_text(json.dumps(
            {'version': 2, 'clients': {'codex': self.entry}}))
        release = self.home / 'releases/1.0.0'
        release.mkdir(parents=True)
        (release / 'packaging').mkdir()
        (release / 'packaging/VERSION').write_text('1.0.0')
        (self.home / 'current').write_text('1.0.0')
        args = install_mod.build_parser().parse_args(
            ['--home', str(self.home), '--python', runtime])
        with mock.patch.object(install_mod, 'find_python', return_value=runtime), \
                mock.patch.object(install_mod.sys, 'executable', '/missing/python3.9'), \
                mock.patch.object(install_mod, 'run', invoke), \
                mock.patch.object(install_mod._svc, 'run', invoke), \
                mock.patch.object(install_mod, 'platform_backend', return_value=mock.Mock()), \
                mock.patch.object(install_mod._delivery, '_load', return_value=mock.Mock()), \
                mock.patch.dict(os.environ, HOME=str(self.root / 'user'), PATH='/usr/bin:/bin'), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(install_mod.do_uninstall(args), 0)
            self.config.write_text(self.block)
            (self.home / 'activation.json').write_text(json.dumps(
                {'version': 2, 'clients': {'codex': self.entry}}))
            install_mod._restore_owned_config(self.home, runtime)
        self.assertEqual([command[0] for command in calls], [runtime, runtime])
        self.assertNotIn('openai_base_url', tomllib.loads(self.config.read_text()))

    def test_an_unrecorded_routing_key_is_a_connection_conflict(self):
        before = self.drift('model_provider = "another-provider"\n')
        with self.assertRaises(SystemExit):
            self.owner.removal_plan(self.config, self.entry)
        self.assertEqual(self.config.read_text(), before)

    def test_markers_inside_a_multiline_literal_do_not_prove_ownership(self):
        before = "person_note = '''\n" + self.block + "'''\n"
        self.config.write_text(before)
        with self.assertRaises(SystemExit):
            self.owner.removal_plan(self.config, self.entry)
        self.assertEqual(self.config.read_text(), before)

    def test_failed_desktop_proof_then_update_does_not_claim_user_settings(self):
        from tests.test_codex_desktop_switch import switcher
        blocks = switcher._blocks
        entry = dict(self.entry, inserted_block=self.owner._insert_root_lines(
            self.block, ['model = "old-choice"']))
        self.config.write_text(self.owner._insert_root_lines(
            self.block, ['model = "new-choice"', 'person_setting = "keep me"']))
        (self.home / 'mixed-router-state.json').write_text(json.dumps(
            {'port': 4321, 'token': 'synthetic-route'}))
        blocks._codex.write_client_receipt(self.home, 'codex', entry)
        with self.assertRaises(switcher.SwitchError):
            switcher._apply(self.home, entry, 'switched', lambda _: False, None)
        restored = blocks._codex.codex_attachment(self.home)
        self.assertNotIn('person_setting', restored['inserted_block'])
        blocks._codex.attach_config(self.config, self.block, restored)
        self.assertEqual(tomllib.loads(self.config.read_text())['person_setting'], 'keep me')
        self.assertEqual(tomllib.loads(self.config.read_text())['model'], 'new-choice')

    def test_alternate_desktop_values_stay_valid_and_preserved(self):
        for line in ('desktop = { appearanceTheme = "dark" }\n',
                     'desktop.appearanceTheme = "dark"\n',
                     '"desktop" . appearanceTheme = "dark"\n'):
            with self.subTest(line=line), contextlib.redirect_stdout(io.StringIO()):
                self.config.write_text(self.block.replace(self.owner.END, line + self.owner.END))
                prior = {'written': {self.owner.QUEUE_KEY: 'steer'},
                         'previous': {self.owner.QUEUE_KEY: 'queue'}}
                entry = dict(self.entry, desktop=prior)
                result = self.owner.attach_config(self.config, self.block, entry)
                self.assertEqual(tomllib.loads(self.config.read_text())['desktop'],
                                 {'appearanceTheme': 'dark'})
                self.assertEqual(result[2], prior)


if __name__ == '__main__':
    unittest.main()
