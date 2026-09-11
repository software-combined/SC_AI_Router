"""Plan 094: one atomic text writer for installer-side state and config."""
import json
import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.install_fixtures import install_mod


def _mod():
    # File-based load: PyPI's `packaging` distribution shadows the local
    # installer directory on sys.path, so never `from packaging import ...`.
    import importlib.util as _ilu
    root = Path(__file__).resolve().parents[1]
    spec = _ilu.spec_from_file_location(
        'router_atomic_write', root / 'packaging' / 'atomic_write.py')
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class AtomicWriteTests(unittest.TestCase):
    def _dir(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        return Path(tmp)

    def test_create_and_overwrite(self):
        mod = _mod()
        home = self._dir()
        target = home / 'mixed-router-state.json'
        mod.replace_text(target, '{"a": 1}\n')
        self.assertEqual(target.read_text(), '{"a": 1}\n')
        mod.replace_text(target, '{"a": 2}\n')
        self.assertEqual(target.read_text(), '{"a": 2}\n')

    def test_mode_is_owner_only(self):
        mod = _mod()
        home = self._dir()
        target = home / 'config.toml'
        mod.replace_text(target, 'x = 1\n')
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)

    def test_failed_write_keeps_original_and_no_temp(self):
        mod = _mod()
        home = self._dir()
        target = home / 'mixed-router-state.json'
        target.write_text('original\n')
        before = list(home.iterdir())
        with mock.patch.object(os, 'replace', side_effect=OSError('crash')):
            with self.assertRaises(OSError):
                mod.replace_text(target, 'torn\n')
        self.assertEqual(target.read_text(), 'original\n')
        self.assertEqual(sorted(p.name for p in home.iterdir()),
                         sorted(p.name for p in before))

    def test_concurrent_writers_leave_one_complete_file(self):
        # Plan 094 core claim: unique temp names mean two writers cannot unlink
        # each other's in-flight temp, and no temp survives.
        import threading
        mod = _mod()
        home = self._dir()
        target = home / 'mixed-router-state.json'
        payloads = [json.dumps({'writer': i, 'pad': 'x' * 200}) + '\n' for i in range(4)]

        def write(text):
            mod.replace_text(target, text)

        errors = []

        def guarded(text):
            try:
                write(text)
            except BaseException as exc:  # a shared temp name raises here
                errors.append(exc)

        threads = [threading.Thread(target=guarded, args=(text,)) for text in payloads]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertIn(target.read_text(), payloads)
        self.assertEqual([p for p in home.iterdir() if p.suffix == '.tmp'], [])

    def test_failed_stream_write_keeps_original_and_no_temp(self):
        # The likelier real failure is the write phase, not the rename.
        import io
        mod = _mod()
        home = self._dir()
        target = home / 'mixed-router-state.json'
        target.write_text('original\n')

        class _BadStream(io.StringIO):
            def write(self, text):
                raise OSError('disk full')

        with mock.patch.object(os, 'fdopen', return_value=_BadStream()):
            with self.assertRaises(OSError):
                mod.replace_text(target, 'torn\n')
        self.assertEqual(target.read_text(), 'original\n')
        self.assertEqual([p for p in home.iterdir() if p.suffix == '.tmp'], [])

    def test_symlinked_target_is_replaced_not_written_through(self):
        # Plan 094 records this choice: os.replace swaps the link itself, which
        # also closes a planted-symlink redirect out of the config dir.
        mod = _mod()
        home = self._dir()
        real = home / 'managed.toml'
        real.write_text('managed\n')
        link = home / 'config.toml'
        link.symlink_to(real)
        mod.replace_text(link, 'new\n')
        self.assertFalse(link.is_symlink())
        self.assertEqual(link.read_text(), 'new\n')
        self.assertEqual(real.read_text(), 'managed\n')

    def test_read_only_target_is_replaced(self):
        # Plan 094 records this choice: rename needs only directory permission.
        mod = _mod()
        home = self._dir()
        target = home / 'config.toml'
        target.write_text('old\n')
        target.chmod(0o444)
        self.addCleanup(target.chmod, 0o600)
        mod.replace_text(target, 'new\n')
        self.assertEqual(target.read_text(), 'new\n')

    def test_state_writer_survives_crashed_replace(self):
        home = self._dir()
        state_path = home / 'mixed-router-state.json'
        state_path.write_text('{"port": 1}\n')
        with mock.patch.object(os, 'replace', side_effect=OSError('crash')):
            with self.assertRaises(OSError):
                install_mod._svc._atomic_write.replace_text(state_path, '{"port": 2}\n')
        self.assertEqual(state_path.read_text(), '{"port": 1}\n')
        leftovers = [p for p in home.iterdir() if p.suffix == '.tmp']
        self.assertEqual(leftovers, [])


if __name__ == '__main__':
    unittest.main()
