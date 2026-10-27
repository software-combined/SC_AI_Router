"""Real Git transitions and runner handoff cannot hide required verification."""
import json
import os
import shutil
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = 'plugins/scg-example/skills/example/SKILL.md'
MANIFEST = 'plugins/scg-example/.codex-plugin/plugin.json'
MODULES = ('test_plugin', 'test_agent_skills', 'test_prototypes_manifest',
           'test_review_export', 'test_security_review', 'test_packaging',
           'test_router_worker_no_result', 'test_windows_agent_skills',
           'test_plugin_verification')


@unittest.skipUnless(shutil.which('git'), 'requires real Git integration')
class PluginVerificationTests(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(temporary) / 'repo'
        self.root.mkdir()
        self.report = Path(temporary) / 'report.json'
        self.env = {**os.environ, 'GIT_CONFIG_GLOBAL': os.devnull,
                    'GIT_CONFIG_NOSYSTEM': '1', 'PYTHONDONTWRITEBYTECODE': '1'}
        self.git('init', '-q')
        self.git('config', 'user.name', 'Example')
        self.git('config', 'user.email', 'test@example.invalid')
        self.write('.gitignore', '__pycache__/\n*.pyc\n')
        self.write('.agents/plugins/marketplace.json', json.dumps({'plugins': [
            {'name': 'scg-example', 'source': {'path': './plugins/scg-example'}}]}))
        self.write(SKILL, '---\nname: example\ndescription: Example skill.\n---\n')
        for client in ('codex', 'claude'):
            self.write(f'plugins/scg-example/.{client}-plugin/plugin.json',
                       json.dumps({'name': 'scg-example', 'version': '0.1.0'}))
        self.write('plugins/CHANGELOG.md', '# Changelog\n')
        self.write('tests/__init__.py', '')
        for name in MODULES:
            self.write(f'tests/{name}.py', 'import unittest\nclass T(unittest.TestCase):\n'
                       '    def test_ok(self): self.assertTrue(True)\n')
        self.write('tests/test_router.py', 'import unittest\nclass T(unittest.TestCase):\n'
                   '    def test_full_only(self): self.fail("full Router sentinel")\n')
        for name in ('ci_unittest.py', 'plugin_verification.py'):
            source = ROOT / 'tools' / name
            if source.exists():
                self.write('tools/' + name, source.read_text(encoding='utf-8'))
        self.base = self.commit()

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return path

    def git(self, *args, input=None):
        return subprocess.check_output(['git', *args], cwd=self.root, env=self.env,
                                       input=input, text=True).strip()

    def commit(self):
        self.git('add', '.')
        self.git('commit', '-qm', 'fixture')
        return self.git('rev-parse', 'HEAD')

    def command(self, *args, base=None):
        return [sys.executable, str(self.root / 'tools/plugin_verification.py'),
                '--base', self.base if base is None else base, *args]

    def run_plan(self, *args, base=None):
        result = subprocess.run(self.command(*args, base=base), cwd=self.root,
                                env=self.env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return json.loads(result.stdout)

    def change_skill(self):
        self.write(SKILL, (self.root / SKILL).read_text() + '\nUpdated guidance.\n')

    def test_small_skill_change_selects_complete_plugin_contract_suites(self):
        self.change_skill()
        plan = self.run_plan()
        self.assertEqual(plan['mode'], 'plugins')
        self.assertEqual(set(plan['tests']), {'tests.' + name for name in MODULES})

    def test_domain_skill_edit_selects_contracts_after_layout_is_integrated(self):
        (self.root / 'plugins/development').mkdir()
        self.git('mv', 'plugins/scg-example', 'plugins/development/scg-example')
        self.write('.agents/plugins/marketplace.json', json.dumps({'plugins': [
            {'name': 'scg-example', 'source': {
                'path': './plugins/development/scg-example'}}]}))
        self.base = self.commit()
        self.write('plugins/development/scg-example/skills/example/SKILL.md',
                   '# Updated domain skill\n')
        self.assertEqual(self.run_plan()['mode'], 'plugins')

    def test_domain_layout_move_itself_keeps_full_verification(self):
        (self.root / 'plugins/development').mkdir()
        self.git('mv', 'plugins/scg-example', 'plugins/development/scg-example')
        self.assertEqual(self.run_plan()['mode'], 'full')

    def test_unsafe_marketplace_path_keeps_full_verification(self):
        self.write('.agents/plugins/marketplace.json', json.dumps({'plugins': [
            {'name': 'scg-example', 'source': {
                'path': './plugins/../scg-example'}}]}))
        self.base = self.commit()
        self.change_skill()
        self.assertEqual(self.run_plan()['mode'], 'full')

    def test_committed_index_worktree_and_untracked_inputs_are_unioned(self):
        self.change_skill()
        self.commit()
        self.write('ai_router/router.py', 'staged Router change\n')
        self.git('add', 'ai_router/router.py')
        (self.root / 'ai_router/router.py').unlink()
        self.assertEqual(self.run_plan()['mode'], 'full')

    def test_committed_router_change_cannot_hide_behind_a_working_skill_edit(self):
        self.write('ai_router/router.py', '# Router change\n')
        self.commit()
        self.change_skill()
        self.assertEqual(self.run_plan()['mode'], 'full')

    def test_opposing_manifest_behavior_changes_do_not_become_version_only(self):
        self.write(MANIFEST, '{"name":"scg-example","version":"0.1.0","hooks":"x"}')
        self.git('add', MANIFEST)
        self.write(MANIFEST, '{"name":"scg-example","version":"0.1.1"}')
        self.assertEqual(self.run_plan()['mode'], 'full')

    def test_version_only_manifests_and_changelog_remain_plugin_scope(self):
        self.write(MANIFEST, '{"name":"scg-example","version":"0.1.1"}')
        self.write(MANIFEST.replace('codex', 'claude'),
                   '{"name":"scg-example","version":"0.1.1"}')
        self.write('plugins/CHANGELOG.md', '# Next plugin version\n')
        self.assertEqual(self.run_plan()['mode'], 'plugins')

    def test_ambiguous_manifest_fields_do_not_qualify_as_version_only(self):
        self.write(MANIFEST, '{"name":"other","name":"scg-example","version":"0.1.1"}')
        self.assertEqual(self.run_plan()['mode'], 'full')

    def test_scripts_policies_marketplace_and_unknown_paths_keep_full_checks(self):
        for name in ('plugins/scg-example/scripts/task.py',
                     'plugins/scg-example/skills/example/references/settings.json',
                     'plugins/unknown/skills/example/SKILL.md', 'AGENTS.md',
                     '.github/workflows/check.yml', 'tools/plugin_verification.py',
                     'requirements.txt', '.agents/plugins/marketplace.json'):
            with self.subTest(path=name):
                path = self.root / name
                old = path.read_bytes() if path.exists() else None
                self.write(name, (old.decode() if name == 'tools/plugin_verification.py' else '')
                           + '\n# changed\n')
                self.assertEqual(self.run_plan()['mode'], 'full')
                if old is None:
                    path.unlink()
                else:
                    path.write_bytes(old)

    def test_unknown_history_nonancestor_and_empty_changes_keep_full_checks(self):
        orphan = self.git('commit-tree', 'HEAD^{tree}', input='unrelated\n')
        for base in (self.base, 'missing-ref', '0' * 40, orphan):
            with self.subTest(base=base):
                self.assertEqual(self.run_plan(base=base)['mode'], 'full')

    def test_untracked_reference_with_spaces_is_a_single_path(self):
        path = 'plugins/scg-example/skills/example/references/a note.md'
        self.write(path, '# Reference\n')
        plan = self.run_plan()
        self.assertEqual(plan['mode'], 'plugins')
        self.assertEqual(plan['paths'], [path])

    def test_deleted_or_renamed_skill_keeps_full_checks(self):
        self.git('mv', SKILL, SKILL.replace('SKILL.md', 'renamed.md'))
        self.assertEqual(self.run_plan()['mode'], 'full')

    @unittest.skipUnless(os.name == 'posix', 'POSIX symlinks and executable mode')
    def test_symlinks_and_mode_changes_keep_full_checks(self):
        path = self.root / SKILL
        path.chmod(0o755)
        self.assertEqual(self.run_plan()['mode'], 'full')
        path.chmod(0o644)
        path.unlink()
        path.symlink_to('missing.md')
        self.assertEqual(self.run_plan()['mode'], 'full')

    def test_runner_executes_plugin_cases_without_router_cases(self):
        self.change_skill()
        result = subprocess.run(self.command('--run', '--report', str(self.report)),
                                cwd=self.root, env=self.env, capture_output=True,
                                text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        report = json.loads(self.report.read_text())
        self.assertTrue(report['complete'])
        self.assertEqual(len(report['cases']), len(MODULES))
        self.assertFalse(any('test_router.' in row['id'] for row in report['cases']))

    def test_explicit_full_mode_executes_the_router_control(self):
        self.change_skill()
        result = subprocess.run(self.command('--full', '--run', '--report', str(self.report)),
                                cwd=self.root, env=self.env, capture_output=True,
                                text=True, timeout=20)
        self.assertNotEqual(result.returncode, 0)
        report = json.loads(self.report.read_text())
        self.assertTrue(any('test_router.' in row['id'] for row in report['cases']))

    def test_failed_plugin_test_is_not_retried_with_full_discovery(self):
        self.write('tests/test_plugin.py', 'import unittest\nclass T(unittest.TestCase):\n'
                   '    def test_bad(self): self.fail("required plugin failure")\n')
        self.base = self.commit()
        self.change_skill()
        result = subprocess.run(self.command('--run', '--report', str(self.report)),
                                cwd=self.root, env=self.env, capture_output=True,
                                text=True, timeout=20)
        self.assertNotEqual(result.returncode, 0)
        report = json.loads(self.report.read_text())
        self.assertEqual(report['summary']['failures'], 1)
        self.assertFalse(any('test_router.' in row['id'] for row in report['cases']))

    def test_missing_required_plugin_suite_fails_visibly(self):
        (self.root / 'tests/test_packaging.py').unlink()
        self.base = self.commit()
        self.change_skill()
        result = subprocess.run(self.command('--run'), cwd=self.root, env=self.env,
                                capture_output=True, text=True, timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('missing verification suite', result.stderr)

    @unittest.skipUnless(os.name == 'posix', 'CI uses POSIX worker groups')
    def test_cancellation_reaches_existing_runner_and_stops_workers(self):
        marker = self.report.with_name('worker.pid')
        self.write('tests/test_plugin.py', 'import os,time,unittest\nfrom pathlib import Path\n'
                   'class T(unittest.TestCase):\n'
                   f'    def test_wait(self): Path({str(marker)!r}).write_text(str(os.getpid())); time.sleep(30)\n')
        self.base = self.commit()
        self.change_skill()
        process = subprocess.Popen(self.command('--run', '--workers', '2', '--report',
                                               str(self.report)), cwd=self.root,
                                   env=self.env, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            deadline = time.monotonic() + 10
            while not marker.exists() and time.monotonic() < deadline and process.poll() is None:
                time.sleep(0.02)
            self.assertTrue(marker.exists(), 'worker never started')
            worker = int(marker.read_text())
            process.send_signal(signal.SIGTERM)
            self.assertNotEqual(process.wait(timeout=10), 0)
            with self.assertRaises(ProcessLookupError):
                os.kill(worker, 0)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            if marker.exists():
                try:
                    os.killpg(int(marker.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass


if __name__ == '__main__':
    unittest.main()
