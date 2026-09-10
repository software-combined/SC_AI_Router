"""Plan 041 installer tests. install.py imports cleanly as a module."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from codex_router import feed_verify
from tests.fakes import LAUNCHD, static_fetch as _static_fetch

_ROOT = Path(__file__).resolve().parents[1]


def _real_bundle(tmp):
    """Build a real release bundle via packaging/release.py (slow; ~3s)."""
    feeddir = Path(tmp) / 'feed'
    feeddir.mkdir()
    spec = importlib.util.spec_from_file_location(
        'router_release', _ROOT / 'packaging' / 'release.py')
    release_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(release_mod)
    release_mod.main(['--out', str(feeddir)])
    tarball = next(iter(feeddir.glob('*.tar.gz')))
    blob = tarball.read_bytes()
    with tarfile.open(tarball, mode='r') as tar:
        manifest = json.loads(tar.extractfile('MANIFEST.json').read())
    return manifest['version'], _static_fetch(
        {'version': manifest['version'], 'url': 'file:///bundle.tar.gz',
         'sha256': hashlib.sha256(blob).hexdigest(), 'min_python': '3.14'}, blob), blob, manifest


def _install_mod():
    spec = importlib.util.spec_from_file_location('router_install', _ROOT / 'packaging' / 'install.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # This existing rig exercises launchd on every host. Linux lifecycle
    # tests explicitly select linux and use the same installer seams.
    module.PLATFORM = 'darwin'
    return module


install_mod = _install_mod()


def _tarball(files=(), links=()):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w') as tar:
        for name, data in files:
            raw = data if isinstance(data, bytes) else data.encode()
            info = tarfile.TarInfo(name)
            info.size = len(raw)
            tar.addfile(info, io.BytesIO(raw))
        for name, target in links:
            info = tarfile.TarInfo(name)
            info.type = tarfile.SYMTYPE
            info.linkname = target
            tar.addfile(info)
    return buf.getvalue()


def _ok_run(cmd, **kwargs):
    if '-c' in cmd:
        return SimpleNamespace(returncode=0, stdout='3 14\n/opt/homebrew/bin/python3.14\n',
                               stderr='')
    # launchctl goes through the stateful domain model: a fake that answered
    # `print` with rc 0 for a booted-out label is what let the bootout/bootstrap
    # defect reach a release.
    answer = LAUNCHD(cmd, **kwargs)
    if answer is not None:
        return answer
    return SimpleNamespace(returncode=0, stdout='', stderr='')


def _craft_bundle(version):
    """Crafted install bundle + feed doc (bytes only, no release build)."""
    from tests.fakes import install_payloads
    files = install_payloads(version)
    manifest = {'version': version, 'files':
                {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
    blob = _tarball(files=[('MANIFEST.json', json.dumps(manifest)), *files.items()])
    latest = {'version': version, 'url': 'file:///bundle.tar.gz',
              'sha256': None, 'min_python': '3.14'}
    return blob, latest


_SEAMS = ('run', 'health', 'wait_version', 'self_test',
           'write_catalogue', 'fetch_feed', 'feed_serial')
# webbrowser patches module-global stdlib handle via setattr on install_mod;
# call sites use `webbrowser.open` so plain setattr suffices (no _svc mirror).


def _patch_attrs(test, **overrides):
    test.addCleanup(LAUNCHD.reset)
    LAUNCHD.reset()
    # Real launchd settle windows are minutes long; tests must never wait on
    # wall-clock time, and must never fall back to a real time.sleep.
    for mod in (install_mod, install_mod._svc):
        for name, value in (('UNLOAD_TIMEOUT_S', 2), ('LOAD_TIMEOUT_S', 2),
                            ('_sleep', lambda *_a, **_k: None)):
            if hasattr(mod, name):
                test.addCleanup(setattr, mod, name, getattr(mod, name))
                setattr(mod, name, value)
    for name, value in overrides.items():
        if name == 'webbrowser':
            # Module-global stdlib handle; call sites use webbrowser.open.
            test.addCleanup(setattr, install_mod, name, getattr(install_mod, name))
            setattr(install_mod, name, value)
            continue
        if name not in _SEAMS and not hasattr(install_mod, name):
            raise AttributeError(f'unknown installer seam: {name}')
        test.addCleanup(setattr, install_mod, name, getattr(install_mod, name))
        setattr(install_mod, name, value)
        # Call sites sync from install_mod._svc on entry; mirror there too.
        if hasattr(install_mod._svc, name):
            test.addCleanup(setattr, install_mod._svc, name,
                            getattr(install_mod._svc, name))
            setattr(install_mod._svc, name, value)


def _run_install(test, tmp, home, fake_fetch, fake_run):
    args = install_mod.build_parser().parse_args(
        ['--feed', 'file:///latest.json', '--home', str(home)])
    env = {'HOME': str(Path(tmp) / 'fakehome'), 'OPENROUTER_API_KEY': 'test-key'}
    with mock.patch.dict(os.environ, env):
        test.assertEqual(
            install_mod.do_install(args, _fetch=fake_fetch, _run=fake_run), 0)
    return args, env

class PlatformRefusalTests(unittest.TestCase):
    # Unskipped on purpose: unknown platforms must refuse before any
    # router home exists, while win32 routes to the Windows backend.
    # No launchd, systemctl, getuid, or permission-bit surface here.
    def _patched_home(self, platform):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        previous, install_mod.PLATFORM = install_mod.PLATFORM, platform
        self.addCleanup(setattr, install_mod, 'PLATFORM', previous)
        return Path(tmp.name) / 'home'

    def test_unsupported_platform_refuses_before_any_router_home(self):
        home = self._patched_home('plan9')
        with self.assertRaisesRegex(SystemExit, 'not supported'):
            install_mod.main(['--feed', 'file:///latest.json', '--home', str(home)])
        self.assertFalse(home.exists())

    def test_status_runs_read_only_on_unsupported_platform(self):
        home = self._patched_home('plan9')
        with contextlib.redirect_stdout(buf := io.StringIO()):
            rc = install_mod.main(['--status', '--json', '--home', str(home)])
        self.assertEqual(rc, 0)
        self.assertFalse(json.loads(buf.getvalue())['installed'])
        self.assertFalse(home.exists())

    def test_win32_selects_the_windows_backend(self):
        self._patched_home('win32')
        install_mod.require_supported_platform()
        self.assertEqual(install_mod.platform_backend().name, 'windows')


@unittest.skipIf(os.name == 'nt', 'Unix-only install/service layer')
class InstallTests(unittest.TestCase):
    def test_checksum_mismatch_is_rejected(self):
        with self.assertRaises(SystemExit):
            install_mod.verify_sha256(b'bundle-bytes', '0' * 64)
        want = hashlib.sha256(b'bundle-bytes').hexdigest()
        self.assertTrue(install_mod.verify_sha256(b'bundle-bytes', want))

    def test_extract_rejects_traversal_and_links(self):
        cases = {'traversal': _tarball(files=[('../evil', 'x')]),
                 'absolute': _tarball(files=[('/tmp/evil', 'x')]),
                 'symlink': _tarball(files=[('ok', 'x')], links=[('link', 'ok')])}
        for name, blob in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(SystemExit):
                    install_mod.safe_extract(blob, tmp)

    def test_manifest_mismatch_deletes_partial_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            blob = _tarball(files=[('packaging/VERSION', '9.9.9\n')])
            manifest = {'files': {'packaging/VERSION': '0' * 64}}
            with self.assertRaises(SystemExit):
                install_mod.install_bundle(home, '9.9.9', blob, manifest, '/nonexistent/python')
            self.assertFalse((home / 'releases' / '9.9.9.partial').exists())

    def test_newer_compares_tuples(self):
        self.assertTrue(install_mod.newer('0.10.0', '0.9.9'))
        self.assertTrue(install_mod.newer('0.4.0', '0.3.0'))
        self.assertFalse(install_mod.newer('0.3.0', '0.3.0'))
        self.assertFalse(install_mod.newer('0.3.0', '0.4.0'))

    def test_render_plist_contains_label_home_and_python(self):
        content = install_mod.render_plist(
            '/opt/homebrew/bin/python3.14', Path('/tmp/hm'), {'port': 18749})
        self.assertEqual(content['Label'], 'com.local.codex-mixed-model-router')
        self.assertEqual(content['ProgramArguments'],
                         ['/opt/homebrew/bin/python3.14', '/tmp/hm/router_launch.py'])
        self.assertNotIn('WorkingDirectory', content)
        self.assertEqual(content['EnvironmentVariables'], {'ROUTER_HOME': '/tmp/hm'})
        self.assertTrue(content['KeepAlive'] and content['RunAtLoad'])
        self.assertNotIn('token', json.dumps(content))
        listeners = content['Sockets']['Listeners']
        self.assertEqual(listeners['SockNodeName'], '127.0.0.1')
        self.assertEqual(listeners['SockServiceName'], '18749')
        self.assertEqual(listeners['SockFamily'], 'IPv4')
        self.assertEqual(listeners['SockType'], 'stream')

    def test_swap_current_is_atomic_and_rollback_restores_previous(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            first, second = home / 'releases' / '0.2.0', home / 'releases' / '0.3.0'
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            self.assertIsNone(install_mod.swap_current(home, first))
            self.assertEqual((home / 'current').read_text(), '0.2.0\n')
            self.assertFalse((home / 'current').is_symlink())
            previous = install_mod.swap_current(home, second)
            self.assertEqual(previous, '0.2.0')
            install_mod.swap_current(home, home / 'releases' / previous)
            self.assertEqual((home / 'current').read_text(), '0.2.0\n')

    def test_replace_config_block_preserves_unrelated_lines_and_refuses_double_markers(self):
        block = ('# BEGIN local mixed model picker\nopenai_base_url = "http://x"\n'
                 '# END local mixed model picker\n')
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'config.toml'
            config.write_text('other = 1\n')
            install_mod.replace_config_block(config, block)
            self.assertTrue(config.read_text().startswith(block))
            self.assertIn('other = 1', config.read_text())
            self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o600)
            install_mod.replace_config_block(config, block, block)
            self.assertEqual(config.read_text().count(block), 1)
            config.write_text(block + 'middle = 2\n' + block)
            with self.assertRaises(SystemExit):
                install_mod.replace_config_block(config, block, block)

    def test_install_dry_run_performs_no_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            latest = {'version': '9.9.9', 'url': 'file:///bundle.tar.gz',
                      'sha256': None, 'min_python': '3.14'}
            args = install_mod.build_parser().parse_args(
                ['--feed', 'file:///latest.json', '--home', str(home), '--dry-run'])
            rc = install_mod.do_install(args, _fetch=_static_fetch(latest, b''))
            self.assertEqual(rc, 0)
            self.assertFalse(home.exists())

    def test_health_failure_triggers_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            prev = home / 'releases' / '0.2.0'
            (prev / 'packaging').mkdir(parents=True)
            (prev / 'packaging' / 'VERSION').write_text('0.2.0\n')
            home.mkdir(parents=True, exist_ok=True)
            os.symlink(str(prev), home / 'current')
            blob, latest = _craft_bundle('9.9.9')
            fake_fetch = _static_fetch(latest, blob)

            calls = []

            def fake_run(cmd, **kwargs):
                calls.append(cmd)
                return _ok_run(cmd, **kwargs)

            _patch_attrs(self, run=fake_run,
                         self_test=lambda *args: None,
                         health=lambda state, timeout=20: None,
                         wait_version=lambda *args, **kwargs: None)

            args = install_mod.build_parser().parse_args(
                ['--feed', 'file:///latest.json', '--home', str(home)])
            env = {'HOME': tmp, 'OPENROUTER_API_KEY': 'test-key'}
            with mock.patch.dict(os.environ, env):
                with self.assertRaises(SystemExit) as ctx:
                    install_mod.do_install(args, _fetch=fake_fetch, _run=fake_run)
            self.assertEqual(ctx.exception.code, 1)
            self.assertEqual((home / 'current').read_text(), '0.2.0\n')
            self.assertTrue(any('kill' in cmd for cmd in calls))


    def test_replace_config_block_truncates_shorter_replacement(self):
        long_block = ('# BEGIN local mixed model picker\n'
                      'openai_base_url = "http://127.0.0.1:18749/%s/backend-api/codex"\n'
                      '# END local mixed model picker\n' % ('t' * 200))
        short_block = ('# BEGIN local mixed model picker\n'
                       'openai_base_url = "http://x/"\n'
                       '# END local mixed model picker\n')
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'config.toml'
            config.write_text('other = 1\n' + long_block)
            install_mod.replace_config_block(config, short_block, long_block)
            self.assertEqual(config.read_bytes(), ('other = 1\n' + short_block).encode())
            self.assertEqual(config.read_text().count('# BEGIN local mixed model picker'), 1)

    def test_self_test_passes_on_extracted_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            version, _, blob, manifest = _real_bundle(tmp)
            extract = Path(tmp) / 'extracted'
            extract.mkdir()
            with tarfile.open(Path(tmp) / 'feed' / f'codex-model-router-{version}.tar.gz',
                              mode='r') as tar:
                tar.extractall(extract, filter='data')
            install_mod.self_test(sys.executable, extract)
            want = manifest['version']
            proc = subprocess.run(
                [sys.executable, '-c', 'from codex_router.runtime import VERSION; print(VERSION)'],
                cwd=str(extract), capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout.strip(), want)

    def test_fresh_install_writes_plists_before_first_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            version, fake_fetch, blob, _manifest = _real_bundle(tmp)
            latest = {'version': version, 'url': 'file:///bundle.tar.gz',
                      'sha256': hashlib.sha256(blob).hexdigest(), 'min_python': '3.14'}

            fake_fetch = _static_fetch(latest, blob)

            agents = Path(tmp) / 'fakehome' / 'Library' / 'LaunchAgents'
            plist = agents / 'com.local.codex-mixed-model-router.plist'
            order = []

            def fake_run(cmd, **kwargs):
                order.append((list(cmd), plist.exists()))
                return _ok_run(cmd, **kwargs)

            _patch_attrs(self, health=lambda state, timeout=20: {'status': 'ok', 'version': version})
            _run_install(self, tmp, home, fake_fetch, fake_run)
            bootstraps = [saw for cmd, saw in order if 'bootstrap' in cmd]
            self.assertTrue(bootstraps, 'service was never restarted')
            self.assertTrue(all(bootstraps), 'restart ran before plists were written')
            self.assertEqual((home / 'current').read_text(), version + '\n')


    def test_recheck_reports_up_to_date_after_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            version, _, blob, _manifest = _real_bundle(tmp)
            latest = {'version': version, 'url': 'file:///bundle.tar.gz',
                      'sha256': hashlib.sha256(blob).hexdigest(), 'min_python': '3.14'}

            fake_fetch = _static_fetch(latest, blob)

            _patch_attrs(self, health=lambda state, timeout=20: {'status': 'ok', 'version': version})
            calls = []

            def fake_run(cmd, **kwargs):
                calls.append(list(cmd))
                return _ok_run(cmd, **kwargs)

            args, env = _run_install(self, tmp, home, fake_fetch, fake_run)
            self.assertEqual(install_mod.current_version(home), version)
            n_bootstraps = sum(1 for cmd in calls if 'bootstrap' in cmd)
            with mock.patch.dict(os.environ, env):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = install_mod.do_check_update(
                        args, _fetch=fake_fetch, _sleep=lambda s: None)
            self.assertEqual(rc, 0)
            self.assertIn('up to date', buf.getvalue())
            self.assertEqual(sum(1 for cmd in calls if 'bootstrap' in cmd), n_bootstraps)


    def test_check_update_uses_etag_and_treats_304_as_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            (home / 'update-etag').write_text('old-etag\n')
            seen = []

            def fake_read(feed, etag):
                seen.append((feed, etag))
                return 304, b'', 'old-etag'

            def boom(url):
                raise AssertionError('tarball must not download on 304')

            args = install_mod.build_parser().parse_args(
                ['--feed', 'file:///latest.json', '--home', str(home)])
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = install_mod.do_check_update(
                    args, _fetch=boom, _read_feed=fake_read, _sleep=lambda s: None)
            self.assertEqual(rc, 0)
            self.assertIn('up to date', buf.getvalue())
            self.assertEqual(seen, [('file:///latest.json', 'old-etag')])
            self.assertEqual((home / 'update-etag').read_text(), 'old-etag\n')

    def test_channel_beta_uses_origin_without_api_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            self.assertEqual(install_mod.channel_feed(home), install_mod.FEED_URL)
            (home / 'channel').write_text('beta\n')
            self.assertEqual(install_mod.channel_feed(home),
                             'https://github.com/beta/latest.json')
            self.assertEqual(
                feed_verify.beta_feed_url('file:///stable/latest.json'),
                'file:///beta/latest.json')
            with self.assertRaises(SystemExit):
                feed_verify.beta_feed_url('not-a-url')

    def test_jitter_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            sleeps = []
            args = install_mod.build_parser().parse_args(
                ['--feed', 'file:///latest.json', '--home', str(home)])
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                install_mod.do_check_update(
                    args,
                    _read_feed=lambda feed, etag: (304, b'', None),
                    _sleep=sleeps.append)
            self.assertEqual(len(sleeps), 1)
            self.assertGreaterEqual(sleeps[0], 0)
            self.assertLessEqual(sleeps[0], 120)

    def test_update_plist_checks_every_fifteen_minutes(self):
        content = install_mod.render_update_plist('/opt/homebrew/bin/python3.14', Path('/tmp/hm'))
        self.assertEqual(content['StartInterval'], 900)
        self.assertTrue(content['RunAtLoad'])
        self.assertNotIn('StartCalendarInterval', content)

    def test_deferred_check_keeps_old_etag(self):
        # Retaining the old ETag is what makes the next poll re-read the feed.
        # There is no busy gate any more, so the deferral under test is the
        # one that remains: the child installer ran and did not activate the
        # requested version.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            (home / 'update-etag').write_text('etag-A\n')
            (home / 'mixed-router-state.json').write_text(
                json.dumps({'port': 1, 'token': 'x'}))
            blob, latest = _craft_bundle('9.9.9')

            def fake_read(feed, etag):
                self.assertEqual(etag, 'etag-A')
                return 200, json.dumps(latest).encode(), 'etag-B'

            _patch_attrs(self, run=lambda cmd, **kw: _ok_run(cmd, **kw))
            args = install_mod.build_parser().parse_args(
                ['--feed', 'file:///latest.json', '--home', str(home)])
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = install_mod.do_check_update(
                    args, _fetch=lambda url: blob, _read_feed=fake_read,
                    _sleep=lambda s: None)
            self.assertEqual(rc, 0)
            self.assertIn('deferred', buf.getvalue())
            self.assertEqual((home / 'update-etag').read_text(), 'etag-A\n')

    def test_up_to_date_check_stores_new_etag(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            rel = home / 'releases' / '9.9.9'
            (rel / 'packaging').mkdir(parents=True)
            (rel / 'packaging' / 'VERSION').write_text('9.9.9\n')
            home.mkdir(parents=True, exist_ok=True)
            os.symlink(str(rel), home / 'current')
            latest = {'version': '9.9.9', 'url': 'file:///bundle.tar.gz',
                      'sha256': None, 'min_python': '3.14'}

            def fake_read(feed, etag):
                self.assertIsNone(etag)
                return 200, json.dumps(latest).encode(), 'etag-B'

            def boom(url):
                raise AssertionError('tarball must not download when current')

            args = install_mod.build_parser().parse_args(
                ['--feed', 'file:///latest.json', '--home', str(home)])
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = install_mod.do_check_update(
                    args, _fetch=boom, _read_feed=fake_read, _sleep=lambda s: None)
            self.assertEqual(rc, 0)
            self.assertIn('up to date', buf.getvalue())
            self.assertEqual((home / 'update-etag').read_text(), 'etag-B\n')


if __name__ == '__main__':
    unittest.main()
