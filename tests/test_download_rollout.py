"""Publishing native sign-in settings must not enrol routine update clients."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_download_auth import CONFIG, load
from tests.test_workflows import ROOT, run_block


@unittest.skipUnless(os.name == 'posix' and shutil.which('bash'),
                     'release workflow runs on Ubuntu')
class DownloadRolloutTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name)
        (self.work / 'packaging').symlink_to(ROOT / 'packaging', target_is_directory=True)
        bin_dir = self.work / 'bin'
        bin_dir.mkdir()
        (bin_dir / 'python').symlink_to(sys.executable)
        self.env = {**os.environ,
                    'PATH': f'{bin_dir}{os.pathsep}{os.environ["PATH"]}',
                    'GITHUB_RUN_NUMBER': '42', 'GITHUB_SHA': 'a' * 40,
                    'GITHUB_ENV': str(self.work / 'env'),
                    'GITHUB_SERVER_URL': 'https://github.com',
                    'GITHUB_REPOSITORY': 'example/router',
                    'DOWNLOAD_AUTH_CONFIG': json.dumps(CONFIG),
                    'DOWNLOAD_AUTH_ENROLMENT': ''}

    def build(self, suffix='', **settings):
        version = (ROOT / 'packaging/VERSION').read_text().strip()
        env = {**self.env, 'GITHUB_REF_NAME': f'v{version}{suffix}', **settings}
        result = subprocess.run(['bash', '-e', '-c', run_block('Build bundle')],
                                cwd=self.work, env=env, capture_output=True, text=True)
        return result, self.work / 'dist'

    def test_native_config_does_not_enrol_stable_beta_or_express_clients(self):
        enrolment = load('rollout_enrolment', 'packaging/download_enrolment.py')
        for suffix in ('', '-beta', '-express', '-beta-express'):
            with self.subTest(suffix=suffix):
                result, dist = self.build(suffix)
                self.assertEqual(result.returncode, 0, result.stderr)
                latest = json.loads((dist / 'latest.json').read_text())
                self.assertNotIn('download_auth', latest)
                self.assertEqual(json.loads((dist / 'download-auth.json').read_text()), CONFIG)
                home = self.work / 'legacy-home'
                self.assertFalse(enrolment.accept(home, latest.get('download_auth')))
                self.assertFalse((home / 'download-auth.json').exists())

    def test_explicit_enrolment_keeps_the_existing_sign_in_requirement(self):
        result, dist = self.build('-beta', DOWNLOAD_AUTH_ENROLMENT='true')
        self.assertEqual(result.returncode, 0, result.stderr)
        latest = json.loads((dist / 'latest.json').read_text())
        self.assertEqual(latest['download_auth'], CONFIG)
        home = self.work / 'enrolled-home'
        home.mkdir()
        enrolment = load('required_enrolment', 'packaging/download_enrolment.py')
        feed = load('required_feed', 'packaging/feed.py')
        self.assertTrue(enrolment.accept(home, latest['download_auth']))
        feed.configure_home(home)
        with self.assertRaises(feed.SignInRequired):
            feed._request(feed.FEED_URL)

    def test_build_without_enrolment_does_not_clear_existing_access_state(self):
        result, dist = self.build(DOWNLOAD_AUTH_ENROLMENT='false')
        self.assertEqual(result.returncode, 0, result.stderr)
        latest = json.loads((dist / 'latest.json').read_text())
        home = self.work / 'existing-home'
        home.mkdir()
        saved = json.dumps(CONFIG)
        (home / 'download-auth.json').write_text(saved)
        enrolment = load('existing_enrolment', 'packaging/download_enrolment.py')
        self.assertFalse(enrolment.accept(home, latest.get('download_auth')))
        self.assertEqual((home / 'download-auth.json').read_text(), saved)
        feed = load('existing_feed', 'packaging/feed.py')
        feed.configure_home(home)
        with self.assertRaises(feed.SignInRequired):
            feed._request(feed.FEED_URL)

    def test_native_builder_retains_sign_in_config_without_update_enrolment(self):
        result, dist = self.build('-beta')
        self.assertEqual(result.returncode, 0, result.stderr)
        latest = json.loads((dist / 'latest.json').read_text())
        self.assertNotIn('download_auth', latest)
        builder = load('rollout_native_builder', 'tools/build_release_installer.py')
        def check_native_command(command, **kwargs):
            config = Path(command[command.index('--download-config') + 1])
            self.assertEqual(json.loads(config.read_text()), CONFIG)
        with mock.patch.object(builder, 'download', return_value=self.work / 'runtime'), \
                mock.patch.object(builder.subprocess, 'run', side_effect=check_native_command) as run:
            builder.main(['--target', 'darwin/arm64', '--dist', str(dist),
                          '--out', str(self.work / 'native')])
        run.assert_called_once()

    def test_invalid_enrolment_setting_and_missing_config_stop_the_build(self):
        for settings in ({'DOWNLOAD_AUTH_ENROLMENT': 'yes'},
                         {'DOWNLOAD_AUTH_ENROLMENT': 'true', 'DOWNLOAD_AUTH_CONFIG': ''}):
            with self.subTest(settings=settings):
                result, dist = self.build(**settings)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((dist / 'latest.json').exists())


if __name__ == '__main__':
    unittest.main()
