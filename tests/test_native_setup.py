"""A downloaded native installer must not become a service dependency."""
import hashlib
import importlib.util
import io
import json
import os
import plistlib
import shutil
import tarfile
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.fakes import LAUNCHD
from tests.install_fixtures import _craft_bundle, _ok_run, _patch_attrs, _static_fetch, install_mod

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(
        'test_router_' + name, ROOT / 'packaging' / (name + '.py'))
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


payload = module('native_payload')


def resources(root, version='1.2.0', channel='stable'):
    root.mkdir(parents=True)
    for folder in ('runtime/python/bin', 'router/packaging', 'payload'):
        (root / folder).mkdir(parents=True)
    (root / 'runtime/python/bin/python3.14').write_text('bundled Python')
    for name in ('install.py', 'native_setup.py'):
        (root / 'router/packaging' / name).write_text('# packaged entrypoint\n')
    blob = b'packaged-router'
    sha = hashlib.sha256(blob).hexdigest()
    (root / 'payload/bundle.tar.gz').write_bytes(blob)
    doc = dict(version=version, channel=channel, sha256=sha,
               target=payload.target(), runtime_exec='python/bin/python3.14')
    (root / 'installer.json').write_text(json.dumps(doc))
    (root / 'payload/latest.json').write_text(json.dumps(
        dict(version=version, sha256=sha, url='file://bundle.tar.gz')))
    return root


class NativePayloadTests(unittest.TestCase):
    def test_setup_readiness_ignores_legacy_download_signin_state(self):
        setup = module('native_setup')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = resources(root / 'download')
            home = root / 'home'
            home.mkdir()
            (home / 'download-auth.json').write_text('{old or corrupt auth')
            readiness = mock.Mock()
            readiness.check.return_value = {'ready': True, 'clients': {}}
            native_load = setup.load
            def load(name):
                return readiness if name == 'native_readiness' else native_load(name)
            run = mock.Mock(return_value=SimpleNamespace(returncode=0, stdout='{"serving":true}'))
            with mock.patch.object(setup, 'load', side_effect=load):
                facts = setup.status(source, home, run)
            self.assertTrue(facts['onboarding']['ready'])
            self.assertEqual(facts['downloads'], {'access_ready': True, 'public': True})
            self.assertEqual((home / 'download-auth.json').read_text(), '{old or corrupt auth')

    def test_desktop_only_guides_missing_plugin_setup_tools_before_installing(self):
        setup = module('native_setup')
        dialog = mock.Mock()
        dialog.confirm.return_value = False
        with mock.patch('shutil.which', return_value=None), \
                mock.patch.object(setup.webbrowser, 'open') as browser:
            self.assertTrue(setup._missing_assistant(['--clients', 'none', '--desktop'], dialog))
        self.assertIn('Claude desktop', dialog.confirm.call_args.args[0])
        browser.assert_not_called()

    def test_retains_files_before_the_download_is_deleted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            download = resources(root / 'download')
            kept = payload.retained(download, root / 'installed')
            shutil.rmtree(download)
            args = payload.install_arguments(kept, root / 'installed')
            self.assertTrue(Path(args[0]).is_file())
            self.assertTrue(Path(args[1]).is_file())
            self.assertTrue((kept / 'payload/bundle.tar.gz').is_file())
            self.assertNotIn(str(download), ' '.join(args))

    def test_reopening_keeps_existing_client_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = resources(root / 'download', channel='stable')
            home = root / 'home'
            home.mkdir()
            (home / 'channel').write_text('beta\n')
            (home / 'feed').write_text('file:///managed/feed.json\n')
            args = payload.install_arguments(source, home, {'clients': 'claude'})
            self.assertEqual(args[args.index('--clients') + 1], 'claude')
            self.assertNotIn('--choose-clients', args)
            self.assertEqual((home / 'channel').read_text(), 'beta\n')
            self.assertEqual((home / 'feed').read_text(), 'file:///managed/feed.json\n')

    def test_native_first_setup_and_add_send_only_the_chosen_new_clients(self):
        setup = module('native_setup')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = resources(root / 'download')
            for existing in (False, True):
                home = root / str(existing)
                home.mkdir()
                if existing:
                    (home / 'current').write_text('1.2.0\n')
                    (home / 'mixed-router-state.json').write_text('{"clients":"codex"}')
                dialog = mock.MagicMock()
                dialog.dialog.ask.return_value = ('claude', 'terminal')
                dialog.dialog.plan.return_value = ('claude', False)
                load, invoke, which = setup.load, setup.run_installer, shutil.which
                run = mock.Mock(return_value=SimpleNamespace(returncode=1))
                with mock.patch.object(setup, 'load', side_effect=lambda name:
                        dialog if name == 'native_dialog' else mock.Mock()
                        if name == 'native_shortcuts' else load(name)), \
                        mock.patch('shutil.which', side_effect=lambda name, **kwargs:
                                   '/assistant' if name == 'claude' else which(name, **kwargs)), \
                        mock.patch.object(setup, 'run_installer', side_effect=lambda *args:
                                          invoke(*args, run=run)):
                    self.assertEqual(setup.onboard(source, home, 'add' if existing else 'resume'), 1)
                args = run.call_args.args[0]
                self.assertEqual(args[args.index('--clients') + 1], 'claude')
                self.assertNotIn('--setup', args)
                self.assertNotIn('--choose-clients', args)
                self.assertEqual(args.count('--clients'), 1)

    def test_replacing_key_uses_pure_repair_and_passes_the_actual_home(self):
        setup = module('native_setup')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = resources(root / 'download')
            home = root / 'home'
            home.mkdir()
            (home / 'current').write_text('1.2.0\n')
            (home / 'activation.json').write_text('{unreadable')
            (home / 'mixed-router-state.json').write_text(json.dumps(dict(
                clients='claude', port=1, token='synthetic', setup=dict(nonce='test', expires=2000))))
            invoke = setup.run_installer
            run = mock.Mock(return_value=SimpleNamespace(returncode=0))
            with mock.patch.object(setup, 'run_installer', side_effect=lambda *args:
                    invoke(*args, run=run)), mock.patch.object(setup.time, 'time', return_value=1000):
                setup._key(source, home, replace=True, run=run)
            first, key = run.call_args_list
            self.assertEqual(first.args[0].count('--setup'), 1)
            self.assertFalse(set(first.args[0]) & {'--clients', '--choose-clients', '--desktop'})
            self.assertEqual(key.kwargs['env']['ROUTER_HOME'], str(home))

    def test_refuses_a_tampered_bundle_before_creating_the_home(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = resources(root / 'download')
            (source / 'payload/bundle.tar.gz').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'verification'):
                payload.retained(source, root / 'home')
            self.assertFalse((root / 'home').exists())

    def test_refuses_a_foreign_runtime_and_an_escaping_executable(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = resources(Path(temporary) / 'download')
            with self.assertRaisesRegex(ValueError, 'not for this computer'):
                payload.metadata(source, 'unsupported/cpu')
            path = source / 'installer.json'
            doc = json.loads(path.read_text())
            doc['runtime_exec'] = '../outside'
            path.write_text(json.dumps(doc))
            with self.assertRaisesRegex(ValueError, 'Python'):
                payload.metadata(source)


class IndependentControllerTests(unittest.TestCase):
    def test_rollback_and_pruning_do_not_change_the_update_controller(self):
        controller = module('native_controller')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / 'home'
            source = root / 'source'
            (source / 'packaging').mkdir(parents=True)
            files = {'packaging/install.py': b'# independent updater\n',
                     'packaging/VERSION': b'1.2.0\n'}
            for name, content in files.items():
                (source / name).write_bytes(content)
            (source / 'MANIFEST.json').write_text(json.dumps(dict(
                version='1.2.0', files={name: hashlib.sha256(content).hexdigest()
                                       for name, content in files.items()})))
            controller.install(home, source)
            (home / 'current').write_text('0.9.0\n')
            shutil.rmtree(source)
            selected = controller.installer(home)
            self.assertEqual(selected.read_text(), '# independent updater\n')
            self.assertNotIn('/releases/', str(selected))


@unittest.skipIf(os.name == 'nt', 'This service-boundary fixture uses launchd.')
class NativeKeyRefreshTests(unittest.TestCase):
    def test_explicit_key_refresh_restores_service_and_retains_saved_install(self):
        for missing, older, corrupt in ((False, False, False), (True, True, False),
                                        (False, True, True), (True, False, True)):
            with self.subTest(missing=missing, older=older, corrupt=corrupt), \
                    tempfile.TemporaryDirectory() as temporary:
                self.repair(Path(temporary), missing, older, corrupt)

    def repair(self, root, missing, older, corrupt):
        setup = module('native_setup')
        source = resources(root / 'download', '1.2.0' if older else '1.2.1')
        blob, latest = _craft_bundle('1.2.0' if older else '1.2.1')
        with tarfile.open(fileobj=io.BytesIO(blob)) as archive:
            archive.extractall(source / 'router', filter='data')
        user = root / 'user'
        home = user / '.codex/mixed-model-router'
        home.mkdir(parents=True)
        release = home / 'releases/1.2.1'
        installed, _ = _craft_bundle('1.2.1')
        with tarfile.open(fileobj=io.BytesIO(installed)) as archive:
            archive.extractall(release, filter='data')
        retained_files = {path.relative_to(release): path.read_bytes()
                          for path in release.rglob('*') if path.is_file()}
        client_config = user / '.codex/config.toml'
        client_config.write_bytes(b'model = "owner-choice"\n')
        state = install_mod.ensure_state(home)
        state.update(clients='codex', openai_mode='none', claude_mode='subscription',
                     anthropic_mode='subscription', custom={'keep': True})
        install_mod._write_state(home, state)
        saved = {'current': b'1.2.1\n', 'channel': b'beta\n',
                 'feed': b'file:///managed/feed.json\n', 'openrouter.key': b'synthetic-key\n',
                 'activation.json': b'{broken' if corrupt else json.dumps({'clients': {
                     'codex': {'sentinel': 'keep'}, 'claude-desktop': {'sentinel': 'keep'}}}).encode()}
        for name, content in saved.items():
            (home / name).write_bytes(content)
            (home / name).chmod(0o600)
        agents = user / 'Library/LaunchAgents'
        agents.mkdir(parents=True)
        plist = agents / (install_mod.LABEL + '.plist')
        if not missing:
            plist.write_bytes(plistlib.dumps(install_mod._svc.render_plist('/old/python', home, state)))
        _patch_attrs(self, run=_ok_run)
        LAUNCHD.reset(unloaded=(install_mod.LABEL, install_mod.UPDATE_LABEL))
        commands, health = [], []
        def service_run(cmd, **kwargs):
            commands.append(cmd)
            return _ok_run(cmd, **kwargs)
        def response(*args, **kwargs):
            self.assertTrue(LAUNCHD.loaded(install_mod.LABEL), 'repair did not restore service')
            health.append(args[0])
            reply = mock.MagicMock()
            reply.__enter__.return_value = reply
            reply.status = 200
            reply.read.return_value = b'{"status":"ok","version":"1.2.1"}'
            return reply
        real_install = install_mod.do_install
        def invoke(argv, **kwargs):
            with mock.patch.dict(os.environ, kwargs['env'], clear=True), \
                    mock.patch.object(install_mod, 'do_install', side_effect=lambda args:
                        real_install(args, _fetch=_static_fetch(latest, blob), _run=service_run)):
                return SimpleNamespace(returncode=install_mod.main(argv[2:]))
        with mock.patch.dict(os.environ, {'HOME': str(user), 'USERPROFILE': str(user),
                             'PATH': '/usr/bin:/bin'}, clear=True), \
                mock.patch.object(install_mod._svc.urllib.request, 'urlopen', side_effect=response), \
                redirect_stdout(io.StringIO()):
            permanent = setup.retained(source, home)
            self.assertEqual(setup.run_installer(permanent, home, ['--setup'], run=invoke).returncode, 0)
        self.assertTrue(health)
        self.assertTrue(plist.is_file())
        self.assertTrue(any(cmd[:2] == ['launchctl', 'bootstrap'] for cmd in commands))
        self.assertEqual({name: (home / name).read_bytes() for name in saved}, saved)
        after = install_mod.ensure_state(home)
        self.assertEqual({key: after[key] for key in state}, state)
        self.assertIn('nonce', after['setup'])
        self.assertEqual(list((home / 'releases').iterdir()), [release])
        self.assertEqual({path.relative_to(release): path.read_bytes()
                          for path in release.rglob('*') if path.is_file()}, retained_files)
        self.assertEqual(client_config.read_bytes(), b'model = "owner-choice"\n')


if __name__ == '__main__':
    unittest.main()
