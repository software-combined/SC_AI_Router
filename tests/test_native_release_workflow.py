"""Public native downloads use stable; unaccepted platforms remain private."""
import unittest
import os
import subprocess
import tempfile
import textwrap
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/release.yml'


class NativeReleaseWorkflowTests(unittest.TestCase):
    @unittest.skipIf(os.name == 'nt', 'release publication runs on Ubuntu')
    def test_publish_rerun_keeps_existing_release_and_assets(self):
        step = WORKFLOW.read_text().split('      - name: Create release\n', 1)[1]
        script = textwrap.dedent(step.split('        run: |\n', 1)[1])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'dist').mkdir()
            (root / 'dist/release-latest.json').write_text('{}')
            (root / 'dist/example.tar.gz').write_bytes(b'fixture')
            gh = root / 'gh'
            gh.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$SCG_TEST_CALLS"\n'
                          'if [ "$2" = view ]; then exit "$SCG_TEST_VIEW"; fi\n')
            gh.chmod(0o755)
            calls = root / 'calls'
            for exists in (True, False):
                with self.subTest(existing_release=exists):
                    calls.write_text('')
                    result = subprocess.run(['bash', '-c', script], cwd=root, capture_output=True,
                        env={**os.environ, 'PATH': str(root) + os.pathsep + os.environ['PATH'],
                             'SCG_TEST_CALLS': str(calls), 'SCG_TEST_VIEW': '0' if exists else '1',
                             'CHANNEL': 'stable', 'GITHUB_REF_NAME': 'v1.2.11'})
                    self.assertEqual(result.returncode, 0, result.stderr)
                    actions = calls.read_text().splitlines()
                    self.assertEqual(any(line.startswith('release create ') for line in actions), not exists)
                    self.assertFalse(any('upload' in line or 'delete' in line for line in actions))

    def test_windows_checks_release_subset_and_native_acl_in_separate_powershell_steps(self):
        release = WORKFLOW.read_text()
        command = release.split('      - name: Native packaging contracts\n', 1)[1]
        command = command.split('        run: ', 1)[1].splitlines()[0]
        check = WORKFLOW.with_name('check.yml').read_text()
        windows = check.split('  installer-windows:\n', 1)[1].split('  installer-python39:\n', 1)[0]
        steps = {block.splitlines()[0]: block.rstrip().splitlines()[1:]
                 for block in windows.split('      - name: ')[1:]}
        for name, run in (
                ('Native packaging contracts (PowerShell)', command),
                ('Native ACL contract (PowerShell)', 'python -m unittest tests.test_windows_acl_native')):
            with self.subTest(step=name):
                self.assertEqual(steps.get(name), ['        shell: pwsh', '        run: ' + run])

    def test_native_builds_stay_out_of_public_actions_artifacts(self):
        text = WORKFLOW.read_text()
        native = text.split('  native:', 1)[1].split('  publish:', 1)[0]
        self.assertNotIn('actions/upload-artifact', native)
        self.assertIn('/native-builds/', native)
        self.assertIn('role-session-name: router-native-build', native)

    def test_native_pilot_does_not_suppress_normal_update_publication(self):
        text = WORKFLOW.read_text()
        self.assertNotIn('PILOT_ONLY', text)
        publish = text.split('      - name: Publish to the update feed', 1)[1]
        self.assertIn('python tools/publish_feed.py', publish)
        self.assertNotIn('--download-config', publish)
        release = text.split('      - name: Create release', 1)[1]
        self.assertIn('dist/*.tar.gz', release)
        self.assertIn('--prerelease', release)

    def test_native_downloads_require_stable_and_a_platform_publication_gate(self):
        text = WORKFLOW.read_text()
        self.assertIn('if [ "$CHANNEL" = stable ] && {', text)
        self.assertIn('NATIVE_INSTALLERS_MACOS_ARM64_ONLY', text)
        self.assertIn('NATIVE_OPTIONS=(--macos-arm64-only)', text)
        self.assertNotIn('NATIVE_INSTALLERS_PILOT', text)


if __name__ == '__main__':
    unittest.main()
