"""Installer-generated state must satisfy the runtime loader (brief defect 1)."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from ai_router import catalogue
from ai_router.runtime import load_state
from ai_router.retired_slugs import SUBSCRIPTION as LEAF_RETIRED_SLUGS
from ai_router.subscription_roster import SUBSCRIPTION_SLUGS
from tests.test_install import install_mod


class InstallStateTests(unittest.TestCase):
    def _home(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        home = Path(tmp) / 'home'
        home.mkdir(parents=True)
        return home

    def _load(self, path):
        with mock.patch.dict(os.environ, {'OPENROUTER_API_KEY': 'test-key'}):
            return load_state(path)

    def test_fresh_state_passes_runtime_load_with_default_roster(self):
        home = self._home()
        state = install_mod.ensure_state(home)
        self.assertEqual(state['openai_models'], install_mod.DEFAULT_OPENAI_MODELS)
        self.assertEqual(len(state['openai_models']), 8)
        loaded = self._load(home / 'mixed-router-state.json')
        self.assertEqual(loaded['openai_models'], install_mod.DEFAULT_OPENAI_MODELS)

    def test_existing_state_missing_roster_is_backfilled(self):
        home = self._home()
        (home / 'mixed-router-state.json').write_text(
            json.dumps({'port': 1, 'token': 't'}) + '\n')
        state = install_mod.ensure_state(home)
        self.assertEqual(state['openai_models'], install_mod.DEFAULT_OPENAI_MODELS)
        self.assertEqual(self._load(home / 'mixed-router-state.json')['openai_models'],
                         install_mod.DEFAULT_OPENAI_MODELS)

    def test_existing_valid_state_is_untouched(self):
        home = self._home()
        before = json.dumps({'port': 1, 'token': 't', 'openai_models': ['x']}) + '\n'
        (home / 'mixed-router-state.json').write_text(before)
        state = install_mod.ensure_state(home)
        self.assertEqual(state['openai_models'], ['x'])
        self.assertEqual((home / 'mixed-router-state.json').read_text(), before)

    def test_subscription_roster_is_single_sourced(self):
        # Plan 123: the roster leaf, the service seed list, and the catalogue
        # tables cover the same eight slugs; the service order matches the
        # leaf so fresh-state seeding and picker order stay stable.
        self.assertEqual(tuple(install_mod.DEFAULT_OPENAI_MODELS),
                         tuple(SUBSCRIPTION_SLUGS))
        self.assertEqual(set(catalogue.SUBSCRIPTION_REASONING),
                         set(SUBSCRIPTION_SLUGS))
        self.assertEqual(set(catalogue.SUBSCRIPTION_DISPLAY_NAMES),
                         set(SUBSCRIPTION_SLUGS))
        self.assertEqual(len(SUBSCRIPTION_SLUGS), 8)

    def test_service_roster_loads_from_home_style_layout(self):
        # Plan 123: service.py resolves the roster leaf relative to its own
        # file, so a relocated (installed) tree still seeds the roster.
        import importlib.util
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / 'packaging').mkdir()
            (tmp / 'ai_router').mkdir()
            for name in ('service.py', 'launchd.py', 'feed.py',
                         'atomic_write.py'):
                shutil.copy(root / 'packaging' / name, tmp / 'packaging' / name)
            for name in ('subscription_roster.py', 'retired_slugs.py',
                         'feed_verify.py'):
                shutil.copy(root / 'ai_router' / name, tmp / 'ai_router' / name)
            spec = importlib.util.spec_from_file_location(
                'relocated_service', tmp / 'packaging' / 'service.py')
            svc = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(svc)
            self.assertEqual(list(svc.DEFAULT_OPENAI_MODELS),
                             list(SUBSCRIPTION_SLUGS))

    def test_retired_slugs_are_single_sourced(self):
        # Plan 100: the service prune set and the catalogue set are the same
        # object content; a one-sided edit fails here.
        self.assertEqual(frozenset(install_mod._svc.RETIRED_SUBSCRIPTION_SLUGS),
                         frozenset(catalogue.RETIRED_SUBSCRIPTION_SLUGS))
        self.assertEqual(frozenset(catalogue.RETIRED_SUBSCRIPTION_SLUGS),
                         frozenset(LEAF_RETIRED_SLUGS))

    def test_prune_survives_non_string_entries(self):
        # Plan 100 review fix: the prune must not hash non-string elements.
        home = self._home()
        (home / 'mixed-router-state.json').write_text(
            json.dumps({'port': 1, 'token': 't',
                        'openai_models': ['gpt-reserve', {'x': 1}, 'gpt-6-astra']}) + '\n')
        state = install_mod.ensure_state(home)
        self.assertEqual(state['openai_models'], [{'x': 1}, 'gpt-6-astra'])

    def test_prune_follows_the_shared_set_not_a_literal(self):
        # Plan 100: patching the shared set drives the prune, so a hardcoded
        # literal in ensure_state cannot pass this.
        home = self._home()
        (home / 'mixed-router-state.json').write_text(
            json.dumps({'port': 1, 'token': 't',
                        'openai_models': ['gpt-synthetic-retired', 'gpt-6-astra']}) + '\n')
        with mock.patch.object(install_mod._svc, 'RETIRED_SUBSCRIPTION_SLUGS',
                               frozenset({'gpt-synthetic-retired'})):
            state = install_mod.ensure_state(home)
        self.assertEqual(state['openai_models'], ['gpt-6-astra'])

    def test_existing_state_with_retired_slug_is_pruned(self):
        home = self._home()
        (home / 'mixed-router-state.json').write_text(
            json.dumps({'port': 1, 'token': 't',
                        'openai_models': ['gpt-6-astra', 'gpt-reserve',
                                          'gpt-5.6-luna']}) + '\n')
        state = install_mod.ensure_state(home)
        self.assertEqual(state['openai_models'], ['gpt-6-astra', 'gpt-5.6-luna'])
        self.assertEqual(self._load(home / 'mixed-router-state.json')['openai_models'],
                         ['gpt-6-astra', 'gpt-5.6-luna'])


if __name__ == '__main__':
    unittest.main()
