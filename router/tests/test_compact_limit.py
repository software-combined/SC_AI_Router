"""MiMo V2.6 Pro compacts before Xiaomi's long-context failures (0.6.124).

Codex only compacted MiMo Pro threads near 942,000 tokens, deep in the zone
where Xiaomi's endpoint fails about a third of long requests. The row's own
compaction limit is data: the loader accepts only a positive whole number,
and the Codex catalogue gives the limit to that row alone.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from ai_router import jev_compaction as jev, provider_defs, turn_budget
from ai_router.catalogue import merge
from ai_router.registry import FIELDS, load
from tests.test_jev_compaction import asker, history

GOOD = dict(zip(FIELDS, ['x/y', 'openrouter', 'X', 'V', ['low'], 'low',
                         ['text'], [], 'native', 'native', None, False, 1,
                         100, 32768, 'none', 'none', [], True, 'verified']))


class CompactLimitTests(unittest.TestCase):
    def test_limit_is_optional_and_must_be_a_positive_whole_number(self):
        self.assertIsNone(load(json.dumps([GOOD]))[0].auto_compact_token_limit)
        row = {**GOOD, 'auto_compact_token_limit': 400000}
        self.assertEqual(load(json.dumps([row]))[0].auto_compact_token_limit, 400000)
        for bad in (0, -1, True, '400000', 400000.5):
            with self.subTest(bad=bad), self.assertRaises(SystemExit):
                load(json.dumps([{**GOOD, 'auto_compact_token_limit': bad}]))

    def test_mimo_pro_is_the_only_catalogue_row_with_a_limit(self):
        # Flash shows no failures, so it keeps the client default, as do the
        # subscription rows.
        rows = {row['slug']: row for row in
                merge({'models': []}, roster=('gpt-6-astra',))['models']}
        mimo_pro = rows.pop('xiaomi/mimo-v2.6-pro')
        self.assertEqual(mimo_pro['auto_compact_token_limit'], 400000)
        self.assertIn('xiaomi/mimo-v2.6-flash', rows)
        self.assertIn('gpt-6-astra', rows)
        self.assertEqual({row['auto_compact_token_limit'] for row in rows.values()},
                         {None})

    def test_a_row_limit_also_caps_the_jev_result(self):
        # Above 40% of the limit the next turn would compact again at once.
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {'ROUTER_HOME': tmp}), \
                mock.patch.object(jev, 'log_event'):
            (Path(tmp) / 'jev-compaction').write_text('on')
            items = history()

            def run(limit):
                row = SimpleNamespace(context_window=10 ** 6, auto_compact_token_limit=limit)
                with mock.patch.object(jev.registry, 'by_slug', return_value=row):
                    return jev.summary('x/y', 'key', items, provider_defs.OPENROUTER,
                                       home=Path(tmp), ask=asker())
            size = len(run(None).encode())
            just_under = int(size / (turn_budget.BYTES_PER_TOKEN * .4))
            self.assertIsNone(run(just_under))
            self.assertIsNotNone(run(just_under * 2))


if __name__ == '__main__':
    unittest.main()
