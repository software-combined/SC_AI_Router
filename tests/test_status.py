"""Plan 049 --status: read-only redacted diagnostics, install or not.

Never touches the network: health checks run through the injected seam,
and key validity is never probed. Asserts no secret-bearing value in
either output shape.
"""
import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from tests._platform import requires_posix_perms
from tests.install_fixtures import _patch_attrs, install_mod


class StatusTests(unittest.TestCase):
    def _args(self, home):
        return install_mod.build_parser().parse_args(
            ['--status', '--json', '--home', str(home)])

    def _home(self, **files):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        (home / 'releases' / '1.0.0').mkdir(parents=True)
        (home / 'current').write_text('1.0.0\n')
        (home / 'mixed-router-state.json').write_text(json.dumps(
            {'port': 1, 'token': 'test-token', 'openai_models': []}))
        for name, data in files.items():
            (home / name).write_text(data)
        return home

    def test_empty_home_reports_not_installed_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = install_mod.do_status(self._args(home))
            self.assertEqual(rc, 0)
            doc = json.loads(buf.getvalue())
            self.assertFalse(doc['installed'])
            self.assertIsNone(doc['version'])
            self.assertIsNone(doc['serving'])
            self.assertFalse(doc['key_present'])
            self.assertFalse(doc['key_usable'])
            self.assertEqual(doc['clients'], {})
            self.assertFalse(home.exists())

    def test_healthy_install_reports_redacted_status(self):
        home = self._home()
        (home / 'openrouter.key').write_text('sk-test\n')
        os.chmod(home / 'openrouter.key', 0o600)
        _patch_attrs(self, health=lambda state, timeout=20: {'status': 'ok', 'version': '1.0.0'})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = install_mod.do_status(self._args(home))
        self.assertEqual(rc, 0)
        doc = json.loads(buf.getvalue())
        self.assertTrue(doc['installed'])
        self.assertEqual(doc['version'], '1.0.0')
        self.assertTrue(doc['serving'])
        self.assertTrue(doc['key_present'])
        self.assertTrue(doc['key_usable'])
        blob = buf.getvalue()
        self.assertNotIn('test-token', blob)
        self.assertNotIn('sk-test', blob)

    @requires_posix_perms
    def test_group_readable_key_is_present_but_not_usable(self):
        home = self._home()
        (home / 'openrouter.key').write_text('sk-test\n')
        os.chmod(home / 'openrouter.key', 0o640)
        _patch_attrs(self, health=lambda state, timeout=20: None)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            install_mod.do_status(self._args(home))
        doc = json.loads(buf.getvalue())
        self.assertTrue(doc['key_present'])
        self.assertFalse(doc['key_usable'])
        self.assertFalse(doc['serving'])

    def test_human_shape_lists_clients_without_secrets(self):
        home = self._home()
        (home / 'activation.json').write_text(json.dumps(
            {'version': 2, 'clients': {'codex': {'config_path': str(home / 'config.toml'),
                                                'inserted_block': 'block'}}}))
        args = install_mod.build_parser().parse_args(['--status', '--home', str(home)])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = install_mod.do_status(args)
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn('clients: codex', out)
        self.assertIn('feed: cloudfront', out)
        self.assertIn('channel: stable', out)
        self.assertNotIn('block', out)


    def test_corrupt_receipt_reports_no_clients_with_rc_0(self):
        home = self._home()
        (home / 'activation.json').write_text('{truncated')
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = install_mod.do_status(self._args(home))
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(buf.getvalue())['clients'], {})

    def test_port_without_token_reports_not_serving_with_rc_0(self):
        home = self._home()
        (home / 'mixed-router-state.json').write_text(json.dumps({'port': 1}))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = install_mod.do_status(self._args(home))
        self.assertEqual(rc, 0)
        doc = json.loads(buf.getvalue())
        self.assertFalse(doc['serving'])

    @requires_posix_perms
    def test_shadowed_opencode_auth_is_not_usable(self):
        # A 0640 key file shadows opencode_auth at request time, so status
        # must not report usable on the auth file alone.
        home = self._home()
        (home / 'openrouter.key').write_text('sk-test\n')
        os.chmod(home / 'openrouter.key', 0o640)
        auth = home / 'auth.json'
        auth.write_text('{}')
        (home / 'mixed-router-state.json').write_text(json.dumps(
            {'port': 1, 'token': 't', 'openai_models': [], 'opencode_auth': str(auth)}))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            install_mod.do_status(self._args(home))
        doc = json.loads(buf.getvalue())
        self.assertTrue(doc['key_present'])
        self.assertFalse(doc['key_usable'])

    def test_opencode_without_openrouter_key_is_not_usable(self):
        home = self._home()
        auth = home / 'auth.json'
        auth.write_text(json.dumps({'other': {'type': 'api', 'key': 'x'}}))
        (home / 'mixed-router-state.json').write_text(json.dumps(
            {'port': 1, 'token': 't', 'openai_models': [], 'opencode_auth': str(auth)}))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            install_mod.do_status(self._args(home))
        doc = json.loads(buf.getvalue())
        self.assertFalse(doc['key_present'])
        self.assertFalse(doc['key_usable'])

    def test_blank_key_file_is_not_present_or_usable(self):
        home = self._home()
        (home / 'openrouter.key').write_text('\n')
        os.chmod(home / 'openrouter.key', 0o600)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            install_mod.do_status(self._args(home))
        doc = json.loads(buf.getvalue())
        self.assertFalse(doc['key_present'])
        self.assertFalse(doc['key_usable'])

if __name__ == '__main__':
    unittest.main()
