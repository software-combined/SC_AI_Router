"""Public recovery preserves the existing channel and legacy local state."""
import tempfile
import unittest
from pathlib import Path

from tests import test_bootstrap as bootstrap
from tests._platform import unix_only


@unix_only
class BootstrapRecoveryTests(unittest.TestCase):
    def test_recovery_without_a_channel_override_preserves_existing_beta(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            (home / 'channel').write_text('beta\n')
            (home / 'download-auth.json').write_text('{legacy blocked state')
            proc, home = bootstrap.BootstrapTests()._full_run(tmp, None)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual((home / 'channel').read_text(), 'beta\n')
            self.assertEqual((home / 'download-auth.json').read_text(), '{legacy blocked state')

