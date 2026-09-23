"""Fresh-install picker catalogue: config flag and merge seeding (Plan 110/039).

Reuses the tests.install_fixtures rig, so test_install.py keeps tests only.
"""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from tests._platform import unix_only
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from ai_router.catalogue import check, read_openai_mode
from ai_router.clients import models_for
from ai_router.registry import MODELS
from tests.install_fixtures import _ok_run, _patch_attrs, _static_fetch, install_mod

_ROOT = Path(__file__).resolve().parents[1]


def _release_bundle(tmp):
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
    return version, _static_fetch(latest, blob), blob, manifest


def _is_catalogue(cmd):
    return 'ai_router.catalogue' in cmd


def _recording_run(calls, fail_catalogue=False):
    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        if _is_catalogue(cmd):
            if fail_catalogue:
                return SimpleNamespace(returncode=1, stdout='', stderr='merge boom')
            # Portable: run the catalogue merge with this interpreter, not
            # the installer-resolved absolute path (Homebrew-only on macOS).
            return subprocess.run([sys.executable, *cmd[1:]], **kwargs)
        return _ok_run(cmd, **kwargs)
    return fake_run


def _env(tmp):
    return {'HOME': str(Path(tmp) / 'fakehome'), 'OPENROUTER_API_KEY': 'test-key',
            'ROUTER_NO_KEY_WINDOW': '1'}


def _args(home, *extra_args):
    return install_mod.build_parser().parse_args(
        ['--feed', 'file:///latest.json', '--home', str(home), *extra_args])


def _setup(test, tmp):
    home = Path(tmp) / 'home'
    version, fake_fetch, _blob, _manifest = _release_bundle(tmp)
    _patch_attrs(test, health=lambda state, timeout=20: {'status': 'ok', 'version': version})
    return home, version, fake_fetch


def _install(test, tmp, home, fake_fetch, fake_run, *extra_args):
    env = _env(tmp)
    with mock.patch.dict(os.environ, env):
        test.assertEqual(
            install_mod.do_install(_args(home, *extra_args), _fetch=fake_fetch, _run=fake_run), 0)
    return Path(env['HOME']) / '.codex' / 'config.toml'


@unix_only
class InstallCatalogueTests(unittest.TestCase):
    def test_default_install_writes_static_catalog_line(self):
        # The router serves no /models, so the file pointer is the default.
        with tempfile.TemporaryDirectory() as tmp:
            home, _, fake_fetch = _setup(self, tmp)[:3]
            config = _install(self, tmp, home, fake_fetch, _recording_run([]))
            block = config.read_text()
            self.assertIn('# BEGIN local mixed model picker', block)
            self.assertIn(f'model_catalog_json = "{home}/mixed-models.json"', block)

    def test_static_catalogue_flag_kept_as_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, _, fake_fetch = _setup(self, tmp)[:3]
            config = _install(self, tmp, home, fake_fetch,
                              _recording_run([]), '--static-catalogue')
            self.assertIn(f'model_catalog_json = "{home}/mixed-models.json"', config.read_text())

    def test_install_generates_working_picker_catalogue(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, _, fake_fetch = _setup(self, tmp)[:3]
            calls = []
            _install(self, tmp, home, fake_fetch, _recording_run(calls))
            self.assertTrue(any(_is_catalogue(cmd) and '--merge' in cmd for cmd in calls))
            catalog = json.loads((home / 'mixed-models.json').read_text())
            slugs = {m['slug'] for m in catalog['models']}
            for model in models_for(MODELS, 'codex'):
                if model.provider == 'openrouter':
                    self.assertIn(model.slug, slugs)
            # A subscription install lists the subscription rows and the
            # OpenRouter twins beside them, so an exhausted row still has a
            # paid route the user picks deliberately.
            for slug in ('openai/gpt-6-astra', 'openai/gpt-6-luna',
                         'openai/gpt-5.6-terra'):
                self.assertIn(slug, slugs)
            self.assertNotIn('openai/gpt-6-sol', slugs)
            self.assertTrue(check(str(home / 'mixed-models.json')))

    def test_install_catalogue_contains_subscription_roster(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, _, fake_fetch = _setup(self, tmp)[:3]
            _install(self, tmp, home, fake_fetch, _recording_run([]))
            catalog = json.loads((home / 'mixed-models.json').read_text())
            slugs = {m['slug'] for m in catalog['models']}
            for slug in install_mod.DEFAULT_OPENAI_MODELS:
                self.assertIn(slug, slugs)

    def test_none_mode_install_lists_twins_without_subscription_stubs(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, _, fake_fetch = _setup(self, tmp)[:3]
            _install(self, tmp, home, fake_fetch, _recording_run([]),
                     '--openai-mode', 'none')
            catalog = json.loads((home / 'mixed-models.json').read_text())
            slugs = {m['slug'] for m in catalog['models']}
            for twin in ('openai/gpt-6-astra', 'openai/gpt-5.6-terra',
                         'openai/gpt-6-luna'):
                self.assertIn(twin, slugs)
            self.assertNotIn('gpt-6-astra', slugs)
            state = json.loads((home / 'mixed-router-state.json').read_text())
            self.assertEqual(state.get('openai_mode'), 'none')
            self.assertEqual(read_openai_mode(home / 'mixed-models.json'), 'none')
            self.assertTrue(check(str(home / 'mixed-models.json'), 'codex',
                                  include_twins=True))

    def test_catalogue_merge_failure_aborts_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, version, fake_fetch = _setup(self, tmp)[:3]
            with mock.patch.dict(os.environ, _env(tmp)):
                with self.assertRaisesRegex(SystemExit, 'catalogue merge failed'):
                    install_mod.do_install(_args(home), _fetch=fake_fetch,
                                           _run=_recording_run([], fail_catalogue=True))
            self.assertFalse((home / 'releases' / version).exists())

    def test_a_client_with_no_chatgpt_login_installs_without_subscription(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, _, fake_fetch = _setup(self, tmp)[:3]
            codex_home = Path(tmp) / 'fakehome' / '.codex'
            codex_home.mkdir(parents=True)
            (codex_home / 'auth.json').write_text(json.dumps(
                {'auth_mode': 'apikey', 'OPENAI_API_KEY': 'sk-not-a-subscription'}))
            config = _install(self, tmp, home, fake_fetch, _recording_run([]))
            state = json.loads((home / 'mixed-router-state.json').read_text())
            self.assertEqual(state.get('openai_mode'), 'none')
            self.assertIn('model_provider = "scg_router"', config.read_text())
            catalog = json.loads((home / 'mixed-models.json').read_text())
            slugs = {m['slug'] for m in catalog['models']}
            self.assertNotIn('gpt-6-luna', slugs)
            self.assertIn('openai/gpt-6-luna', slugs)


class DefaultModeTests(unittest.TestCase):
    """The install-time default reads Codex's own login store, never a token."""
    def _mode(self, document, name='auth.json'):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / '.codex' / 'config.toml'
            config.parent.mkdir(parents=True)
            if document is not None:
                (config.parent / name).write_text(document)
            return install_mod._codex_config.default_mode(config)

    def test_a_chatgpt_login_keeps_the_subscription_default(self):
        self.assertEqual(self._mode(json.dumps(
            {'auth_mode': 'chatgpt', 'tokens': {'access_token': 'x'}})),
            'subscription')

    def test_a_readable_store_without_tokens_is_no_subscription(self):
        for document in ({'auth_mode': 'apikey', 'OPENAI_API_KEY': 'k'},
                         {'tokens': {}},
                         {'auth_mode': 'chatgpt', 'tokens': None},
                         {}):
            with self.subTest(document=document):
                self.assertEqual(self._mode(json.dumps(document)), 'none')

    def test_an_unknown_client_keeps_the_historical_default(self):
        for document in (None, 'not json', '[]', '"text"'):
            with self.subTest(document=document):
                self.assertEqual(self._mode(document), 'subscription')

    def test_the_default_path_is_the_codex_home_beside_the_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / '.codex'
            codex_home.mkdir()
            (codex_home / 'auth.json').write_text(json.dumps({'tokens': {}}))
            with mock.patch.object(Path, 'home', return_value=Path(tmp)):
                self.assertEqual(install_mod._codex_config.default_mode(), 'none')


if __name__ == '__main__':
    unittest.main()
