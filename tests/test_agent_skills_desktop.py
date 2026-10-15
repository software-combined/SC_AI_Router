"""A desktop-only Mac install can deliver SC tools without a terminal client."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_agent_skills_delivery import skills


class DesktopClientPathTests(unittest.TestCase):
    def test_mac_app_bundled_cli_reaches_plugin_delivery(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            binary = home / 'Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex'
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b'fixture native client')
            with mock.patch.object(skills.Path, 'home', return_value=home), mock.patch('sys.platform', 'darwin'):
                path = skills.client_path({'PATH': '/usr/bin:/bin'},
                                          os_name='posix')
            self.assertIn(str(binary.parent), path.split(os.pathsep))
            seen = []
            def which(name, *, path):
                self.assertIn(str(binary.parent), path.split(os.pathsep))
                return str(binary) if name == 'codex' else None
            def run(command, **unused):
                seen.append(command)
                return mock.Mock(returncode=0, stdout='{"installed":[],"marketplaces":[]}')
            with mock.patch.object(skills, 'client_path', return_value=path):
                result, refused = skills.register('codex', home / 'marketplace', ['scg-review'],
                                                   run=run, which=which)
            self.assertEqual(refused, 0, result)
            self.assertTrue(seen)
            self.assertTrue(all(command[0] == str(binary) for command in seen))


if __name__ == '__main__':
    unittest.main()
