"""Codex-facing defaults the router owns: no Ultra, Max in, steer, DeepSeek.

The served catalogue never carries Ultra, the install seeds the startup
model and the managed [desktop] preferences, and a detach puts the prior
desktop values back.
"""
import importlib.util as _ilu
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests._platform import unix_only
from tests.install_fixtures import (
    craft_bundle,
    ok_run,
    patch_attrs,
    run_install,
    static_fetch,
)

_ROOT = Path(__file__).resolve().parents[1]
_spec = _ilu.spec_from_file_location('codex_config_under_test',
                                     _ROOT / 'packaging' / 'codex_config.py')
codex_config = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(codex_config)

BLOCK = ('# BEGIN local mixed model picker\n'
         'model_catalog_json = "/tmp/x/mixed-models.json"\n'
         '# END local mixed model picker\n')
SEEDED = 'model = "deepseek/deepseek-v4.1-flash"'
SEEDED_EFFORT = 'model_reasoning_effort = "max"'
MANAGED_EFFORTS = ('enabled-reasoning-efforts = '
                   '["low", "medium", "high", "xhigh", "max", "persistent"]')


class CatalogueUltraTests(unittest.TestCase):
    """Ultra is Codex's automatic-delegation level: never served."""

    def test_no_served_row_advertises_ultra_fresh_or_stale(self):
        from ai_router.catalogue import merge, subscription_stub
        stale = dict(subscription_stub('gpt-6-astra'),
                     default_reasoning_level='ultra',
                     supported_reasoning_levels=[
                         {'effort': effort, 'description': effort}
                         for effort in ('low', 'medium', 'high', 'xhigh',
                                        'max', 'ultra')])
        merged = merge({'models': [stale]},
                       roster=('gpt-6-astra', 'gpt-5.6-luna'))
        for row in merged['models']:
            with self.subTest(slug=row['slug']):
                efforts = [e['effort'] for e in row['supported_reasoning_levels']]
                self.assertNotIn('ultra', efforts)
                self.assertIn(row['default_reasoning_level'], efforts)
        astra = next(m for m in merged['models'] if m['slug'] == 'gpt-6-astra')
        self.assertEqual(astra['default_reasoning_level'], 'medium')
        self.assertEqual([e['effort'] for e in astra['supported_reasoning_levels']],
                         ['low', 'medium', 'high', 'xhigh', 'max'])


class DesktopPreferenceTests(unittest.TestCase):
    """The managed [desktop] values, and what a detach puts back."""

    def test_existing_values_are_replaced_and_restored(self):
        original = ('[desktop]\nappearanceTheme = "dark"\n'
                    'followUpQueueMode = "queue"\n')
        text, record = codex_config.desktop_preferences(original)
        self.assertIn('followUpQueueMode = "steer"', text)
        self.assertIn(MANAGED_EFFORTS, text)
        self.assertIn('appearanceTheme = "dark"', text)
        self.assertEqual(codex_config.desktop_preferences(text)[0], text)
        self.assertEqual(codex_config.restore_desktop(text, record), original)

    def test_missing_table_is_created(self):
        text, record = codex_config.desktop_preferences('approval_policy = "never"\n')
        self.assertIn('[desktop]', text)
        self.assertIn(MANAGED_EFFORTS, text)
        self.assertTrue(record)

    def test_owner_change_after_attach_survives_detach(self):
        text, record = codex_config.desktop_preferences('[desktop]\n')
        changed = text.replace('"steer"', '"queue"')
        self.assertIn('followUpQueueMode = "queue"',
                      codex_config.restore_desktop(changed, record))

    def test_ambiguous_or_repeated_keys_refuse_the_edit(self):
        cases = ('[desktop]\nfollowUpQueueMode = "queue"\n[desktop]\n',
                 '[desktop]\nfollowUpQueueMode = "queue"\n'
                 'followUpQueueMode = "steer"\n')
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(codex_config.desktop_preferences(text), (text, {}))

    def test_a_multi_line_value_refuses_the_edit(self):
        # Rewriting a key whose value spans lines would leave the tail of
        # the array behind; the edit must refuse instead.
        text = ('[desktop]\nenabled-reasoning-efforts = [\n  "low",\n  "max",\n]\n')
        self.assertEqual(codex_config.desktop_preferences(text), (text, {}))

    def test_a_trailing_comment_is_read_as_the_owners_list(self):
        original = '[desktop]\nenabled-reasoning-efforts = ["low", "ultra"] # mine\n'
        text, record = codex_config.desktop_preferences(original)
        self.assertIn('enabled-reasoning-efforts = ["low", "max"]', text)
        self.assertEqual(record['previous']['enabled-reasoning-efforts'],
                         ['low', 'ultra'])
        self.assertIn('enabled-reasoning-efforts = ["low", "ultra"]',
                      codex_config.restore_desktop(text, record))


class SeedModelTests(unittest.TestCase):
    """The startup model is seeded once and never duplicated."""

    def _seed(self, text, block=None, previous=None):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.toml'
            path.write_text(text)
            return codex_config.seed_picker_selection(path, previous,
                                                      block or BLOCK)

    def test_fresh_config_gets_the_router_default(self):
        seeded = self._seed('approval_policy = "never"\n')
        self.assertIn(SEEDED, seeded)
        self.assertIn(SEEDED_EFFORT, seeded)

    def test_a_config_with_its_own_model_is_left_alone(self):
        text = BLOCK + '\nmodel = "meta/muse-spark-1.3"\n'
        self.assertEqual(self._seed(text, previous=BLOCK), BLOCK)

    def test_compact_owner_spacing_is_not_reseeded(self):
        # model="x" is valid TOML; a second root-level key would break it.
        self.assertEqual(self._seed('model="meta/muse-spark-1.3"\n'), BLOCK)

    def test_carried_owner_lines_are_not_reseeded(self):
        carried = BLOCK.replace('# END', SEEDED + '\n# END')
        self.assertEqual(self._seed('approval_policy = "never"\n',
                                    block=carried), carried)

    def test_a_compact_carried_pick_is_kept(self):
        # Codex may rewrite the line's shape; it must still be carried and
        # must never be joined by a second seeded key.
        carried = BLOCK.replace('# END', '  model="meta/muse-spark-1.3"\n# END')
        self.assertEqual(self._seed('approval_policy = "never"\n',
                                    block=carried), carried)

    def test_seeded_lines_land_before_a_declared_table(self):
        block = ('# BEGIN local mixed model picker\n'
                 'model_provider = "scg_router"\n'
                 '[model_providers.scg_router]\nname = "SC router"\n'
                 '# END local mixed model picker\n')
        seeded = self._seed('approval_policy = "never"\n', block=block)
        self.assertLess(seeded.index(SEEDED),
                        seeded.index('[model_providers.scg_router]'))


@unix_only
class InstallerPreferenceTests(unittest.TestCase):
    """The install writes both surfaces; a detach puts the prior ones back."""

    def _install(self, tmp, home, version='1.0.0'):
        blob, latest = craft_bundle(version)
        latest = dict(latest, version=version)
        patch_attrs(self, run=ok_run, self_test=lambda *args: None,
                    write_catalogue=lambda *args, **kwargs: None,
                    wait_version=lambda *args, **kwargs: True)
        run_install(self, tmp, home, static_fetch(latest, blob), ok_run)
        return Path(tmp) / 'fakehome' / '.codex' / 'config.toml'

    def test_install_seeds_the_model_and_the_desktop_preferences(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            text = self._install(tmp, home).read_text()
            for expected in (SEEDED, SEEDED_EFFORT,
                             'followUpQueueMode = "steer"', MANAGED_EFFORTS):
                self.assertIn(expected, text)
            receipt = json.loads((home / 'activation.json').read_text())
            self.assertIn('desktop', receipt['clients']['codex'])

    def test_an_existing_model_choice_is_kept_and_never_duplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / 'fakehome' / '.codex'
            config_dir.mkdir(parents=True)
            (config_dir / 'config.toml').write_text(
                'model = "meta/muse-spark-1.3"\nmodel_reasoning_effort = "xhigh"\n')
            text = self._install(tmp, Path(tmp) / 'home').read_text()
            self.assertEqual(text.count('model = '), 1)
            self.assertIn('model = "meta/muse-spark-1.3"', text)
            self.assertIn('followUpQueueMode = "steer"', text)

    def test_detach_restores_the_prior_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            config = self._install(tmp, home)
            env = {**os.environ, 'ROUTER_HOME': str(home),
                   'ROUTER_RESTORE_ONLY': '1'}
            result = subprocess.run(
                [sys.executable, str(_ROOT / 'tools' / 'disable.py')],
                capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            text = config.read_text()
            self.assertNotIn('# BEGIN local mixed model picker', text)
            self.assertNotIn('followUpQueueMode', text)
            self.assertNotIn('enabled-reasoning-efforts', text)

    def test_an_update_keeps_the_owners_originals_for_detach(self):
        # A scheduled update re-applies the managed values; the receipt must
        # still hold what the owner had before the router ever touched them.
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / 'fakehome' / '.codex'
            config_dir.mkdir(parents=True)
            (config_dir / 'config.toml').write_text(
                '[desktop]\nfollowUpQueueMode = "queue"\n')
            home = Path(tmp) / 'home'
            self._install(tmp, home, '1.0.0')
            config = self._install(tmp, home, '1.0.1')
            self.assertIn('followUpQueueMode = "steer"', config.read_text())
            env = {**os.environ, 'ROUTER_HOME': str(home),
                   'ROUTER_RESTORE_ONLY': '1'}
            result = subprocess.run(
                [sys.executable, str(_ROOT / 'tools' / 'disable.py')],
                capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            text = config.read_text()
            self.assertIn('followUpQueueMode = "queue"', text)
            self.assertNotIn('enabled-reasoning-efforts', text)

    def test_an_owner_pick_inside_the_block_survives_update_and_detach(self):
        # Codex rewrites the seeded model line in place, so the receipt's
        # block copy goes stale; an update must still land and keep the pick.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            config = self._install(tmp, home, '1.0.0')
            config.write_text(config.read_text().replace(
                SEEDED, 'model = "meta/muse-spark-1.3"'))
            config = self._install(tmp, home, '1.0.1')
            self.assertIn('model = "meta/muse-spark-1.3"', config.read_text())
            env = {**os.environ, 'ROUTER_HOME': str(home),
                   'ROUTER_RESTORE_ONLY': '1'}
            result = subprocess.run(
                [sys.executable, str(_ROOT / 'tools' / 'disable.py')],
                capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('# BEGIN local mixed model picker', config.read_text())

    def test_a_duplicate_pick_in_the_block_is_normalised(self):
        # Two root-level `model` keys already make the config unreadable;
        # the update must leave exactly one, and the owner's last one wins.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            config = self._install(tmp, home, '1.0.0')
            config.write_text(config.read_text().replace(
                SEEDED, SEEDED + '\nmodel = "meta/muse-spark-1.3"'))
            config = self._install(tmp, home, '1.0.1')
            text = config.read_text()
            self.assertEqual(text.count('model = '), 1)
            self.assertIn('model = "meta/muse-spark-1.3"', text)


if __name__ == '__main__':
    unittest.main()
