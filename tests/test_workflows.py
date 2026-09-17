"""Offline execution of the release workflow's shell contract."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / '.github/workflows'
RELEASE = (WORKFLOWS / 'release.yml').read_text()


def run_block(name, text=None):
    step = (text if text is not None else RELEASE).split(f'      - name: {name}\n', 1)[1]
    block = re.search(r'        run: \|\n((?:          [^\n]*\n|\n)+)', step)
    return textwrap.dedent(block[1])


@unittest.skipUnless(os.name == 'posix' and shutil.which('bash'),
                     'release workflow runs on Ubuntu')
class ReleaseShellTests(unittest.TestCase):
    def test_release_uses_existing_tag_and_matching_download_url(self):
        base = (ROOT / 'packaging/VERSION').read_text().strip()
        for channel, suffix in [('stable', ''), ('beta', '-beta'),
                                ('stable', '-express'), ('beta', '-beta-express')]:
            with self.subTest(channel=channel), tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp)
                # Build the real bundle; gh is the sole external boundary.
                (work / 'packaging').symlink_to(ROOT / 'packaging', target_is_directory=True)
                bin_dir = work / 'bin'
                bin_dir.mkdir()
                (bin_dir / 'python').symlink_to(sys.executable)
                gh = bin_dir / 'gh'
                gh.write_text(f'#!{sys.executable}\nimport json,sys\n'
                              'open("gh-args.json", "w").write(json.dumps(sys.argv[1:]))\n')
                gh.chmod(0o700)
                tag = f'v{base}{suffix}'
                env = {**os.environ, 'PATH': f'{bin_dir}{os.pathsep}{os.environ["PATH"]}',
                       'GITHUB_REF_NAME': tag, 'GITHUB_RUN_NUMBER': '42',
                       'GITHUB_SHA': 'a' * 40, 'GITHUB_ENV': str(work / 'env'),
                       'GITHUB_SERVER_URL': 'https://github.com',
                       'GITHUB_REPOSITORY': 'example/router', 'CHANNEL': channel}
                subprocess.run(['bash', '-e', '-c', run_block('Build bundle')],
                               cwd=work, env=env, check=True, capture_output=True)
                latest = json.loads((work / 'dist/latest.json').read_text())
                self.assertEqual(latest['version'], f'{base}.42')
                self.assertEqual(latest['channel'], channel)
                self.assertIs(latest['express'], suffix.endswith('-express'))
                self.assertEqual((work / 'env').read_text(), f'CHANNEL={channel}\n')
                self.assertEqual(latest['url'],
                                 f'https://github.com/example/router/releases/download/{tag}/'
                                 f'ai-router-{base}.42.tar.gz')
                shutil.copy(work / 'dist/latest.json', work / 'dist/release-latest.json')
                subprocess.run(['bash', '-e', '-c', run_block('Create release')],
                               cwd=work, env=env, check=True, capture_output=True)
                args = json.loads((work / 'gh-args.json').read_text())
                self.assertEqual(args[:3], ['release', 'create', tag])
                self.assertIn('--verify-tag', args)
                self.assertNotIn('--target', args)
                self.assertEqual('--prerelease' in args, channel == 'beta')

    def test_moved_or_deleted_tag_cannot_publish_the_feed(self):
        sha = 'a' * 40
        for remote, status, publishes in [(sha, '0', True), ('b' * 40, '0', False),
                                           ('', '1', False)]:
            with self.subTest(remote=remote), tempfile.TemporaryDirectory() as tmp:
                env = {**os.environ, 'GITHUB_SHA': sha, 'TAG_RESPONSE': remote,
                       'TAG_STATUS': status, 'GITHUB_REPOSITORY': 'example/router',
                       'GITHUB_REF_NAME': 'v1.2.3-beta'}
                stubs = '''
                    gh() {
                      printf '%s\\n' "$*" > api-args
                      printf '%s\\n' "$TAG_RESPONSE"
                      return "$TAG_STATUS"
                    }
                    aws() { printf 'seed-bytes\\n'; }
                    python() { touch published; }
                '''
                result = subprocess.run(
                    ['bash', '-e', '-c', textwrap.dedent(stubs)
                     + run_block('Publish to the update feed')],
                    cwd=tmp, env=env, capture_output=True)
                self.assertEqual(result.returncode == 0, publishes)
                self.assertEqual((Path(tmp) / 'published').exists(), publishes)
                self.assertIn('commits/refs%2Ftags%2Fv1.2.3-beta',
                              (Path(tmp) / 'api-args').read_text())


class InstallerCiGateTests(unittest.TestCase):
    """Plan 156: scoped native installer checks behind the one Test gate."""
    CHECK = (WORKFLOWS / 'check.yml').read_text()
    SETUP = (ROOT / '.github/actions/setup/action.yml').read_text()

    def test_the_test_gate_waits_for_every_installer_job(self):
        self.assertIn(
            'needs: [changes, installer-macos, installer-windows, installer-python39]',
            self.CHECK)
        self.assertIn('if: ${{ !cancelled() }}', self.CHECK)
        self.assertIn(
            "contains(needs.*.result, 'failure') || contains(needs.*.result, 'cancelled')",
            self.CHECK)

    @unittest.skipUnless(os.name == 'posix' and shutil.which('bash'),
                         'runs the workflow step through a POSIX shell with a '
                         'shell-script git stub; the gate itself runs on Ubuntu')
    def test_the_scope_step_fails_closed_and_writes_the_output(self):
        # The exact workflow step: a failed diff must fail it (pipefail), not
        # read as "no installer files changed" and silently skip the native
        # checks while the required gate stays green.
        block = run_block('Installer scope', self.CHECK).replace(
            '${{ github.base_ref }}', 'develop')
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / 'bin'
            bin_dir.mkdir()
            stub = bin_dir / 'git'
            stub.write_text('#!/bin/sh\nprintf "%s\\n" "$GIT_STUB_OUTPUT"\n'
                            'exit "$GIT_STUB_STATUS"\n')
            stub.chmod(0o700)
            out = Path(tmp) / 'out'
            env = {**os.environ, 'PATH': f'{bin_dir}{os.pathsep}{os.environ["PATH"]}',
                   'GIT_STUB_OUTPUT': 'packaging/install.py',
                   'GIT_STUB_STATUS': '0', 'GITHUB_OUTPUT': str(out)}
            subprocess.run(['bash', '-e', '-c', block], cwd=ROOT, env=env,
                           check=True, capture_output=True)
            self.assertIn('installer=true', out.read_text())
            env['GIT_STUB_STATUS'] = '128'
            failed = subprocess.run(['bash', '-e', '-c', block], cwd=ROOT, env=env,
                                    capture_output=True)
            self.assertNotEqual(failed.returncode, 0)

    def test_installer_jobs_are_scope_selected_for_pull_requests(self):
        for job in ('installer-macos', 'installer-windows', 'installer-python39'):
            self.assertIn(f'{job}:', self.CHECK)
        # The producer wiring too: without the step id and the job output no
        # installer job is ever selected, however correct the consumer is.
        self.assertIn('id: scope', self.CHECK)
        self.assertIn('installer: ${{ steps.scope.outputs.installer }}', self.CHECK)
        self.assertIn(
            "if: github.event_name == 'pull_request' && github.base_ref == 'main'",
            self.CHECK)
        self.assertIn("if: needs.changes.outputs.installer == 'true'", self.CHECK)
        self.assertIn('tools/ci_scope.py --installer', self.CHECK)
        self.assertIn('tools/ci_scope.py --installer-tests', self.CHECK)
        self.assertIn('runs-on: macos-latest', self.CHECK)
        self.assertIn('runs-on: windows-latest', self.CHECK)

    def test_runtime_containment_modules_are_never_installer_scoped(self):
        # Plan 156 guard: runtime coverage (port-hijack hardening, shutdown
        # auth, drain, containment, policy scans) must always run in the
        # default suite, never hide behind the installer opt-in.
        import importlib.util
        tool = ROOT / 'tools' / 'ci_scope.py'
        spec = importlib.util.spec_from_file_location('router_ci_scope', tool)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        listed = set(module.INSTALLER_TESTS)
        for name in ('tests.test_lifecycle', 'tests.test_agent_containment',
                     'tests.test_stream_containment', 'tests.test_policy_scans'):
            with self.subTest(module=name):
                self.assertNotIn(name, listed)

    def test_the_39_check_selects_its_interpreter_through_the_composite(self):
        # The composite owns the pin and must pass the version input through;
        # the 3.9 job must not carry a second pin of its own (policy scan
        # enforces that side).
        self.assertIn('python-version: ${{ inputs.python-version }}', self.SETUP)
        self.assertIn('python-version: "3.9"', self.CHECK)
        self.assertIn('tools/check_installer_python39.py', self.CHECK)

    def test_releases_run_the_installer_checks_before_publishing(self):
        self.assertIn(
            'needs: [installer-macos, installer-windows, installer-python39]', RELEASE)
        self.assertIn('!cancelled() &&', RELEASE)
        self.assertIn("contains(needs.*.result, 'failure')", RELEASE)
        self.assertIn('tools/ci_scope.py --installer-tests', RELEASE)
        self.assertIn('tools/check_installer_python39.py', RELEASE)


class WorkflowBoundaryTests(unittest.TestCase):
    def test_release_serializes_feed_and_checks_both_actors(self):
        self.assertIn('group: release-feed\n  cancel-in-progress: false', RELEASE)
        self.assertIn('  queue: max\n', RELEASE)
        for actor in ('github.actor', 'github.triggering_actor'):
            self.assertIn(f'contains(fromJSON(\'["SC-Cyril", "BrentJMaxwell"]\'), {actor})', RELEASE)

    def test_public_prs_keep_read_only_checks_on_both_targets(self):
        check = (WORKFLOWS / 'check.yml').read_text()
        self.assertIn('pull_request:\n    branches: [main, develop]', check)
        self.assertIn('types: [opened, synchronize, reopened, edited]', check)
        self.assertIn('permissions:\n  contents: read', check)
        self.assertIn('persist-credentials: false', check)
        self.assertIn('name: Test\n', check)
        self.assertNotIn('pull_request_target:', check)

if __name__ == '__main__':
    unittest.main()
