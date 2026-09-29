"""Native session identity capture and account-change invalidation."""
import json
import contextlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.claude_profile_sync_fixtures import load_helper

identity = load_helper('claude_profile_identity')
ACCOUNT = '12345678-1234-4567-8123-123456789abc'
ORG = 'abcdefab-1234-4567-8123-123456789abc'
CLI = '87654321-1234-4567-8123-123456789abc'
HOST = 'local_12345678-abcd-4567-8123-123456789abc'


class BindingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.profile = Path(temp.name).resolve()
        self.config = self.profile / 'config.json'
        self.config.write_text(json.dumps({'lastKnownAccountUuid': ACCOUNT,
                                          'windowSizeWasSignedIn': True}))
        self.cookies = self.profile / 'Cookies'
        db = sqlite3.connect(self.cookies)
        db.execute('CREATE TABLE cookies (name TEXT, host_key TEXT, value TEXT, encrypted_value BLOB, last_update_utc INTEGER)')
        db.executemany('INSERT INTO cookies VALUES (?,?,?,?,?)', [
            ('lastActiveOrg', '.claude.ai', '', b'encrypted-org', 11644473600001000),
            ('sessionKey', '.claude.ai', '', b'synthetic-session', 11644473600001000)])
        db.commit()
        db.close()
        self.record = self.profile / 'claude-code-sessions' / ACCOUNT / ORG / (HOST + '.json')
        self.record.parent.mkdir(parents=True)
        self.record.write_text(json.dumps({'sessionId': HOST, 'cliSessionId': CLI, 'lastFocusedAt': 2}))
        self.event = {'hook_event_name': 'SessionStart', 'session_id': CLI}
        self.env = {'CLAUDE_CODE_ENTRYPOINT': 'claude-desktop', 'CLAUDE_CODE_HOST_SESSION_ID': HOST}

    def capture(self):
        return identity.capture_subscription(self.profile, self.event, self.env)

    def test_only_exact_native_session_supplies_binding_and_never_copies_cookie_values(self):
        self.assertIsNone(identity.subscription(self.profile))

        self.assertTrue(self.capture())
        self.assertEqual(identity.subscription(self.profile), (ACCOUNT, ORG))
        receipt = (self.profile / identity.BINDING).read_text()
        self.assertNotIn('encrypted-org', receipt)
        self.assertNotIn('synthetic-session', receipt)
        self.env['CLAUDE_CODE_ENTRYPOINT'] = 'cli'
        self.assertFalse(self.capture())
        self.env['CLAUDE_CODE_ENTRYPOINT'] = 'claude-desktop'
        self.event['session_id'] = ORG
        self.assertFalse(self.capture())

    def test_delayed_callback_cannot_bind_a_task_from_before_the_org_change(self):
        db = sqlite3.connect(self.cookies)
        db.execute("UPDATE cookies SET last_update_utc=11644473600003000 WHERE name='lastActiveOrg'")
        db.commit()
        db.close()
        self.assertFalse(self.capture())

    def test_v2_authentication_presence_and_removal_use_the_same_guard(self):
        with contextlib.closing(sqlite3.connect(self.cookies)) as db:
            db.execute("UPDATE cookies SET name='sessionKeyV2' WHERE name='sessionKey'")
            db.commit()
        self.assertTrue(self.capture())
        self.assertEqual(identity.subscription(self.profile), (ACCOUNT, ORG))
        self.assertNotIn('synthetic-session', (self.profile / identity.BINDING).read_text())
        with contextlib.closing(sqlite3.connect(self.cookies)) as db:
            db.execute("DELETE FROM cookies WHERE name='sessionKeyV2'")
            db.commit()
        self.assertIsNone(identity.subscription(self.profile))

    def test_cookie_timestamp_refresh_keeps_the_verified_binding(self):
        self.assertTrue(self.capture())
        with contextlib.closing(sqlite3.connect(self.cookies)) as db:
            db.execute("UPDATE cookies SET last_update_utc=11644473600003000 WHERE name='lastActiveOrg'")
            db.commit()
        self.assertEqual(identity.subscription(self.profile), (ACCOUNT, ORG))

    def test_account_logout_and_organization_changes_invalidate_without_guessing(self):
        original = self.config.read_bytes()
        for change in ({'lastKnownAccountUuid': CLI}, {'windowSizeWasSignedIn': False}):
            self.config.write_bytes(original)
            self.assertTrue(self.capture())
            doc = json.loads(original)
            doc.update(change)
            self.config.write_text(json.dumps(doc))
            self.assertIsNone(identity.subscription(self.profile))
        self.config.write_bytes(original)
        self.assertTrue(self.capture())
        db = sqlite3.connect(self.cookies)
        db.execute("UPDATE cookies SET encrypted_value=? WHERE name='lastActiveOrg'", (b'new-org',))
        db.commit()
        self.assertIsNone(identity.subscription(self.profile))
        self.assertTrue(self.capture())
        db.execute("DELETE FROM cookies WHERE name='sessionKey'")
        db.commit()
        db.close()
        self.assertIsNone(identity.subscription(self.profile))

    def test_duplicate_namespaces_and_redirected_records_cannot_bind(self):
        other = self.record.parent.parent / CLI / self.record.name
        other.parent.mkdir()
        other.write_bytes(self.record.read_bytes())
        self.assertFalse(self.capture())
        other.unlink()
        other.symlink_to(self.record)
        self.assertFalse(self.capture())

    def test_account_pair_binding_is_private_idempotent_and_never_reassigned(self):
        home = self.profile / 'router'
        home.mkdir()
        gateway = self.profile / 'gateway'
        with mock.patch.object(identity, 'subscription', return_value=(ACCOUNT, ORG)) as native, \
                mock.patch.object(identity, 'third_party', return_value=(CLI, ORG)) as third:
            self.assertTrue(identity.bind_profile_accounts(home, self.profile, gateway))
            path = home / '.claude-profile-control-accounts.json'
            before = path.read_bytes(), path.stat().st_mtime_ns
            self.assertNotIn(ACCOUNT.encode(), before[0])
            self.assertNotIn(CLI.encode(), before[0])
            self.assertTrue(identity.bind_profile_accounts(home, self.profile, gateway))
            native.return_value = (CLI, ORG)
            self.assertFalse(identity.bind_profile_accounts(home, self.profile, gateway))
            native.return_value = (ACCOUNT, ORG)
            third.return_value = (ACCOUNT, ORG)
            self.assertFalse(identity.bind_profile_accounts(home, self.profile, gateway))
            third.return_value = None
            self.assertIsNone(identity.bind_profile_accounts(home, self.profile, gateway))
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
            if identity.os.name != 'nt':
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()
