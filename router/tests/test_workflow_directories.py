"""Source paths and checkout-free jobs work in both repository layouts."""
from pathlib import Path
import re
import shlex
import tempfile
import unittest

from tests.test_ci_pipeline import CHECK, DIAGNOSTIC, jobs
from tests.test_workflows import run_block

REPOSITORY = CHECK.parents[2]


def step(block, name):
    return block.split('      - name: ' + name + '\n', 1)[1].split('\n      - ', 1)[0]


def directory(workflow, block, action='', arm='after'):
    """Resolve the workflow, job and step precedence used by these workflows."""
    value = '.'
    for text, indent in ((workflow.split('\njobs:\n')[0], 4),
                         (block.split('    steps:', 1)[0], 8), (action, 8)):
        match = re.search(r'^' + ' ' * indent + r'working-directory: (.+)$', text, re.M)
        if match:
            value = match[1]
    if value == "${{ inputs.arm == 'before' && '.' || 'router' }}":
        return '.' if arm == 'before' else 'router'
    return value


class WorkflowDirectoryTests(unittest.TestCase):
    def test_hook_suite_is_reachable_from_main_and_both_comparison_arms(self):
        for path in (CHECK, DIAGNOSTIC):
            text = path.read_text()
            block = jobs(path)['hook-adapter']
            names = ['Hook adapter tests'] + (['Recorded Hook adapter tests']
                                              if path == DIAGNOSTIC else [])
            for name in names:
                action = step(block, name)
                command = re.search(r'^        run: (.+)$', action, re.M)[1]
                args = shlex.split(command)
                source = args[args.index('-s') + 1].replace('${{ github.workspace }}', str(REPOSITORY))
                for arm in ('before', 'after'):
                    with self.subTest(path=path.name, step=name, arm=arm):
                        cwd = REPOSITORY / directory(text, block, action, arm)
                        self.assertTrue((cwd / source).is_dir(), 'hook discovery starts outside the plugin tree')

    def test_jobs_before_checkout_have_an_existing_working_directory(self):
        for path, names in ((DIAGNOSTIC, ('windows-native-aggregate', 'test', 'candidate-test')),
                            (CHECK.parent / 'windows-ci-safety.yml',
                             ('shared-fixture', 'control-fixture', 'matrix-fixture'))):
            text = path.read_text()
            for name in names:
                block = jobs(path)[name]
                action = (step(jobs(path)['test'], 'Required jobs')
                          if '    steps: *acceptance-steps' in block else
                          block.split('    steps:', 1)[1].split('\n      - uses:', 1)[0])
                with self.subTest(path=path.name, job=name), tempfile.TemporaryDirectory() as fresh:
                    self.assertTrue((Path(fresh) / directory(text, block, action)).is_dir())

    def test_lint_requirements_resolve_in_both_source_layouts(self):
        text = DIAGNOSTIC.read_text()
        requirements = re.search(r'-r ("[^"]+"|\S+)', run_block('Lint (F401/F811)', text))[1]
        requirements = requirements.strip('"').replace('${{ github.workspace }}', str(REPOSITORY))
        block = jobs(DIAGNOSTIC)['test']
        for arm in ('before', 'after'):
            with self.subTest(arm=arm):
                cwd = REPOSITORY / directory(text, block, arm=arm)
                self.assertTrue((cwd / requirements).is_file())
