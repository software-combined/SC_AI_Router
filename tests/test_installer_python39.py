"""The installer-Python check stays inert: it must never run host-mutating files.

Incident 2026-09-13: the first version of tools/check_installer_python39.py
imported every surface file, and tools/disable.py detaches the live router
when it runs, so an unattended check unloaded the owner's service. The check
now imports only `load` files, in a child process with a scratch HOME,
ROUTER_HOME and PATH, and never executes `parse` files.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / 'tools' / 'check_installer_python39.py'


def _check_module():
    spec = importlib.util.spec_from_file_location('router_check_python39', CHECK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_surface(root, lines):
    config = root / 'config'
    config.mkdir(parents=True, exist_ok=True)
    (config / 'installer-python-surface.txt').write_text('\n'.join(lines) + '\n')


class CheckInertnessTests(unittest.TestCase):
    def run_check(self, root, extra_env=None):
        env = {**os.environ}
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [sys.executable, str(CHECK), '--root', str(root)],
            capture_output=True, text=True, env=env)

    def test_a_parse_file_is_never_executed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sentinel = root / 'sentinel'
            (root / 'fixture').mkdir()
            (root / 'fixture' / 'safe.py').write_text('VALUE = 1\n')
            (root / 'fixture' / 'trap.py').write_text(
                'import os\n'
                'open(os.environ["CHECK_TRAP_SENTINEL"], "w").write("fired")\n')
            _write_surface(root, ['load fixture/safe.py', 'parse fixture/trap.py'])
            result = self.run_check(root, {'CHECK_TRAP_SENTINEL': str(sentinel)})
            self.assertEqual(result.returncode, 0,
                             result.stdout + result.stderr)
            self.assertFalse(sentinel.exists(), 'the parse file was executed')

    def test_loads_run_with_a_scratch_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = root / 'record'
            marker = 'home-must-not-leak'
            (root / 'fixture').mkdir()
            (root / 'fixture' / 'home.py').write_text(
                'import os\n'
                'open(os.environ["CHECK_HOME_RECORD"], "w").write(\n'
                '    os.environ["HOME"] + "\\n" + os.environ["ROUTER_HOME"])\n')
            _write_surface(root, ['load fixture/home.py'])
            result = self.run_check(root, {
                'CHECK_HOME_RECORD': str(record), 'HOME': marker,
                'ROUTER_HOME': marker})
            self.assertEqual(result.returncode, 0,
                             result.stdout + result.stderr)
            child_home, child_router_home = record.read_text().splitlines()
            self.assertNotEqual(child_home, marker)
            self.assertNotEqual(child_router_home, marker)
            self.assertNotEqual(child_router_home, '')

    def test_a_load_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'fixture').mkdir()
            (root / 'fixture' / 'broken.py').write_text(
                'raise RuntimeError("check fixture failure")\n')
            _write_surface(root, ['load fixture/broken.py'])
            result = self.run_check(root)
            self.assertEqual(result.returncode, 1)
            self.assertIn('check fixture failure', result.stdout)


class SurfaceContractTests(unittest.TestCase):
    def entries(self):
        return _check_module().read_surface(ROOT)[0]

    def test_the_real_surface_pins_disable_as_parse_only(self):
        entries = self.entries()
        self.assertIn(('parse', 'tools/disable.py'), entries)
        self.assertNotIn(('load', 'tools/disable.py'), entries)
        for launcher in ('packaging/router_launch.py', 'packaging/update_launch.py',
                         'packaging/task_launch.py'):
            self.assertIn(('parse', launcher), entries)
        for loaded in ('packaging/install.py', 'packaging/operator_surface.py',
                       'packaging/claude_desktop_config.py',
                       'packaging/claude_profile_publish.py',
                       'ai_router/winacl.py'):
            self.assertIn(('load', loaded), entries)

    def test_surface_entries_are_unique_and_exist(self):
        entries = self.entries()
        paths = [rel for _mode, rel in entries]
        self.assertEqual(len(paths), len(set(paths)), 'duplicate surface entry')
        for rel in paths:
            with self.subTest(path=rel):
                self.assertTrue((ROOT / rel).is_file(), rel)


class DisableToolImportTests(unittest.TestCase):
    def test_importing_disable_never_touches_the_router(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            block = ('# BEGIN local mixed model picker\n'
                     'openai_base_url = "http://127.0.0.1:1/example"\n'
                     '# END local mixed model picker\n')
            config = home / 'config.toml'
            config.write_text('approval_policy = "never"\n' + block + '\n')
            (home / 'activation.json').write_text(json.dumps({
                'version': 2,
                'clients': {'codex': {'config_path': str(config),
                                      'inserted_block': block}}}))
            before = config.read_text()
            with mock.patch.dict(os.environ, {'ROUTER_HOME': str(home)}), \
                    mock.patch('subprocess.run') as run:
                spec = importlib.util.spec_from_file_location(
                    'router_disable_tool', ROOT / 'tools' / 'disable.py')
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            run.assert_not_called()
            self.assertEqual(config.read_text(), before,
                             'importing tools/disable.py modified the config')


if __name__ == '__main__':
    unittest.main()
