"""A private installer pilot cannot expose builds or switch routine updates."""
import unittest
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/release.yml'


class NativeReleaseWorkflowTests(unittest.TestCase):
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

    def test_private_pilot_does_not_switch_routine_update_feeds(self):
        text = WORKFLOW.read_text()
        feed = text.split('if [ "$PILOT_ONLY" != true ]; then', 1)[1].split('          fi', 1)[0]
        self.assertIn('tools/publish_feed.py', feed)
        release = text.split('      - name: Create release', 1)[1]
        pilot = release.split('if [ "$PILOT_ONLY" = true ]; then', 1)[1].split('          fi', 1)[0]
        self.assertIn('--prerelease', pilot)
        self.assertIn('exit 0', pilot)
        self.assertNotIn('dist/', pilot)


if __name__ == '__main__':
    unittest.main()
