"""Publishing native sign-in settings must not enrol routine update clients."""
import json
import os
import shutil
import subprocess
import sys
import tarfile
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
                self.assertFalse((dist / 'download-auth.json').exists())
                home = self.work / 'legacy-home'
                self.assertFalse(enrolment.accept(home, latest.get('download_auth')))
                self.assertFalse((home / 'download-auth.json').exists())

    def test_existing_auth_state_does_not_require_credentials_for_downloads(self):
        home = self.work / 'existing-home'
        home.mkdir()
        saved = '{old or corrupt authentication settings'
        (home / 'download-auth.json').write_text(saved)
        feed = load('public_rollout_feed', 'packaging/feed.py')
        feed.configure_home(home)
        with mock.patch.object(feed._auth, 'ensure_access') as signin:
            for suffix in ('stable/latest.json', 'stable/latest.json.sig',
                           'bundles/release.tar.gz', 'stable/models.json'):
                request = feed._request(feed.FEED_ORIGIN + '/' + suffix)
                self.assertIsNone(request.get_header('Cookie'))
                self.assertIsNone(request.get_header('Authorization'))
        signin.assert_not_called()
        self.assertEqual((home / 'download-auth.json').read_text(), saved)

    def test_native_builder_ignores_legacy_auth_metadata_and_sidecar(self):
        result, dist = self.build('-beta')
        self.assertEqual(result.returncode, 0, result.stderr)
        latest_path = dist / 'latest.json'
        latest = json.loads(latest_path.read_text())
        latest['download_auth'] = CONFIG
        latest_path.write_text(json.dumps(latest))
        (dist / 'download-auth.json').write_text(json.dumps(CONFIG))
        builder = load('public_native_builder', 'tools/build_release_installer.py')
        with mock.patch.object(builder, 'download', return_value=self.work / 'runtime'), \
                mock.patch.object(builder.subprocess, 'run') as run:
            builder.main(['--target', 'darwin/arm64', '--dist', str(dist),
                          '--out', str(self.work / 'native')])
        run.assert_called_once()
        self.assertNotIn('--download-config', run.call_args.args[0])

    def test_reused_build_removes_only_the_generated_auth_sidecar(self):
        result, dist = self.build('-beta')
        self.assertEqual(result.returncode, 0, result.stderr)
        (dist / 'download-auth.json').write_text(json.dumps(CONFIG))
        unrelated = dist / 'operator-notes.txt'
        unrelated.write_text('preserve')
        result, dist = self.build('-beta', DOWNLOAD_AUTH_CONFIG='')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('download_auth', json.loads((dist / 'latest.json').read_text()))
        self.assertFalse((dist / 'download-auth.json').exists())
        self.assertEqual(unrelated.read_text(), 'preserve')

    def test_legacy_repository_settings_cannot_enrol_public_clients(self):
        result, dist = self.build(DOWNLOAD_AUTH_ENROLMENT='true')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('download_auth', json.loads((dist / 'latest.json').read_text()))
        self.assertFalse((dist / 'download-auth.json').exists())

    def test_retired_release_cli_options_are_refused(self):
        release = load('public_release_cli', 'packaging/release.py')
        with self.assertRaises(SystemExit), mock.patch('sys.stderr'):
            release.main(['--out', str(self.work / 'dist'), '--enrol-downloads'])

    def test_verified_public_controller_recovers_an_enrolled_installation(self):
        result, dist = self.build('-beta')
        self.assertEqual(result.returncode, 0, result.stderr)
        source = self.work / 'recovery-source'
        with tarfile.open(next(dist.glob('*.tar.gz'))) as archive:
            archive.extractall(source, filter='data')
        home = self.work / 'blocked-home'
        home.mkdir()
        preserved = {'current': '1.2.8.177\n', 'download-auth.json': '{old auth',
                     'openrouter.key': 'synthetic-existing-key', 'channel': 'stable\n',
                     'mixed-router-state.json': '{"clients":"claude","custom":"preserve"}'}
        for name, body in preserved.items():
            (home / name).write_text(body)
        controller = load('public_recovery_controller', 'packaging/native_controller.py')
        installer = controller.install(home, source)
        self.assertEqual(controller.installer(home), installer)
        recovered_feed = load('recovered_public_feed', installer.with_name('feed.py'))
        recovered_feed.configure_home(home)
        with mock.patch.object(recovered_feed._auth, 'ensure_access') as signin:
            self.assertIsNone(recovered_feed._request(recovered_feed.FEED_URL).get_header('Cookie'))
        signin.assert_not_called()
        for name, body in preserved.items():
            self.assertEqual((home / name).read_text(), body)


if __name__ == '__main__':
    unittest.main()
