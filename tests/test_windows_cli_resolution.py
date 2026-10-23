"""Store CLI selection ignores ELF files and expires with each discovered package."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.test_codex_config_proof import proof


class WindowsCliTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.package = self.base / 'Store.old'
        self.exe = self.file('app/Codex.exe')

    def file(self, relative, data=b'MZ fixture'):
        path = self.package / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def resolve(self, *, env=None, run=None, record=None):
        return proof.codex_bin(env or {}, self.package, app_exe=self.exe,
            platform_name='win32', run=run or mock.Mock(return_value=SimpleNamespace(
                returncode=0, stdout='codex-cli 0.163.0-alpha.11\n', stderr='')),
            record=record)

    def test_elf_codex_does_not_shadow_windows_executable(self):
        self.file('app/resources/codex', b'\x7fELF fixture')
        wanted = self.file('app/resources/codex.exe')
        record = {}
        self.assertEqual(self.resolve(record=record), str(wanted))
        self.assertEqual(record['cli_path'], 'app/resources/codex.exe')
        self.assertNotIn(str(self.base), json.dumps(record))

    def test_bin_layout_precedes_adjacent_and_package_root(self):
        wanted = self.file('app/resources/codex-cli/bin/codex.exe')
        self.file('app/resources/codex.exe')
        self.file('resources/codex.exe')
        self.assertEqual(self.resolve(), str(wanted))

    def test_bad_header_and_failed_version_try_the_next_candidate(self):
        first = self.file('app/resources/codex-cli/bin/codex.exe')
        second = self.file('app/resources/codex.exe')
        for failure in (SimpleNamespace(returncode=0, stdout='other-tool 1.0.0', stderr=''),
                        SimpleNamespace(returncode=1, stdout='codex-cli 1.2.3', stderr=''),
                        OSError(193, 'private path'), subprocess.TimeoutExpired('private command', 5)):
            run = mock.Mock(side_effect=[failure, SimpleNamespace(returncode=0,
                stdout='codex-cli 0.163.0-alpha.11', stderr='')])
            record = {}
            self.assertEqual(self.resolve(run=run, record=record), str(second))
            attempt = record['cli_attempts'][0]
            self.assertEqual(attempt['operation'], 'cli_version')
            self.assertGreaterEqual(attempt['elapsed_ms'], 0)
            self.assertNotIn('private', json.dumps(record))
            self.assertEqual(run.call_args_list[0].args[0], [str(first), '--version'])
            self.assertEqual(run.call_args.kwargs['timeout'], 5)
            self.assertEqual(run.call_args.kwargs['creationflags'], 0x08000000)
        first.write_bytes(b'\x7fELF fixture')
        run = mock.Mock(return_value=SimpleNamespace(returncode=0, stdout='codex-cli 1.2.3', stderr=''))
        self.assertEqual(self.resolve(run=run), str(second))
        run.assert_called_once()

    def test_known_vendor_layout_remains_available(self):
        cli = self.file('app/resources/codex-cli/vendor/x86_64-pc-windows-msvc/codex/codex.exe')
        self.assertEqual(self.resolve(), str(cli))

    def test_override_is_ignored_and_new_package_folder_is_discovered(self):
        old = self.file('app/resources/codex.exe')
        self.assertEqual(self.resolve(env={'CODEX_BIN': '/pinned/old/codex'}), str(old))
        renamed = self.base / 'Store.new'
        self.package.rename(renamed)
        self.package, self.exe = renamed, renamed / 'app/Codex.exe'
        self.assertEqual(self.resolve(), str(renamed / 'app/resources/codex.exe'))

    def test_helpers_and_outside_package_candidates_are_rejected(self):
        self.file('app/resources/codex-command-runner.exe')
        self.file('app/resources/codex-windows-sandbox-x64.exe')
        self.assertIsNone(self.resolve())
        outside = self.base / 'outside.exe'
        outside.write_bytes(b'MZ fixture')
        candidate = self.package / 'app/resources/codex.exe'
        try:
            candidate.symlink_to(outside)
        except OSError:
            self.skipTest('symlinks unavailable')
        self.assertIsNone(self.resolve())

    def test_non_windows_layout_and_override_remain_unchanged(self):
        cli = self.file('resources/codex', b'\x7fELF fixture')
        for name in ('darwin', 'linux'):
            self.assertEqual(proof.codex_bin({}, self.package, app_exe=self.exe,
                                           platform_name=name), str(cli))
            self.assertEqual(proof.codex_bin({'CODEX_BIN': '/chosen'}, self.package,
                                           platform_name=name), '/chosen')


if __name__ == '__main__':
    unittest.main()
