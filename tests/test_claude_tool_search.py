"""The tool-search hard switch blocks an attach and fails the doctor.

Claude Code forces deferred MCP tool loading off whenever
`CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS` is truthy, and `ENABLE_TOOL_SEARCH`
cannot override it. An attach that shipped anyway would silently send every
MCP tool on every turn, so the installer refuses and the doctor reports the
file that carries it. Synthetic settings only; never the operator's own.
"""
import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.install_fixtures import install_mod

claude_config = install_mod._claude_config


def _state():
    return {'port': 1, 'token': 'test-token', 'openai_models': [],
            'claude_mode': 'subscription'}


class SwitchRefusalTests(unittest.TestCase):
    def _settings(self, tmp, env):
        path = Path(tmp) / 'settings.json'
        path.write_text(json.dumps({'env': env}))
        return path

    def test_a_set_hard_switch_refuses_the_attach(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._settings(tmp, {
                'CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS': '1'})
            with self.assertRaisesRegex(SystemExit,
                                        'forces deferred tool loading off'):
                claude_config.merge_env(Path(tmp), _state(), path, env={})
            self.assertNotIn('127.0.0.1', path.read_text())

    def test_a_switch_in_the_environment_refuses_the_attach(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._settings(tmp, {})
            with self.assertRaisesRegex(SystemExit, 'the environment'):
                claude_config.merge_env(
                    Path(tmp), _state(), path,
                    env={'CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS': '1'})

    def test_an_empty_or_zero_switch_does_not_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._settings(tmp, {
                'CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS': ''})
            doc, changed, _ = claude_config.merge_env(
                Path(tmp), _state(), path,
                env={'CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS': '0'})
            self.assertTrue(changed)
            self.assertEqual(doc['env']['ENABLE_TOOL_SEARCH'], 'true')


class SwitchDoctorTests(unittest.TestCase):
    def _home(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        home = tmp / 'home'
        release = home / 'releases' / '1.0.0' / 'packaging'
        release.mkdir(parents=True)
        (release / 'VERSION').write_text('1.0.0\n')
        (home / 'current').write_text('1.0.0\n')
        (home / 'mixed-router-state.json').write_text(
            json.dumps({'port': 1, 'token': 'x'}))
        install_mod._codex_config.write_client_receipt(home, 'claude', {
            'config_path': str(home / 'settings.json'),
            'inserted_block': '{}', 'claude_mode': 'subscription'})
        return home

    def test_doctor_fails_and_names_the_switch(self):
        home = self._home()
        (home / 'settings.json').write_text(json.dumps({'env': {
            'CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS': '1'}}))
        args = install_mod.build_parser().parse_args(
            ['--home', str(home), '--doctor', '--json'])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = install_mod.do_doctor(args)
        row = next(row for row in json.loads(buf.getvalue())['rows']
                   if row['check'] == 'claude')
        self.assertEqual(rc, 1)
        self.assertEqual(row['status'], 'FAIL')
        self.assertIn('CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS', row['detail'])
        self.assertIn('remove the variable', row['fix'])
