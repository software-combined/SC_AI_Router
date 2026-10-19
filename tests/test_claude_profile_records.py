"""Profile-root, namespace and record grouping contracts."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import claude_profile_sync_fixtures as fixtures
from tests._platform import symlink_or_skip


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'claude_profile_records', ROOT / 'packaging' / 'claude_profile_records.py')
records = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(records)


class ProfileRecordsTests(unittest.TestCase):
    def setUp(self):
        provider = mock.patch.object(records._identity, 'subscription',
                                     side_effect=fixtures.subscription_identity)
        provider.start()
        self.addCleanup(provider.stop)

    def test_profile_roots_follow_each_platform(self):
        cases = (
            ('darwin', {}, ('Library', 'Application Support', 'Claude'),
             ('Library', 'Application Support', 'Claude-3p')),
            ('win32', {'APPDATA': '/appdata', 'LOCALAPPDATA': '/local'},
             ('appdata', 'Claude'), ('local', 'Claude-3p')),
            ('linux', {'XDG_CONFIG_HOME': '/xdg'},
             ('xdg', 'Claude'), ('xdg', 'Claude-3p')),
        )
        for platform_name, env, first_tail, third_tail in cases:
            with self.subTest(platform=platform_name), mock.patch.object(
                    Path, 'home', return_value=Path('/home/user')):
                first, third = records.profile_roots(env, platform_name)
                self.assertEqual(tuple(first.parts[-len(first_tail):]), first_tail)
                self.assertEqual(tuple(third.parts[-len(third_tail):]), third_tail)

    def test_override_moves_only_third_party_profile(self):
        with mock.patch.object(Path, 'home',
                              return_value=Path('/home/user')):
            first, third = records.profile_roots(
                {'CLAUDE_USER_DATA_DIR': '/custom/third'}, 'linux')
        self.assertEqual(first, Path('/home/user/.config/Claude'))
        self.assertEqual(third, Path('/custom/third'))

    def test_receipt_supplies_third_party_path_and_refuses_disagreement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            home = root / 'router'
            third = root / 'attached'
            entry = third / 'configLibrary' / 'id.json'
            entry.parent.mkdir(parents=True)
            entry.write_text('{}')
            home.mkdir()
            (home / 'activation.json').write_text(json.dumps({
                'clients': {'claude-desktop': {'config_path': str(entry)}}}))
            with mock.patch.object(Path, 'home', return_value=root / 'user'):
                _first, got = records.profile_roots({}, 'linux', home)
                self.assertEqual(got, third)
                with self.assertRaisesRegex(ValueError, 'disagrees'):
                    records.profile_roots(
                        {'CLAUDE_USER_DATA_DIR': str(root / 'other')},
                        'linux', home)

    def test_store_namespaces_keep_distinct_layouts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_path = fixtures.profile(
                root, 'Claude', '12345678-1234-4567-8123-123456789abc', 'abcdefab-1234-4567-8123-123456789abc')
            local = fixtures.namespace(
                profile_path, 'local-agent-mode-sessions',
                '12345678-1234-4567-8123-123456789abc', 'abcdefab-1234-4567-8123-123456789abc')
            code = fixtures.namespace(
                profile_path, 'claude-code-sessions',
                '12345678-1234-4567-8123-123456789abc', 'abcdefab-1234-4567-8123-123456789abc')
            self.assertEqual(local.parts[-2:], ('12345678', 'abcdefab'))
            self.assertEqual(code.parts[-2:],
                             ('12345678-1234-4567-8123-123456789abc', 'abcdefab-1234-4567-8123-123456789abc'))
            for store in fixtures.STORES:
                with self.subTest(store=store):
                    got = records.resolve_namespace(
                        profile_path / store, profile_path)
                    self.assertEqual(got[1],
                                     fixtures.namespace(
                                         profile_path, store,
                                         '12345678-1234-4567-8123-123456789abc', 'abcdefab-1234-4567-8123-123456789abc'))

    def test_invalid_attachment_receipt_never_falls_back_to_another_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            env = {'XDG_CONFIG_HOME': str(home / 'profiles')}
            expected = home / 'profiles/Claude-3p'
            self.assertEqual(records.profile_roots(env, 'linux', home)[1], expected)
            receipt = home / 'activation.json'
            receipt.write_text('{"clients": {"codex": {}}}')
            self.assertEqual(records.profile_roots(env, 'linux', home)[1], expected)
            for text in ('{', '{"clients": []}',
                         '{"clients": {"claude-desktop": {}}}',
                         '{"clients": {"claude-desktop": {"config_path": "relative"}}}'):
                receipt.write_text(text)
                before = fixtures.fingerprint(home)
                with self.subTest(receipt=text), self.assertRaises(ValueError):
                    records.profile_roots(env, 'linux', home)
                self.assertEqual(fixtures.fingerprint(home), before)

    def test_missing_or_ambiguous_identity_never_creates_a_namespace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_path = fixtures.profile(
                root, 'Claude', '12345678-1234-4567-8123-123456789abc', 'abcdefab-1234-4567-8123-123456789abc')
            store = profile_path / 'claude-code-sessions'
            self.assertIsNotNone(records.resolve_namespace(store, profile_path))
            fixtures.namespace(profile_path, 'claude-code-sessions',
                               '12345678-1234-4567-8123-123456789abc', 'org-one')
            fixtures.namespace(profile_path, 'claude-code-sessions',
                               '12345678-1234-4567-8123-123456789abc', 'org-two')
            self.assertIsNone(records.resolve_namespace(store, profile_path))
            self.assertEqual(len(records.namespace_paths(store)), 2)

    def test_full_uuid_local_namespace_is_selected_without_creating_short_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            account = '12345678-1234-4567-8123-123456789abc'
            org = 'abcdefab-1234-4567-8123-123456789abc'
            profile = fixtures.profile(tmp, 'Claude', account, org)
            store = profile / 'local-agent-mode-sessions'
            expected = store / account / org
            self.assertEqual(records.resolve_namespace(store, profile), (expected.parent, expected))
            expected.mkdir(parents=True)
            self.assertEqual(records.resolve_namespace(store, profile), (expected.parent, expected))
            self.assertFalse((store / account[:8]).exists())

    def test_cached_account_and_existing_history_do_not_prove_current_organization(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = fixtures.profile(tmp, 'Claude', 'account', 'org')
            for store in fixtures.STORES:
                fixtures.record(profile, store, 'account', 'org', 'existing')
            (profile / 'config.json').write_text('{"lastKnownAccountUuid":"account"}')
            before = fixtures.fingerprint(profile)
            for store in fixtures.STORES:
                self.assertIsNone(records.resolve_namespace(profile / store, profile))
            self.assertEqual(fixtures.fingerprint(profile), before)

    def test_records_group_by_session_id_not_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile_path = fixtures.profile(
                tmp, 'Claude', '12345678-1234-4567-8123-123456789abc', 'abcdefab-1234-4567-8123-123456789abc')
            fixtures.record(profile_path, 'claude-code-sessions',
                            '12345678-1234-4567-8123-123456789abc', 'abcdefab-1234-4567-8123-123456789abc', 'same',
                            filename='local_one.json')
            fixtures.record(profile_path, 'claude-code-sessions',
                            '12345678-1234-4567-8123-123456789abc', 'abcdefab-1234-4567-8123-123456789abc', 'same',
                            filename='local_two.json')
            groups = records.group_records(
                profile_path / 'claude-code-sessions')
            self.assertEqual([path.name for path in groups['same']],
                             ['local_one.json', 'local_two.json'])

    def test_actual_selector_uses_stable_equal_copy_not_incoming_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile_path = fixtures.profile(
                tmp, 'Claude', '12345678-1234-4567-8123-123456789abc', 'abcdefab-1234-4567-8123-123456789abc')
            store = profile_path / 'claude-code-sessions'
            fixtures.duplicate(profile_path, 'claude-code-sessions',
                               '12345678-1234-4567-8123-123456789abc', 'abcdefab-1234-4567-8123-123456789abc', 'same',
                               'one', title='same')
            fixtures.duplicate(profile_path, 'claude-code-sessions',
                               '12345678-1234-4567-8123-123456789abc', 'abcdefab-1234-4567-8123-123456789abc', 'same',
                               'two', title='same')
            namespace = records.resolve_namespace(store, profile_path)
            existing, _doc = fixtures.sync._choose(records.group_records(store)['same'], namespace)
            self.assertEqual(existing.name, 'local_one.json')

    def test_first_party_environment_override_is_ignored(self):
        first, _ = records.profile_roots({'XDG_CONFIG_HOME': '/native',
                                         'CLAUDE_FIRST_PARTY_DATA_DIR': '/untrusted'}, 'linux')
        self.assertEqual(first, Path('/native/Claude'))

    def test_nonregular_configuration_is_refused_before_open(self):
        import os
        if not hasattr(os, 'mkfifo'):
            self.skipTest('POSIX FIFO')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp).resolve() / 'config.json'
            os.mkfifo(path)
            with mock.patch.object(Path, 'read_text', side_effect=AssertionError('must not open')):
                with self.assertRaises(ValueError):
                    records.read_json(path)

    def test_root_and_ancestor_symlinks_are_refused_before_namespace_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            target = fixtures.profile(root, 'Claude', 'account', 'org')
            link = root / 'link'
            symlink_or_skip(target, link, target_is_directory=True)
            for store in (link, link / 'claude-code-sessions'):
                with self.assertRaises(ValueError):
                    records.namespace_paths(store)
            with self.assertRaises(ValueError):
                records.assert_target(link / 'new', link)
            self.assertFalse((target / 'new').exists())

    def test_unsupported_target_identity_schema_remains_unresolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            profile = fixtures.profile(root, 'Claude', 'account', 'org')
            for value in ({'oauthAccount': []}, {'oauthAccount': 'account'},
                          {'accountName': 'display', 'emailAddress': 'test@example.invalid'},
                          {'lastKnownAccountUuid': [], 'lastKnownOrganizationUuid': {}}, {}):
                (profile / 'config.json').write_text(json.dumps(value))
                for store in fixtures.STORES:
                    self.assertIsNone(records.resolve_namespace(profile / store, profile))
                    self.assertFalse((profile / store).exists())


if __name__ == '__main__':
    unittest.main()
