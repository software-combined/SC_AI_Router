"""Switch Codex's picker file, `routed-models.json`, and its readiness check.

The switched route runs Codex without ChatGPT sign-in, so its picker may list
only models the router can serve for this key: the rows no-subscription mode
shows, filtered exactly like the mixed list. Every availability sync rewrites
the file, never empty and never without a current snapshot, and
`codex_route.ready` tells Switch Codex whether the file matches the installed
key's current snapshot.
"""
import json
import unittest
import urllib.error
from unittest import mock

from ai_router import availability, catalogue, codex_route, routed_models, snapshot_store
from ai_router.registry import external_slugs
from ai_router.state import STATE_NAME
from ai_router.subscription_roster import SUBSCRIPTION_SLUGS
from tests.harness import tmp_home
from tests.test_availability import _ok
from tests.test_model_prompt import _write_policy

KEY = 'k'
FLASH, TWIN, QWEN = ('deepseek/deepseek-v4.1-flash', 'openai/gpt-6-astra',
                     'qwen/qwen3.8-max-0902')


def _denied(req, timeout=None):
    raise urllib.error.HTTPError(req.full_url, 401, 'denied', {}, None)


def _down(req, timeout=None):
    raise OSError('transient')


class RoutedModelsTests(unittest.TestCase):
    def setUp(self):
        saved = availability._SNAPSHOT
        self.addCleanup(setattr, availability, '_SNAPSHOT', saved)
        availability._SNAPSHOT = None

    def _home(self, policy=None):
        home = tmp_home(self)
        # A ChatGPT roster, so the mixed list carries a subscription row.
        (home / STATE_NAME).write_text(json.dumps({'openai_models': ['gpt-6-astra']}))
        if policy is not None:
            _write_policy(home, policy)
        catalogue.merge_file(home / 'mixed-models.json', available=None)
        return home

    def _refresh(self, home, *ids, key=KEY, opener=None):
        availability.refresh('openrouter.ai', key, home, 'global', opener or _ok(*ids))

    def _slugs(self, path):
        return {row['slug'] for row in json.loads(path.read_text())['models']}

    def _ready(self, home, key=KEY):
        with mock.patch.object(availability, 'current_key', return_value=key), \
                mock.patch.object(availability, 'current_region', return_value='global'):
            return codex_route.ready(home)

    def test_a_sync_writes_the_rows_no_subscription_mode_shows(self):
        home = self._home()
        ids = external_slugs() - {QWEN}
        self._refresh(home, *ids)
        routed = self._slugs(home / routed_models.NAME)
        self.assertTrue({FLASH, TWIN} <= routed)  # routed rows and the OpenAI twins
        self.assertNotIn(QWEN, routed)  # the key cannot use it
        self.assertFalse(routed & set(SUBSCRIPTION_SLUGS))
        self.assertIn('gpt-6-astra', self._slugs(home / 'mixed-models.json'))
        none_mode = catalogue.merge_file(home / 'none-mode.json', openai_mode='none',
                                         available=ids)
        self.assertEqual(routed, {row['slug'] for row in none_mode['models']})

    def test_the_portco_allowlist_applies_as_it_does_to_the_mixed_list(self):
        home = self._home(policy=[FLASH, TWIN])
        self._refresh(home, *external_slugs())
        self.assertEqual(self._slugs(home / routed_models.NAME), {FLASH, TWIN})

    def test_the_mixed_list_is_written_as_before(self):
        with_routed, without = self._home(), self._home()
        self._refresh(with_routed, *external_slugs())
        with mock.patch.object(routed_models, 'sync'):
            self._refresh(without, *external_slugs())
        self.assertEqual((with_routed / 'mixed-models.json').read_bytes(),
                         (without / 'mixed-models.json').read_bytes())

    def test_losing_the_snapshot_keeps_the_previous_list(self):
        # A rejected key, and a rotated key whose first refresh fails, both
        # clear the snapshot; the mixed list follows, the routed list stays.
        for key, opener in ((KEY, _denied), ('rotated-key', _down)):
            with self.subTest(key=key):
                home = self._home()
                self._refresh(home, *external_slugs())
                before = (home / routed_models.NAME).read_bytes()
                self._refresh(home, key=key, opener=opener)
                self.assertIsNone(availability.current())
                self.assertEqual((home / routed_models.NAME).read_bytes(), before)
                self.assertFalse(external_slugs() & self._slugs(home / 'mixed-models.json'))

    def test_a_list_with_no_rows_is_never_written(self):
        # A key that can use no approved row, a policy that allows none, and
        # no snapshot at all each leave nothing to show.
        for home, ids in ((self._home(), ('nobody/none',)),
                          (self._home(policy=['nobody/none']), tuple(external_slugs()))):
            with self.subTest(policy=(home / 'model-policy.json').exists()):
                self._refresh(home, *ids)
                self.assertFalse((home / routed_models.NAME).exists())
        home = self._home()
        self.assertFalse(routed_models.sync(home, None, None))
        self._refresh(home, *external_slugs())
        before = (home / routed_models.NAME).read_bytes()
        self._refresh(home, 'nobody/none')
        self.assertEqual((home / routed_models.NAME).read_bytes(), before)

    def test_ready_needs_rows_and_a_current_snapshot_for_the_installed_key(self):
        home = self._home()
        self.assertFalse(self._ready(home))  # no list yet
        self._refresh(home, *external_slugs())
        self.assertTrue(self._ready(home))  # inside the router: its live snapshot
        availability._SNAPSHOT = None  # Switch Codex asks from its own process
        self.assertTrue(self._ready(home))
        self.assertFalse(self._ready(home, key='another-key'))
        self.assertFalse(self._ready(home, key=None))
        snapshot_store.clear(home)
        self.assertFalse(self._ready(home))

    def test_ready_fails_when_the_list_names_a_model_the_snapshot_dropped(self):
        home = self._home()
        self._refresh(home, *external_slugs())
        availability._SNAPSHOT = None
        self.assertTrue(self._ready(home))
        # The key lost a model and no sync has rewritten the list yet.
        snapshot_store.write(home, availability.key_fingerprint(KEY), 'global',
                             external_slugs() - {FLASH})
        self.assertFalse(self._ready(home))

    def test_ready_fails_on_an_empty_or_malformed_list(self):
        home = self._home()
        self._refresh(home, *external_slugs())
        self.assertTrue(self._ready(home))
        for text in ('{"models": []}', 'not json', '[]', '{"models": ["x"]}'):
            with self.subTest(text=text):
                (home / routed_models.NAME).write_text(text)
                self.assertFalse(self._ready(home))


if __name__ == '__main__':
    unittest.main()
