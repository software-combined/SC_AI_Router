"""Feed serial anti-replay: release emits it, installer enforces it (Plan 047 A4)."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from tests._platform import unix_only
from tests.fakes import static_fetch as _static_fetch
from tests.test_install import _craft_bundle, _ok_run, _patch_attrs, install_mod
from tests.test_release import _release_mod


def _install_args(home, *extra):
    return install_mod.build_parser().parse_args(
        ['--feed', 'file:///latest.json', '--home', str(home), *extra])


def _home_with_serial(tmp, text='9\n'):
    home = Path(tmp) / 'home'
    home.mkdir(parents=True)
    (home / 'feed-serial').write_text(text)
    return home


@unix_only
class FeedSerialTests(unittest.TestCase):
    def test_release_emits_build_as_serial(self):
        release_mod = _release_mod()
        with tempfile.TemporaryDirectory() as tmp:
            release_mod.main(['--out', tmp, '--build', '41'])
            self.assertEqual(json.loads((Path(tmp) / 'latest.json').read_text())['serial'], 41)
            release_mod.main(['--out', tmp])
            self.assertEqual(json.loads((Path(tmp) / 'latest.json').read_text())['serial'], 0)

    def test_check_serial_accepts_fresh_equal_and_newer(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            self.assertEqual(install_mod.check_serial(home, {'serial': 0}), 0)
            home.mkdir(parents=True)
            (home / 'feed-serial').write_text('9\n')
            self.assertEqual(install_mod.check_serial(home, {'serial': 9}), 9)
            self.assertEqual(install_mod.check_serial(home, {'serial': 10}), 10)

    def test_check_serial_refuses_replay_legacy_and_bad_shapes(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = _home_with_serial(tmp)
            for latest in ({'serial': 7}, {}, {'serial': '9'}, {'serial': True}, {'serial': None}):
                with self.subTest(latest=latest), self.assertRaises(SystemExit):
                    install_mod.check_serial(home, latest)
            (home / 'feed-serial').write_text('oops\n')
            with self.assertRaises(SystemExit):
                install_mod.check_serial(home, {'serial': 9})

    def test_install_persists_serial_and_refuses_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            blob, latest = _craft_bundle('0.4.2.9')
            latest = {**latest, 'serial': 9}
            version = latest['version']
            _patch_attrs(self, health=lambda state, timeout=20: {'status': 'ok', 'version': version})
            env = {'HOME': str(Path(tmp) / 'fakehome'), 'OPENROUTER_API_KEY': 'test-key'}
            with mock.patch.dict(os.environ, env):
                self.assertEqual(
                    install_mod.do_install(_install_args(home), _fetch=_static_fetch(latest, blob),
                                           _run=_ok_run), 0)
            self.assertEqual((home / 'feed-serial').read_text(), '9\n')
            stale = {**latest, 'version': '9.9.9', 'serial': 7}
            with mock.patch.dict(os.environ, env), self.assertRaises(SystemExit):
                install_mod.do_install(_install_args(home), _fetch=_static_fetch(stale, blob),
                                       _run=_ok_run)

    def test_version_pin_bypasses_serial_gate(self):
        # --version restores an installed release without consulting the feed
        # or its serial: the old path unpacked the feed document as a bundle.
        with tempfile.TemporaryDirectory() as tmp:
            home = _home_with_serial(tmp)
            env = {'HOME': str(Path(tmp) / 'fakehome'), 'OPENROUTER_API_KEY': 'test-key'}
            for version, serial in (('0.4.2.0', 10), ('0.4.2.1', 11)):
                blob, latest = _craft_bundle(version)
                latest = {**latest, 'serial': serial}
                _patch_attrs(self, health=lambda state, timeout=20, version=version: {
                    'status': 'ok', 'version': version})
                with mock.patch.dict(os.environ, env):
                    self.assertEqual(
                        install_mod.do_install(
                            _install_args(home), _fetch=_static_fetch(latest, blob),
                            _run=_ok_run), 0)
            serial_before = (home / 'feed-serial').read_text()
            _patch_attrs(self, wait_version=lambda *args, **kwargs: True)

            def boom(url):
                raise AssertionError('rollback must not fetch anything')

            with mock.patch.dict(os.environ, env):
                self.assertEqual(
                    install_mod.do_install(_install_args(home, '--version', '0.4.2.0'),
                                           _fetch=boom, _run=_ok_run), 0)
            self.assertEqual((home / 'current').read_text(), '0.4.2.0\n')
            self.assertEqual((home / 'feed-serial').read_text(), serial_before)

    def test_check_update_refuses_stale_feed_before_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = _home_with_serial(tmp)
            blob, latest = _craft_bundle('9.9.9')
            stale = {**latest, 'serial': 7}
            args = install_mod.build_parser().parse_args(
                ['--check-update', '--feed', 'file:///latest.json', '--home', str(home)])
            stale_body = json.dumps(stale).encode()

            def fake_fetch(url):
                return blob

            with self.assertRaises(SystemExit) as ctx:
                install_mod.do_check_update(
                    args,
                    _fetch=fake_fetch,
                    _read_feed=lambda url, etag: (200, stale_body, None),
                    _sleep=lambda s: None)
            self.assertIn('stale feed serial', str(ctx.exception.code))


if __name__ == '__main__':
    unittest.main()
