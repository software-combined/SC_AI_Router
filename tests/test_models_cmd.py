"""Model onboarding command (Plan 046 Step 2). Offline fixtures only."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from ai_router import models as models_mod
from ai_router.models import (cmd_add, cmd_check, cmd_discover, cmd_list, cmd_remove,
                                 derive_row, qualify_name)

LIVE = {
    'qwen/qwen4-coder': {
        'name': 'Qwen: Qwen4 Coder',
        'architecture': {'input_modalities': ['text', 'image', 'video']},
        'context_length': 262144,
        'top_provider': {'max_completion_tokens': 65536},
        'reasoning': {'supported_efforts': ['low', 'high', 'max']},
        'pricing': {'web_search': '0.001'},
    },
    'plain/model': {
        'name': 'No Vendor Here',
        'architecture': {'input_modalities': ['text']},
        'context_length': 8192,
        'top_provider': {},
        'reasoning': {'supported_efforts': ['medium']},
        'pricing': {},
    },
}


def _seeded(tmp, rows):
    path = Path(tmp) / 'models.json'
    path.write_text(json.dumps(rows))
    return path


def _row(slug='a/b', priority=100):
    return {'slug': slug, 'provider': 'openrouter', 'display_name': 'A',
            'vendor': 'V', 'reasoning': ['low'], 'default_reasoning': 'low',
            'modalities': ['text'], 'excluded_efforts': [], 'schema_mode': 'native', 'history_mode': 'native',
            'max_tools': None, 'drop_images': False, 'context_window': 1, 'priority': priority,
            'max_output_tokens': 7, 'reasoning_summary': 'none', 'apply_patch': 'none',
            'experimental_tools': [], 'web_search': True, 'tier': 'verified', 'listed': True}


class DeriveTests(unittest.TestCase):
    def test_name_split_modalities_and_default(self):
        row = derive_row('qwen/qwen4-coder', LIVE['qwen/qwen4-coder'])
        self.assertEqual(row['display_name'], 'Qwen: Qwen4 Coder \u00b7 OpenRouter')
        self.assertEqual(row['vendor'], 'Qwen')
        self.assertEqual(row['modalities'], ['text', 'image'])
        self.assertEqual(row['default_reasoning'], 'low')
        self.assertEqual(row['reasoning'], ['low', 'high', 'max'])
        self.assertEqual(row['tier'], 'preview')
        self.assertTrue(row['web_search'])
        self.assertEqual(row['max_output_tokens'], 65536)

    def test_name_without_vendor_and_lowest_default(self):
        row = derive_row('plain/model', LIVE['plain/model'])
        self.assertEqual(row['display_name'], 'Plain: No Vendor Here \u00b7 OpenRouter')
        self.assertEqual(row['vendor'], 'Plain')
        self.assertEqual(row['default_reasoning'], 'medium')
        self.assertEqual(row['modalities'], ['text'])
        self.assertFalse(row['web_search'])

    def test_qualify_name_keeps_snapshots_and_dedupes_vendor(self):
        vendor, label = qualify_name(
            'deepseek/deepseek-v4-pro-0813',
            {'name': 'DeepSeek: DeepSeek V4 Pro 0813'})
        self.assertEqual((vendor, label), ('DeepSeek', 'DeepSeek: V4 Pro 0813'))
        vendor, label = qualify_name(
            'deepseek/deepseek-v4.1-flash',
            {'name': 'DeepSeek: DeepSeek V4.1 Flash'})
        self.assertEqual((vendor, label), ('DeepSeek', 'DeepSeek: V4.1 Flash'))

    def test_empty_reasoning_refused(self):
        live = dict(LIVE['plain/model'], reasoning={'supported_efforts': []})
        with self.assertRaises(SystemExit):
            derive_row('plain/model', live)

    def test_models_without_effort_control_use_none(self):
        for metadata in (None, {'mandatory': False}):
            with self.subTest(reasoning=metadata):
                live = dict(LIVE['plain/model'], reasoning=metadata)
                row = derive_row('plain/model', live)
                self.assertEqual(row['reasoning'], ['none'])
                self.assertEqual(row['default_reasoning'], 'none')
                self.assertEqual(row['tier'], 'preview')

    def test_mandatory_or_unknown_efforts_are_not_disabled(self):
        for metadata in ({'mandatory': True},
                         {'mandatory': False, 'supported_efforts': ['future']}):
            with self.subTest(reasoning=metadata):
                live = dict(LIVE['plain/model'], reasoning=metadata)
                with self.assertRaises(SystemExit):
                    derive_row('plain/model', live)


class AddTests(unittest.TestCase):
    def test_unknown_slug_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _seeded(tmp, [_row()])
            with self.assertRaisesRegex(SystemExit, 'not in the live'):
                cmd_add(path, 'nope/nothing', LIVE)

    def test_duplicate_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _seeded(tmp, [_row('qwen/qwen4-coder')])
            with self.assertRaisesRegex(SystemExit, 'already in'):
                cmd_add(path, 'qwen/qwen4-coder', LIVE)

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _seeded(tmp, [_row()])
            before = path.read_text()
            row = cmd_add(path, 'qwen/qwen4-coder', LIVE, dry_run=True)
            self.assertEqual(path.read_text(), before)
            self.assertEqual(row['slug'], 'qwen/qwen4-coder')

    def test_add_renumbers_into_picker_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed = {**_row('z-ai/glm-5.3', 100), 'vendor': 'Z.ai',
                    'display_name': 'Z.ai: GLM 5.3 \u00b7 OpenRouter'}
            path = _seeded(tmp, [seed])
            cmd_add(path, 'qwen/qwen4-coder', LIVE)
            rows = json.loads(path.read_text())
            self.assertEqual([row['slug'] for row in rows],
                             ['qwen/qwen4-coder', 'z-ai/glm-5.3'])
            self.assertEqual([row['priority'] for row in rows], [100, 101])

    def test_probe_activates_preview_before_verifying(self):
        with tempfile.TemporaryDirectory() as tmp:
            models_mod.COMPAT_PATH, saved = Path(tmp) / 'compatibility.md', models_mod.COMPAT_PATH
            self.addCleanup(setattr, models_mod, 'COMPAT_PATH', saved)
            path = _seeded(tmp, [_row()])
            seen = {}

            def fake_probe(slug):
                rows = json.loads(path.read_text())
                seen['during'] = next(r['tier'] for r in rows if r['slug'] == slug)
                return True

            row = cmd_add(path, 'qwen/qwen4-coder', LIVE,
                          probe=True, _probe=fake_probe)
            self.assertEqual(seen['during'], 'preview')
            self.assertEqual(row['tier'], 'verified')
            rows = json.loads(path.read_text())
            self.assertEqual(
                next(r['tier'] for r in rows if r['slug'] == 'qwen/qwen4-coder'),
                'verified')

    def test_failed_probe_keeps_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            models_mod.COMPAT_PATH, saved = Path(tmp) / 'compatibility.md', models_mod.COMPAT_PATH
            self.addCleanup(setattr, models_mod, 'COMPAT_PATH', saved)
            path = _seeded(tmp, [_row()])
            row = cmd_add(path, 'qwen/qwen4-coder', LIVE,
                          probe=True, _probe=lambda slug: False)
            self.assertEqual(row['tier'], 'preview')
            rows = json.loads(path.read_text())
            self.assertEqual(
                next(r['tier'] for r in rows if r['slug'] == 'qwen/qwen4-coder'),
                'preview')

    def test_dry_run_with_probe_neither_writes_nor_probes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _seeded(tmp, [_row()])
            before = path.read_text()

            def boom(slug):
                raise AssertionError('dry run must not bill a probe')

            row = cmd_add(path, 'qwen/qwen4-coder', LIVE,
                          dry_run=True, probe=True, _probe=boom)
            self.assertEqual(path.read_text(), before)
            self.assertEqual(row['tier'], 'preview')

    def test_add_writes_unlisted_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _seeded(tmp, [_row()])
            row = cmd_add(path, 'qwen/qwen4-coder', LIVE)
            self.assertEqual(row['tier'], 'preview')
            self.assertFalse(row['listed'])
            stored = next(r for r in json.loads(path.read_text())
                          if r['slug'] == 'qwen/qwen4-coder')
            self.assertFalse(stored['listed'])

    def test_passed_probe_promotes_to_listed_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            models_mod.COMPAT_PATH, saved = Path(tmp) / 'compatibility.md', models_mod.COMPAT_PATH
            self.addCleanup(setattr, models_mod, 'COMPAT_PATH', saved)
            path = _seeded(tmp, [_row()])
            row = cmd_add(path, 'qwen/qwen4-coder', LIVE,
                          probe=True, _probe=lambda slug: True)
            self.assertEqual(row['tier'], 'verified')
            self.assertTrue(row['listed'])
            stored = next(r for r in json.loads(path.read_text())
                          if r['slug'] == 'qwen/qwen4-coder')
            self.assertEqual(stored['tier'], 'verified')
            self.assertTrue(stored['listed'])
            compat = models_mod.COMPAT_PATH.read_text()
            self.assertIn('qwen/qwen4-coder', compat)
            self.assertIn('tool', compat)

    def test_failed_probe_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            models_mod.COMPAT_PATH, saved = Path(tmp) / 'compatibility.md', models_mod.COMPAT_PATH
            self.addCleanup(setattr, models_mod, 'COMPAT_PATH', saved)
            path = _seeded(tmp, [_row()])
            before = path.read_text()
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                row = cmd_add(path, 'qwen/qwen4-coder', LIVE,
                              probe=True, _probe=lambda slug: False)
            self.assertEqual((row['tier'], row['listed']), ('preview', False))
            stored = next(r for r in json.loads(path.read_text())
                          if r['slug'] == 'qwen/qwen4-coder')
            self.assertEqual((stored['tier'], stored['listed']), ('preview', False))
            self.assertIn('stays unlisted', buf.getvalue())

    def test_refused_probe_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            models_mod.COMPAT_PATH, saved = Path(tmp) / 'compatibility.md', models_mod.COMPAT_PATH
            self.addCleanup(setattr, models_mod, 'COMPAT_PATH', saved)
            path = _seeded(tmp, [_row()])

            def refused(slug):
                raise SystemExit('no credential')

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                row = cmd_add(path, 'qwen/qwen4-coder', LIVE,
                              probe=True, _probe=refused)
            self.assertEqual((row['tier'], row['listed']), ('preview', False))
            self.assertIn('refused', buf.getvalue())

    def test_verified_tier_without_probe_stays_unlisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _seeded(tmp, [_row()])
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                row = cmd_add(path, 'qwen/qwen4-coder', LIVE, tier='verified')
            self.assertEqual(row['tier'], 'verified')
            self.assertFalse(row['listed'])
            self.assertIn('stays unlisted', buf.getvalue())

    def test_probe_sets_tier(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _seeded(tmp, [_row()])
            saved = models_mod.COMPAT_PATH
            models_mod.COMPAT_PATH = Path(tmp) / 'compatibility.md'
            try:
                row = cmd_add(path, 'qwen/qwen4-coder', LIVE,
                              probe=True, _probe=lambda slug: True)
                self.assertEqual(row['tier'], 'verified')
                row = cmd_add(path, 'plain/model', LIVE,
                              probe=True, _probe=lambda slug: False)
                self.assertEqual(row['tier'], 'preview')
                self.assertIn('qwen/qwen4-coder', models_mod.COMPAT_PATH.read_text())
            finally:
                models_mod.COMPAT_PATH = saved


class DiscoverTests(unittest.TestCase):
    def test_discover_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _seeded(tmp, [_row('a/b', 100)])
            before = path.read_text()
            live = {'a/b': {}, 'n/e-w': {}}
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                doc = cmd_discover(path, live)
            self.assertEqual(path.read_text(), before)
            self.assertEqual(doc['addable'], ['n/e-w'])
            self.assertEqual(doc['registered'], ['a/b'])
            self.assertEqual(doc['unavailable'], [])
            self.assertEqual(doc['retired'], [])
            self.assertIn('addable', buf.getvalue())

    def test_discover_reports_unavailable_and_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _seeded(tmp, [_row('a/b', 100)])
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                doc = cmd_discover(path, {}, as_json=True)
            self.assertEqual(doc['unavailable'], ['a/b'])
            self.assertEqual(doc['registered'], [])
            parsed = json.loads(buf.getvalue())
            self.assertEqual(parsed, doc)

    def test_discover_refuses_manual_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _seeded(tmp, [_row('a/b', 100)])
            with self.assertRaises(SystemExit):
                cmd_discover(path, {}, provider_id='openai')


class RemoveTests(unittest.TestCase):
    def test_missing_refused_and_present_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _seeded(tmp, [_row('a/b')])
            with self.assertRaisesRegex(SystemExit, 'not in'):
                cmd_remove(path, 'zzz/q')
            cmd_remove(path, 'a/b')
            self.assertEqual(json.loads(path.read_text()), [])


class CheckTests(unittest.TestCase):
    def test_duplicates_and_live_gap_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = [_row('a/b', 100), _row('a/b', 100)]
            path = _seeded(tmp, rows)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = cmd_check(path, {'a/b': {}})
            self.assertEqual(rc, 1)
            self.assertIn('duplicate slug', buf.getvalue())
            self.assertIn('duplicate priority', buf.getvalue())
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = cmd_check(path, {})
            self.assertEqual(rc, 1)
            self.assertIn('not in live list', buf.getvalue())

    def test_clean_offline_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _seeded(tmp, [_row('a/b', 100), _row('c/d', 101)])
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = cmd_check(path, None)
            self.assertEqual(rc, 0)
            self.assertIn('0 problems', buf.getvalue())

    def test_out_of_order_priorities_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _seeded(tmp, [_row('b/b', 100), _row('a/a', 101)])
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = cmd_check(path, None)
            self.assertEqual(rc, 1)
            self.assertIn('priorities not in picker order', buf.getvalue())


class ListTests(unittest.TestCase):
    def test_list_prints_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _seeded(tmp, [_row('a/b', 100)])
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                cmd_list(path)
            self.assertIn('a/b', buf.getvalue())
            self.assertIn('tier=verified', buf.getvalue())


if __name__ == '__main__':
    unittest.main()
