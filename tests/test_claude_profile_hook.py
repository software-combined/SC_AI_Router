"""Automatic identity setup preserves user hooks and stays non-blocking."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.claude_profile_sync_fixtures import load_helper

hook = load_helper('claude_profile_hook')


class HookTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name).resolve() / 'router'
        self.home.mkdir()
        self.settings = self.home.parent / 'claude/settings.json'
        self.settings.parent.mkdir()
        self.env = {'CLAUDE_CONFIG_DIR': str(self.settings.parent)}
        self.user_hook = {'hooks': [{'type': 'command', 'command': 'user-command'}]}
        self.settings.write_text(json.dumps({'hooks': {'SessionStart': [self.user_hook]},
                                             'env': {'KEEP': 'user'}}))

    def test_install_upgrade_and_detach_keep_unrelated_settings(self):
        hook.install(self.home, '/python', self.env)
        first = self.settings.read_bytes()
        hook.install(self.home, '/python', self.env)
        self.assertEqual(self.settings.read_bytes(), first)
        hook.install(self.home, '/new-python', self.env)
        doc = json.loads(self.settings.read_text())
        entries = doc['hooks']['SessionStart']
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0], self.user_hook)
        self.assertTrue(entries[1]['hooks'][0]['async'])
        self.assertIn('/new-python', entries[1]['hooks'][0]['command'])
        doc['userAdded'] = True
        self.settings.write_text(json.dumps(doc))
        hook.uninstall(self.home)
        self.assertEqual(json.loads(self.settings.read_text()), {
            'hooks': {'SessionStart': [self.user_hook]}, 'env': {'KEEP': 'user'},
            'userAdded': True})
        hook.uninstall(self.home)

    def test_preexisting_identical_callback_is_not_owned_or_replaced(self):
        hook.install(self.home, '/python', self.env)
        original = json.loads(self.settings.read_text())['hooks']['SessionStart'][1]
        (self.home / hook.RECEIPT).unlink()
        hook.install(self.home, '/python', self.env)
        hook.install(self.home, '/different-python', self.env)
        hook.uninstall(self.home)
        self.assertEqual(json.loads(self.settings.read_text())['hooks']['SessionStart'],
                         [self.user_hook, original])

    def test_detach_preserves_exact_user_bytes_and_missing_settings_can_retry(self):
        hook.install(self.home, '/python', self.env)
        entry = json.loads((self.home / hook.RECEIPT).read_text())['entry']
        before = ('{\r\n "hooks" : {"SessionStart": [' + json.dumps(entry)
                  + ', { "keep" : [1,  2] }]}, "other" : "\\u00e9"\r\n}\r\n')
        self.settings.write_bytes(before.encode())
        receipt = self.home / hook.RECEIPT
        receipt.write_bytes(receipt.read_bytes().replace(b'\n', b'\r\n'))
        hook.uninstall(self.home)
        self.assertEqual(self.settings.read_bytes(),
                         b'{\r\n "hooks" : {"SessionStart": [{ "keep" : [1,  2] }]}, "other" : "\\u00e9"\r\n}\r\n')
        hook.install(self.home, '/python', self.env)
        self.settings.unlink()
        hook.uninstall(self.home)
        self.assertFalse(self.settings.exists())
        self.assertFalse((self.home / hook.RECEIPT).exists())

    def test_native_callback_waits_for_publication_but_stops_on_identity_change(self):
        guard = {'account': 'a', 'organization_cookie': 'one'}
        env = {'CLAUDE_CODE_ENTRYPOINT': 'claude-desktop'}
        with mock.patch.object(hook._identity, '_subscription_guard', return_value=guard), \
                mock.patch.object(hook._identity, 'capture_subscription', side_effect=[False, True]) as capture, \
                mock.patch.object(hook.time, 'sleep'):
            self.assertTrue(hook.capture({}, env))
            self.assertEqual(capture.call_count, 2)
        with mock.patch.object(hook._identity, '_subscription_guard', side_effect=[
                guard, {'account': 'a', 'organization_cookie': 'two'}]), \
                mock.patch.object(hook._identity, 'capture_subscription') as capture:
            self.assertFalse(hook.capture({}, env))
            capture.assert_not_called()

    def test_failed_capture_is_bounded_and_silent(self):
        guard = {'account': 'a', 'organization_cookie': 'one'}
        with mock.patch.object(hook._identity, '_subscription_guard', return_value=guard), \
                mock.patch.object(hook._identity, 'capture_subscription', return_value=False) as capture, \
                mock.patch.object(hook.time, 'sleep'):
            self.assertFalse(hook.capture({}, {'CLAUDE_CODE_ENTRYPOINT': 'claude-desktop'}))
            self.assertEqual(capture.call_count, 20)
        with mock.patch.object(hook.sys, 'stdin', io.StringIO('{not-json')), \
                mock.patch.object(hook.sys, 'stdout', io.StringIO()) as out:
            hook.main([])
            self.assertEqual(out.getvalue(), '')


if __name__ == '__main__':
    unittest.main()
