"""Plan 058 Stage 1: one preflight before anything is written.

Runs on every platform, so it lives outside the Unix-only install class.
"""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_install import _patch_attrs, install_mod


class PreflightTests(unittest.TestCase):
    def _args(self, *extra):
        return install_mod.build_parser().parse_args(
            ['--preflight', '--home', '/tmp/preflight-test-home', *extra])

    def test_preflight_passes_with_all_prerequisites(self):
        _patch_attrs(self, find_python=lambda explicit=None: '/usr/bin/python3.14')
        with mock.patch.object(install_mod.shutil, 'which', return_value='/usr/bin/x'):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = install_mod.do_preflight(self._args())
        self.assertEqual(rc, 0)
        self.assertIn('Python, feed-route, and client prerequisites present', buf.getvalue())

    def test_preflight_reports_everything_missing_together(self):
        _patch_attrs(self, find_python=lambda explicit=None: None)
        diag_feed = install_mod._diag._svc._feed
        with mock.patch.object(install_mod.shutil, 'which', return_value=None), \
                mock.patch.object(diag_feed, 'gh_candidates', return_value=()):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                with self.assertRaisesRegex(SystemExit, '2'):
                    install_mod.do_preflight(self._args())
        out = buf.getvalue()
        self.assertIn('no Python 3.14 found', out)
        self.assertIn('GitHub CLI (gh) binary not found', out)
        self.assertIn('Codex CLI not found', out)

    def test_preflight_explicit_feed_skips_gh_requirement(self):
        _patch_attrs(self, find_python=lambda explicit=None: '/usr/bin/python3.14')
        with mock.patch.object(install_mod.shutil, 'which',
                               side_effect=lambda name: None if name == 'gh' else '/usr/bin/x'):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = install_mod.do_preflight(
                    self._args('--feed', 'file:///bundle.tar.gz'))
        self.assertEqual(rc, 0)

    def test_preflight_service_only_skips_codex_requirement(self):
        _patch_attrs(self, find_python=lambda explicit=None: '/usr/bin/python3.14')
        with mock.patch.object(install_mod.shutil, 'which',
                               side_effect=lambda name: None if name == 'codex' else '/usr/bin/x'):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = install_mod.do_preflight(self._args('--client', 'none'))
        self.assertEqual(rc, 0)

    def test_preflight_through_main_creates_no_home(self):
        _patch_attrs(self, find_python=lambda explicit=None: '/usr/bin/python3.14')
        with mock.patch.object(install_mod.shutil, 'which', return_value='/usr/bin/x'):
            with tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp) / 'home'
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = install_mod.main(['--preflight', '--home', str(home)])
                self.assertEqual(rc, 0)
                self.assertFalse(home.exists())



if __name__ == '__main__':
    unittest.main()
