"""The current DeepSeek Flash snapshot replaces its retired picker entry."""
from dataclasses import replace
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from ai_router import (catalogue, claude, compaction_summary, model_refresh, models,
                       providers, registry, request_context)
from ai_router.clients import visible_for
from tests.harness import stub_credentials


NEW = 'deepseek/deepseek-v4.1-flash-1017'
OLD = 'deepseek/deepseek-v4.1-flash'


class DeepSeekSnapshotRegistryTests(unittest.TestCase):
    def test_only_hidden_retired_rows_may_share_a_provider_target(self):
        rows = {row['slug']: row for row in json.loads(models.MODELS_PATH.read_text())}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'models.json'
            for changes, expected in (({}, 0), ({'listed': True}, 1),
                                      ({'slug': 'other/alias'}, 1)):
                with self.subTest(changes=changes), contextlib.redirect_stdout(io.StringIO()):
                    path.write_text(json.dumps([rows[NEW], {**rows[OLD], **changes}]))
                    self.assertEqual(models.cmd_check(path, {NEW: {}}), expected)

    def test_snapshot_is_pinned_for_both_clients(self):
        row = registry.by_slug(NEW)
        self.assertIsNotNone(row)
        self.assertEqual(registry.upstream_id_for(row), NEW)
        self.assertEqual(row.display_name, 'DeepSeek: V4.1 Flash 1017 · OpenRouter')
        self.assertEqual(row.context_window, 1048576)
        self.assertEqual(row.max_output_tokens, 393216)
        self.assertEqual(row.modalities, ('text', 'image'))
        self.assertEqual(row.default_reasoning, 'low')
        for client in ('codex', 'claude'):
            self.assertTrue(visible_for(row, client), client)

    def test_stale_model_cache_keeps_the_hidden_compatibility_target(self):
        current = registry.by_slug(NEW)
        compatibility = registry.by_slug(OLD)
        self.assertIsNotNone(compatibility)
        stale = replace(current, slug=OLD, listed=True,
                        observed_item_types=('compaction',))
        rows = model_refresh.overlay((current, compatibility), (stale,))
        restored = next(row for row in rows if row.slug == OLD)
        self.assertEqual(restored, compatibility)
        self.assertEqual(registry.upstream_id_for(restored), NEW)
        self.assertIn(OLD, catalogue.RETIRED_SLUGS)
        for client in ('codex', 'claude'):
            self.assertFalse(visible_for(restored, client), client)
        self.assertNotIn(OLD, {row['slug'] for row in
                              catalogue.merge({'models': [{'slug': OLD}]})['models']})

    def test_saved_old_model_requests_use_the_new_snapshot_on_both_routes(self):
        context = request_context.resolve(OLD, request_context.capture())
        for select, path, content in (
                (providers.select, '/responses', {'input': 'Continue the saved task.'}),
                (claude.select, '/v1/messages', {'messages': [
                    {'role': 'user', 'content': 'Continue the saved task.'}]})):
            with self.subTest(path=path):
                payload = {'model': OLD, **content}
                adapter = select(OLD, path, catalogue=context.catalogue)
                prepared = adapter.prepare(OLD, path, payload, json.dumps(payload).encode(),
                                           {}, stub_credentials(), context=context)
                self.assertEqual(json.loads(prepared.body)['model'], NEW)
                self.assertEqual(payload['model'], OLD)

    def test_compaction_uses_the_new_snapshot_without_old_measurements(self):
        self.assertIn(NEW, compaction_summary.SUMMARY_MODEL_SLUGS)
        self.assertNotIn(OLD, compaction_summary.SUMMARY_MODEL_SLUGS)
        row = registry.by_slug(NEW)
        self.assertIsNotNone(row)
        self.assertEqual(row.observed_item_types, ())
