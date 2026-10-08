"""Media rows preserve the registry's optional-field and preview contracts."""
import json
import unittest

from ai_router.registry import FIELDS, MODELS, Model, load


class MediaRegistryTests(unittest.TestCase):
    def test_media_kind_defaults_none_and_validates(self):
        self.assertIsNone(Model(slug='x/y', provider='openrouter', display_name='X',
                                vendor='V', reasoning=('low',),
                                default_reasoning='low').media_kind)
        good = dict(zip(FIELDS, ['x/y', 'openrouter', 'X', 'V',
            ['low'], 'low', ['text'], [], 'native', 'native', None, False, 1,
            100, 32768, 'none', 'none', [], True, 'verified']))
        for kind in ('image', 'video'):
            self.assertEqual(load(json.dumps([{**good, 'media_kind': kind}]))[0].media_kind, kind)
        with self.assertRaises(SystemExit):
            load(json.dumps([{**good, 'media_kind': 'audio'}]))
        media = [m for m in MODELS if m.media_kind is not None]
        self.assertTrue(media)
        for model in media:
            self.assertFalse(model.listed)
            self.assertEqual(model.tier, 'preview')
