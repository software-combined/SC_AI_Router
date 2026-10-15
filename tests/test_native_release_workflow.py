"""A private installer pilot cannot expose builds or switch routine updates."""
import unittest
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/release.yml'


class NativeReleaseWorkflowTests(unittest.TestCase):
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
