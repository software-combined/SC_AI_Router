"""Private release downloads use gh credentials only for this repository."""
import subprocess
import unittest
from unittest import mock

from tests.test_install import install_mod

svc = install_mod._svc
PREFIX = 'https://github.com/software-combined/SC_OpenRouter_adapter/releases/'


class PrivateUpdateTests(unittest.TestCase):
    def test_latest_feed_and_versioned_bundle_use_authenticated_cli(self):
        for suffix, tag in [('latest/download/latest.json', None),
                            ('download/v0.6.7.19/codex-model-router-0.6.7.19.tar.gz', 'v0.6.7.19')]:
            with self.subTest(tag=tag), mock.patch.object(svc.shutil, 'which', return_value='/usr/bin/gh'), \
                    mock.patch.object(svc, 'run', return_value=subprocess.CompletedProcess(
                        [], 0, b'asset bytes', b'')) as run, \
                    mock.patch.object(svc.urllib.request, 'urlopen', side_effect=AssertionError('anonymous fetch')):
                self.assertEqual(svc.fetch(PREFIX + suffix), b'asset bytes')
                cmd = run.call_args.args[0]
                self.assertEqual(cmd[:5], ['/usr/bin/gh', 'release', 'download', '--repo',
                                          'software-combined/SC_OpenRouter_adapter'])
                self.assertIn(suffix.split('/')[-1], cmd)
                self.assertEqual(cmd[-2:], ['--', tag] if tag else ['--output', '-'])

    def test_scheduled_feed_uses_same_authenticated_fetch(self):
        with mock.patch.object(svc.urllib.request, 'urlopen', side_effect=AssertionError('anonymous fetch')):
            seen = []
            def fetch(url):
                seen.append(url)
                return b'feed'
            self.assertEqual(svc.fetch_feed(PREFIX + 'latest/download/latest.json', 'old', fetch),
                             (200, b'feed', 'old'))
            self.assertEqual(seen, [PREFIX + 'latest/download/latest.json'])

    def test_other_hosts_and_repositories_never_use_github_login(self):
        with mock.patch.object(svc, 'run', side_effect=AssertionError('credential use')):
            for url in ['https://example.com/asset',
                        'https://github.com/other/repository/releases/latest/download/latest.json']:
                self.assertIsNone(svc.github_asset(url))

    def test_auth_failure_has_actionable_nonsecret_error(self):
        with mock.patch.object(svc.shutil, 'which', return_value='/usr/bin/gh'), \
                mock.patch.object(svc, 'run', return_value=subprocess.CompletedProcess(
                    [], 1, b'', b'private diagnostic')):
            with self.assertRaisesRegex(SystemExit, 'check gh auth status') as err:
                svc.fetch(PREFIX + 'latest/download/latest.json')
            self.assertNotIn('private diagnostic', str(err.exception))

    def test_missing_cli_and_wildcard_asset_are_rejected(self):
        with mock.patch.object(svc.shutil, 'which', return_value=None), \
                mock.patch.object(svc.Path, 'is_file', return_value=False):
            with self.assertRaisesRegex(SystemExit, 'require GitHub CLI'):
                svc.fetch(PREFIX + 'latest/download/latest.json')
        with self.assertRaisesRegex(SystemExit, 'invalid router release asset'):
            svc.fetch(PREFIX + 'latest/download/*')
