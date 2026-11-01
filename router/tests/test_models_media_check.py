"""Chat catalogue checks must not reject hand-authored media API rows."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from ai_router.models import cmd_check
from tests.test_models_cmd import _row


class MediaCheckTests(unittest.TestCase):
    def test_missing_chat_fails_but_media_outside_chat_catalogue_passes(self):
        for kind in ('image', 'video'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                media = {**_row('a/media', 101), 'media_kind': kind,
                         'tier': 'preview', 'listed': False,
                         'reasoning': ['none'], 'default_reasoning': 'none'}
                chat = _row('a/text', 100)
                path = Path(tmp) / 'models.json'
                path.write_text(json.dumps([media, chat]))
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(cmd_check(path, {'a/text': {}}), 0)
                self.assertIn('0 problems', output.getvalue())
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(cmd_check(path, {}), 1)
                self.assertIn('not in live list: a/text', output.getvalue())
                self.assertNotIn('a/media', output.getvalue())
