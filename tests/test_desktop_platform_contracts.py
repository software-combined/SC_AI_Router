"""Native switching must retain its shutdown and durable-publication boundaries."""
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.test_native_setup import module


class DesktopPlatformContractTests(unittest.TestCase):
    def test_windows_publication_flush_uses_a_writable_handle_without_changing_bytes(self):
        publish = module('claude_profile_publish')
        def durable(fd):
            os.write(fd, b'')  # Windows FlushFileBuffers requires write access.
            os.fsync(fd)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve() / 'saved-task.json'
            path.write_bytes(b'saved task sentinel')
            with mock.patch.object(publish, 'os', SimpleNamespace(name='nt', fsync=durable)):
                publish.flush(path)
            self.assertEqual(path.read_bytes(), b'saved task sentinel')

    def test_windows_shutdown_matches_the_verified_executable_without_case_sensitivity(self):
        platform = module('claude_desktop_platform')
        identity = dict(root='C:/Apps/Codex', exe='C:/Apps/Codex/Codex.exe', user='user')
        row = dict(pid=10, parent=1, user='user', born='2026-10-18T00:00:00Z',
                   exe='c:/apps/codex/CODEX.EXE')
        run = mock.Mock(return_value=SimpleNamespace(returncode=0))
        with mock.patch.object(platform, 'app_identity', return_value=identity), \
                mock.patch.object(platform, '_snapshot', side_effect=[{10: row}, {}]):
            self.assertTrue(platform.request_stop('win32', run=run,
                app=platform.App('com.openai.codex', ())))
        self.assertIn('$births=@{10=', run.call_args.args[0][-1])
        self.assertIn('foreach($n in @(10))', run.call_args.args[0][-1])

    def test_linux_orphaned_bundled_codex_writer_prevents_a_configuration_change(self):
        platform = module('claude_desktop_platform')
        identity = dict(root='/apps/Codex', exe='/apps/Codex/ChatGPT', user='user')
        row = dict(pid=11, parent=1, user='user', born='start', exe='/apps/Codex/resources/codex')
        app = platform.App('com.openai.codex', ())
        with mock.patch.object(platform, 'app_identity', return_value=identity), \
                mock.patch.object(platform, '_snapshot', return_value={11: row}), \
                mock.patch.object(platform, 'confirm', return_value=True):
            self.assertTrue(platform.is_running('linux', app=app))
            self.assertFalse(platform.request_stop('linux', timeout=0, app=app))
