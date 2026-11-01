"""Installation and stale replies must never report completed staff setup."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from tests.test_native_setup import module

readiness = module('native_readiness')
delivery = module('install_delivery')


class ReadinessTests(unittest.TestCase):
    def test_only_a_new_successful_reply_for_the_selected_assistant_counts(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / 'logs').mkdir()
            rows = [dict(event='request_completed', protocol='responses', status=200,
                         ts='2020-01-01T00:00:00+00:00'),
                    dict(event='request_failed', protocol='messages', status=500,
                         ts=datetime.now(timezone.utc).isoformat())]
            log = home / 'logs/router.jsonl'
            log.write_text('\n'.join(map(json.dumps, rows)))
            self.assertFalse(readiness.successful_reply(home, 1700000000, 'codex'))
            self.assertFalse(readiness.successful_reply(home, 1700000000, 'claude'))
            rows.append(dict(event='request_completed', protocol='messages', status=200,
                             ts=datetime.now(timezone.utc).isoformat()))
            log.write_text('\n'.join(map(json.dumps, rows)))
            self.assertTrue(readiness.successful_reply(home, 1700000000, 'claude-desktop'))
            self.assertFalse(readiness.successful_reply(home, 1700000000, 'codex'))

    def test_missing_plugin_is_pending_but_intentionally_disabled_plugin_is_preserved(self):
        names = ['scg-documentation', 'scg-review']
        def runner(command, **kwargs):
            entries = [{'pluginId': name + '@scg-agent-plugins', 'enabled': False}
                       for name in names]
            return SimpleNamespace(returncode=0, stdout=json.dumps({'installed': entries}))
        self.assertTrue(readiness.plugins_available(
            'codex', names, run=runner, which=lambda *a, **k: '/client'))
        self.assertFalse(readiness.plugins_available(
            'codex', names + ['missing'], run=runner, which=lambda *a, **k: '/client'))

    def test_desktop_receipt_and_additive_attachment_drive_delivery(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            receipts = module('codex_config')
            receipts._replace_text = module('atomic_write').replace_text
            receipts.write_client_receipt(home, 'claude-desktop', {})
            self.assertEqual(delivery.clients(home, {'clients': 'none'}), ['claude'])
            receipts.write_client_receipt(home, 'codex', {})
            self.assertEqual(delivery.clients(home, {'clients': 'codex'}), ['codex', 'claude'])


if __name__ == '__main__':
    unittest.main()
