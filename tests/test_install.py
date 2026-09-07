"""Plan 041 installer tests. install.py imports cleanly as a module."""
import hashlib
import io
import json
import os
import stat
import sys
import tarfile
import tempfile
import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

_ROOT = Path(__file__).resolve().parents[1]


def _install_mod():
    spec = importlib.util.spec_from_file_location('router_install', _ROOT / 'packaging' / 'install.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
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
        return SimpleNamespace(returncode=0, stdout='3 14', stderr='')
    return SimpleNamespace(returncode=0, stdout='', stderr='')


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
        content = install_mod.render_plist('/opt/homebrew/bin/python3.14', Path('/tmp/hm'))
        self.assertEqual(content['Label'], 'com.local.codex-mixed-model-router')
        self.assertEqual(content['ProgramArguments'],
                         ['/opt/homebrew/bin/python3.14', '-m', 'codex_router'])
        self.assertEqual(content['WorkingDirectory'], '/tmp/hm/current')
        self.assertEqual(content['EnvironmentVariables'], {'ROUTER_HOME': '/tmp/hm'})
        self.assertTrue(content['KeepAlive'] and content['RunAtLoad'])
        self.assertNotIn('token', json.dumps(content))

    def test_swap_current_is_atomic_and_rollback_restores_previous(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            first, second = home / 'releases' / '0.2.0', home / 'releases' / '0.3.0'
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            self.assertIsNone(install_mod.swap_current(home, first))
            self.assertEqual(os.readlink(home / 'current'), str(first))
            previous = install_mod.swap_current(home, second)
            self.assertEqual(previous, str(first))
            install_mod.swap_current(home, Path(previous))
            self.assertEqual(os.readlink(home / 'current'), str(first))

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

    def test_wait_idle_returns_false_when_inflight_stays_positive(self):
        state = {'port': 1, 'token': 'x'}
        self.assertFalse(
            install_mod.wait_idle(state, timeout=2, fetch_health=lambda s: {'inflight': 1}))

    def test_install_dry_run_performs_no_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            latest = {'version': '9.9.9', 'url': 'file:///bundle.tar.gz',
                      'sha256': None, 'min_python': '3.14'}
            args = install_mod.build_parser().parse_args(
                ['--feed', 'file:///latest.json', '--home', str(home), '--dry-run'])
            rc = install_mod.do_install(args, _fetch=lambda url: json.dumps(latest).encode())
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
            manifest = {'version': '9.9.9', 'files':
                        {'packaging/VERSION': hashlib.sha256(b'9.9.9\n').hexdigest()}}
            blob = _tarball(files=[('MANIFEST.json', json.dumps(manifest)),
                                   ('packaging/VERSION', '9.9.9\n')])
            latest = {'version': '9.9.9', 'url': 'file:///bundle.tar.gz',
                      'sha256': None, 'min_python': '3.14'}

            def fake_fetch(url):
                return json.dumps(latest).encode() if url.endswith('.json') else blob

            saved_run, saved_test, saved_health = (
                install_mod.run, install_mod.self_test, install_mod.health)
            self.addCleanup(setattr, install_mod, 'run', saved_run)
            self.addCleanup(setattr, install_mod, 'self_test', saved_test)
            self.addCleanup(setattr, install_mod, 'health', saved_health)
            install_mod.self_test = lambda *args: None
            install_mod.health = lambda state, timeout=20: None
            calls = []

            def fake_run(cmd, **kwargs):
                calls.append(cmd)
                return _ok_run(cmd, **kwargs)

            args = install_mod.build_parser().parse_args(
                ['--feed', 'file:///latest.json', '--home', str(home)])
            env = {'HOME': tmp, 'OPENROUTER_API_KEY': 'test-key'}
            with mock.patch.dict(os.environ, env):
                with self.assertRaises(SystemExit) as ctx:
                    install_mod.do_install(args, _fetch=fake_fetch, _run=fake_run)
            self.assertEqual(ctx.exception.code, 1)
            self.assertEqual(os.readlink(home / 'current'), str(prev))
            self.assertTrue(any('bootstrap' in cmd for cmd in calls))


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
        import importlib.util
        with tempfile.TemporaryDirectory() as tmp:
            feeddir = Path(tmp) / 'feed'
            feeddir.mkdir()
            spec = importlib.util.spec_from_file_location(
                'router_release', _ROOT / 'packaging' / 'release.py')
            release_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(release_mod)
            release_mod.main(['--out', str(feeddir)])
            tarball = next(iter(feeddir.glob('*.tar.gz')))
            extract = Path(tmp) / 'extracted'
            extract.mkdir()
            with tarfile.open(tarball, mode='r') as tar:
                tar.extractall(extract, filter='data')
            install_mod.self_test(sys.executable, extract)

    def test_fresh_install_writes_plists_before_first_restart(self):
        import importlib.util
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
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
            version = manifest['version']
            latest = {'version': version, 'url': 'file:///bundle.tar.gz',
                      'sha256': hashlib.sha256(blob).hexdigest(), 'min_python': '3.14'}

            def fake_fetch(url):
                return json.dumps(latest).encode() if url.endswith('.json') else blob

            agents = Path(tmp) / 'fakehome' / 'Library' / 'LaunchAgents'
            plist = agents / 'com.local.codex-mixed-model-router.plist'
            order = []

            def fake_run(cmd, **kwargs):
                order.append((list(cmd), plist.exists()))
                return _ok_run(cmd, **kwargs)

            saved_run, saved_health = install_mod.run, install_mod.health
            self.addCleanup(setattr, install_mod, 'run', saved_run)
            self.addCleanup(setattr, install_mod, 'health', saved_health)
            install_mod.health = lambda state, timeout=20: {'status': 'ok', 'version': version}
            args = install_mod.build_parser().parse_args(
                ['--feed', 'file:///latest.json', '--home', str(home)])
            env = {'HOME': str(Path(tmp) / 'fakehome'), 'OPENROUTER_API_KEY': 'test-key'}
            with mock.patch.dict(os.environ, env):
                self.assertEqual(
                    install_mod.do_install(args, _fetch=fake_fetch, _run=fake_run), 0)
            bootstraps = [saw for cmd, saw in order if 'bootstrap' in cmd]
            self.assertTrue(bootstraps, 'service was never restarted')
            self.assertTrue(all(bootstraps), 'restart ran before plists were written')
            self.assertEqual(os.readlink(home / 'current'), str(home / 'releases' / version))


if __name__ == '__main__':
    unittest.main()
