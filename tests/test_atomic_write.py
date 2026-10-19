"""Plan 094: one atomic text writer for installer-side state and config."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests._platform import assert_owner_only
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
    def test_concurrent_edit_during_temp_write_is_not_overwritten(self):
        mod = _mod()
        target = self._dir() / 'settings.json'
        target.write_text('{"before":true}\n')
        original = mod._mod.os.chmod
        def changed(path, mode):
            target.write_text('{"concurrent":true}\n')
            original(path, mode)
        with mock.patch.object(mod._mod.os, 'chmod', side_effect=changed), \
                self.assertRaises(mod.ConcurrentChange):
            mod.replace_text(target, '{}\n', expected='{"before":true}\n')
        self.assertEqual(target.read_text(), '{"concurrent":true}\n')
        self.assertEqual(list(target.parent.iterdir()), [target])

    def test_guarded_removal_refuses_a_changed_receipt(self):
        mod = _mod()
        target = self._dir() / 'activation.json'
        target.write_text('{"current":true}\n')
        with self.assertRaises(mod.ConcurrentChange):
            mod.remove(target, expected='{}\n')
        self.assertTrue(target.exists())
        mod.remove(target, expected=target.read_bytes().decode('utf-8'))
        self.assertFalse(target.exists())

    def test_windows_sharing_retry_rechecks_concurrent_changes(self):
        mod = _mod()
        target = self._dir() / 'settings.json'
        target.write_text('before')
        attempts = []
        def replace(source, destination):
            attempts.append(1)
            target.write_text('concurrent edit')
            error = PermissionError('sharing violation')
            error.winerror = 32
            raise error
        windows = SimpleNamespace(**dict(vars(os), name='nt', replace=replace))
        with mock.patch.object(mod._mod, 'os', windows), \
                mock.patch.object(mod._mod.time, 'sleep'), \
                self.assertRaises(mod.ConcurrentChange):
            mod.replace_text(target, 'restored', expected='before')
        self.assertEqual(len(attempts), 1)
        self.assertEqual(target.read_text(), 'concurrent edit')
        self.assertEqual(list(target.parent.iterdir()), [target])

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
        assert_owner_only(self, target)

    def test_explicit_newline_preserves_saved_line_endings(self):
        target = self._dir() / 'setup-current'
        saved = 'one\r\ntwo\n'
        _mod().replace_text(target, saved, newline='')
        self.assertEqual(target.read_bytes(), saved.encode())

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

    def test_replace_json_and_deterministic_tmp_policies(self):
        mod = _mod()
        home = self._dir()
        target = home / 'state.json'
        mod.replace_json(target, {'a': 1})
        self.assertEqual(target.read_text(), '{\n  "a": 1\n}\n')
        stale = home / (target.name + '.router.tmp')
        stale.write_text('leftover')
        with self.assertRaises(mod.StaleTmp):
            mod.replace_json(target, {'a': 2}, tmp_name=stale.name,
                             stale_tmp='refuse')
        self.assertEqual(stale.read_text(), 'leftover')
        mod.replace_json(target, {'a': 2}, tmp_name=stale.name)
        self.assertEqual(json.loads(target.read_text()), {'a': 2})
        self.assertFalse(stale.exists())

    def test_packaging_alias_loads_from_a_home_style_layout(self):
        # An installed release keeps packaging/ and ai_router/ as siblings,
        # and the alias must resolve the runtime leaf from that layout.
        import importlib.util as _ilu
        root = self._dir() / 'home'
        (root / 'ai_router').mkdir(parents=True)
        (root / 'packaging').mkdir()
        for rel in ('ai_router/atomic_write.py', 'packaging/atomic_write.py'):
            source = Path(__file__).resolve().parents[1] / rel
            (root / rel).write_text(source.read_text())
        spec = _ilu.spec_from_file_location(
            'home_router_atomic_write', root / 'packaging' / 'atomic_write.py')
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        target = root / 'config.toml'
        mod.replace_text(target, 'x = 1\n')
        self.assertEqual(target.read_text(), 'x = 1\n')
        assert_owner_only(self, target)

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

        def _fdopen(fd, *args, **kwargs):
            # Real os.fdopen takes ownership of the descriptor; close it here
            # too so the temp is not left open. Windows refuses to unlink a
            # file with a live handle, so a mock that leaked fd would strand
            # the temp there while POSIX quietly tolerated it.
            os.close(fd)
            return _BadStream()

        with mock.patch.object(os, 'fdopen', side_effect=_fdopen):
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
        try:
            link.symlink_to(real)
        except OSError as exc:
            # Windows only lets a process create symlinks with Developer Mode
            # enabled or SeCreateSymbolicLinkPrivilege held (WinError 1314).
            # The replace-the-link-itself behaviour is unchanged by that; skip
            # rather than fail where the OS forbids making the link at all.
            self.skipTest(f'symlink creation not permitted here: {exc}')
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
