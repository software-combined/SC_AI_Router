"""A clean repository's first main push selects native acceptance safely."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tests.test_ci_pipeline import CHECK
from tests.test_workflows import run_block

COMPONENT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'posix' and shutil.which('bash') and shutil.which('git'),
                     'runs the real Ubuntu workflow shell and Git')
class CleanHistoryScopeTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.component = self.root / 'router'
        for name in ('tools', 'config', 'packaging', 'ai_router'):
            (self.component / name).mkdir(parents=True)
        for name in ('tools/ci_scope.py', 'config/installer-python-surface.txt'):
            shutil.copyfile(COMPONENT / name, self.component / name)
        (self.component / 'packaging/install.py').write_text('# Synthetic installer fixture.\n')
        self.env = {**os.environ, 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1',
                    'GITHUB_EVENT_NAME': 'push', 'GITHUB_OUTPUT': str(self.root / 'scope.out')}
        self.git('init', '-q')
        self.git('config', 'user.name', 'Example')
        self.git('config', 'user.email', 'test@example.invalid')
        self.base = self.commit()

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.root, env=self.env,
                                       text=True, stderr=subprocess.DEVNULL).strip()

    def commit(self):
        self.git('add', '.')
        self.git('commit', '-qm', 'fixture')
        return self.git('rev-parse', 'HEAD')

    def scope(self, before, after):
        block = (run_block('Installer scope', CHECK.read_text())
                 .replace('${{ github.base_ref }}', 'main')
                 .replace('${{ github.event.before }}', before)
                 .replace('${{ github.sha }}', after))
        result = subprocess.run(['bash', '-e', '-c', block], cwd=self.component,
                                env=self.env, capture_output=True, text=True)
        output = Path(self.env['GITHUB_OUTPUT'])
        return result, output.read_text() if output.exists() else ''

    def test_first_main_push_uses_all_candidate_paths(self):
        result, output = self.scope('0' * 40, self.base)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output, 'installer=true\n')

    def test_normal_push_preserves_the_actual_diff_scope(self):
        (self.component / 'ai_router/router.py').write_text('# Synthetic runtime-only change.\n')
        result, output = self.scope(self.base, self.commit())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output, 'installer=false\n')

    def test_missing_nonzero_history_remains_a_failure(self):
        result, _ = self.scope('1' * 40, self.base)
        self.assertNotEqual(result.returncode, 0)
