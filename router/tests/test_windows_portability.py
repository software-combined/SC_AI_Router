"""Plan 116: shared installer surfaces that Windows exposed as non-portable.

Pins the TOML path form in the Codex block, the windowless subprocess seam,
and the platform-correct no-interpreter remedy. Offline; no real tasks.
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


codex_config = _load('router_codex_config_portability', 'packaging/codex_config.py')
service = _load('router_service_portability', 'packaging/service.py')


class BundledTextEncodingTests(unittest.TestCase):
    def test_model_labels_and_instructions_ignore_the_host_locale(self):
        script = r'''
from pathlib import Path
from ai_router import model_instructions, model_refresh, registry
assert all(m.display_name.endswith(' \u00b7 OpenRouter')
           for m in registry.MODELS if m.provider == 'openrouter')
for name, text in (('routed_base_instructions.txt', model_instructions.BASE_INSTRUCTIONS),
                   ('subscription_base_instructions.txt', model_instructions.SUBSCRIBER_INSTRUCTIONS)):
    path = Path(model_instructions.__file__).with_name(name)
    assert text == path.read_text(encoding='utf-8')
    assert model_refresh._read(path) == text
'''
        result = subprocess.run([sys.executable, '-X', 'utf8=0', '-c', script],
                                cwd=ROOT, capture_output=True, text=True,
                                env={**os.environ, 'LC_ALL': 'C', 'PYTHONCOERCECLOCALE': '0'})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class CodexBlockPathTests(unittest.TestCase):
    def test_catalogue_path_uses_forward_slashes(self):
        # TOML basic strings treat backslashes as escapes: a native Windows
        # path would leave Codex unable to parse its own config.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'mixed-model-router'
            block = codex_config.build_block(home, {'port': 1, 'token': 't'}, 'subscription', True)
            line = next(l for l in block.splitlines() if l.startswith('model_catalog_json'))
            self.assertNotIn('\\', line)
            self.assertIn(home.as_posix() + '/mixed-models.json', line)


class WindowlessRunTests(unittest.TestCase):
    def test_run_hides_console_children_on_windows_only(self):
        with mock.patch.object(service.subprocess, 'run') as run:
            with mock.patch.object(service.sys, 'platform', 'win32'):
                service.run(['x'], capture_output=True)
            self.assertEqual(run.call_args.kwargs.get('creationflags'),
                             getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            with mock.patch.object(service.sys, 'platform', 'darwin'):
                service.run(['x'], capture_output=True)
            self.assertNotIn('creationflags', run.call_args.kwargs)

    def test_explicit_flags_are_left_alone(self):
        with mock.patch.object(service.subprocess, 'run') as run, \
                mock.patch.object(service.sys, 'platform', 'win32'):
            service.run(['x'], creationflags=7)
        self.assertEqual(run.call_args.kwargs['creationflags'], 7)


class NoInterpreterMessageTests(unittest.TestCase):
    def test_windows_never_sees_the_homebrew_remedy(self):
        install_mod = _load('router_install_portability', 'packaging/install.py')
        args = install_mod.build_parser().parse_args(['--dry-run', '--home', 'x'])
        with mock.patch.object(install_mod, 'find_python', return_value=None), \
                mock.patch.object(install_mod, 'PLATFORM', 'win32'), \
                mock.patch('builtins.print') as printed:
            with self.assertRaises(SystemExit):
                install_mod.do_install(args)
        text = ' '.join(str(c.args[0]) for c in printed.call_args_list)
        self.assertNotIn('brew', text)
        self.assertIn('Python 3.14', text)


if __name__ == '__main__':
    unittest.main()
