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
MAIN_ACCEPTANCE = ("(github.event_name == 'pull_request' && github.base_ref == 'main') || "
                   "(github.event_name == 'push' && github.ref == 'refs/heads/main')")
NOT_A_TEXT_EDIT = "(github.event.action != 'edited' || github.event.changes.base)"


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
                self.assertEqual(args[args.index('--title') + 1], tag)
                self.assertEqual('--prerelease' in args, channel == 'beta')

    def test_moved_or_deleted_tag_cannot_publish_the_feed(self):
        sha = 'a' * 40
        for remote, status, publishes in [(sha, '0', True), ('b' * 40, '0', False),
                                           ('', '1', False)]:
            with self.subTest(remote=remote), tempfile.TemporaryDirectory() as tmp:
                env = {**os.environ, 'GITHUB_SHA': sha, 'TAG_RESPONSE': remote,
                       'TAG_STATUS': status, 'GITHUB_REPOSITORY': 'example/router',
                       'GITHUB_REF_NAME': 'v0.6.123-beta'}
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
                self.assertIn('commits/refs%2Ftags%2Fv0.6.123-beta',
                              (Path(tmp) / 'api-args').read_text())


class InstallerCiGateTests(unittest.TestCase):
    """Plan 156: scoped native installer checks behind the one Test gate."""
    CHECK = (WORKFLOWS / 'check.yml').read_text()
    SETUP = (ROOT / '.github/actions/setup/action.yml').read_text()

    def test_required_gate_waits_for_all_scoped_jobs(self):
        self.assertIn(
            'needs: [changes, installer-macos, installer-windows, installer-python39, plugin-schedulers, hook-adapter]',
            self.CHECK)
        self.assertIn('if: ${{ !cancelled() && ' + NOT_A_TEXT_EDIT + ' }}', self.CHECK)
        self.assertIn(
            "contains(needs.*.result, 'failure') || contains(needs.*.result, 'cancelled')",
            self.CHECK)

    def test_the_hook_adapter_tests_run_on_windows_and_posix(self):
        # Plan 156's lesson: a green required check that never executes the
        # tests is worse than no check. Pin the wiring, not just the file.
        # Scope the assertions to this job: plugin-schedulers carries the same
        # matrix string, so an unscoped assertIn would stay green even if this
        # job's matrix were narrowed to one runner.
        self.assertIn('hook-adapter:', self.CHECK)
        job = self.CHECK.split('hook-adapter:', 1)[1]
        self.assertIn('os: [ubuntu-latest, windows-latest]', job)
        self.assertIn('support/git-hooks/tests', job)

    @unittest.skipUnless(os.name == 'posix' and shutil.which('bash'),
                         'runs the workflow step through a POSIX shell with a '
                         'shell-script git stub; the gate itself runs on Ubuntu')
    def test_the_scope_step_fails_closed_and_writes_the_output(self):
        # The exact workflow step: a failed diff must fail it (pipefail), not
        # read as "no installer files changed" and silently skip the native
        # checks while the required gate stays green.
        block = (run_block('Installer scope', self.CHECK)
                 .replace('${{ github.base_ref }}', 'development')
                 .replace('${{ github.event.before }}', 'before')
                 .replace('${{ github.sha }}', 'after'))
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / 'bin'
            bin_dir.mkdir()
            stub = bin_dir / 'git'
            stub.write_text('#!/bin/sh\nprintf "%s\\n" "$GIT_STUB_OUTPUT"\n'
                            'exit "$GIT_STUB_STATUS"\n')
            stub.chmod(0o700)
            for event in ('pull_request', 'push'):
                out = Path(tmp) / f'{event}.out'
                env = {**os.environ, 'PATH': f'{bin_dir}{os.pathsep}{os.environ["PATH"]}',
                       'GITHUB_EVENT_NAME': event, 'GIT_STUB_OUTPUT': 'packaging/install.py',
                       'GIT_STUB_STATUS': '0', 'GITHUB_OUTPUT': str(out)}
                subprocess.run(['bash', '-e', '-c', block], cwd=ROOT, env=env,
                               check=True, capture_output=True)
                self.assertIn('installer=true', out.read_text())
                env['GIT_STUB_STATUS'] = '128'
                failed = subprocess.run(['bash', '-e', '-c', block], cwd=ROOT, env=env,
                                        capture_output=True)
                self.assertNotEqual(failed.returncode, 0)

    def test_installer_jobs_are_scope_selected_for_main_acceptance(self):
        for job in ('installer-macos', 'installer-windows', 'installer-python39'):
            self.assertIn(f'{job}:', self.CHECK)
        # The producer wiring too: without the step id and the job output no
        # installer job is ever selected, however correct the consumer is.
        self.assertIn('id: scope', self.CHECK)
        self.assertIn('installer: ${{ steps.scope.outputs.installer }}', self.CHECK)
        self.assertIn(MAIN_ACCEPTANCE, self.CHECK)
        self.assertIn("if: needs.changes.outputs.installer == 'true'", self.CHECK)
        self.assertIn('github.event.before', self.CHECK)
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

    def test_releases_require_acceptance_before_publishing(self):
        self.assertNotIn('tools/ci_scope.py --installer-tests', RELEASE)
        self.assertNotIn('unittest discover', RELEASE)
        self.assertIn('fetch-depth: 0', RELEASE)
        self.assertIn('actions: read', RELEASE)
        self.assertIn('actions/workflows/check.yml/runs?head_sha=$GITHUB_SHA', RELEASE)
        self.assertIn('.event == "push"', RELEASE)
        self.assertIn('.head_branch == "main"', RELEASE)
        self.assertLess(RELEASE.index('name: Require an accepted commit'),
                        RELEASE.index('uses: ./.github/actions/setup'))
        self.assertLess(RELEASE.index('name: Require an accepted commit'),
                        RELEASE.index('name: Build bundle'))

    def test_release_acceptance_runs_for_main_pull_requests_and_pushes(self):
        for name in ('changes', 'plugin-schedulers', 'hook-adapter'):
            job = re.split(r'\n  \S', self.CHECK.split(f'  {name}:\n', 1)[1], maxsplit=1)[0]
            self.assertIn(f'if: {NOT_A_TEXT_EDIT} && ({MAIN_ACCEPTANCE})', job)
        step = self.CHECK.split('      - name: Unit suite (offline)\n', 1)[1]
        self.assertIn(f'if: {MAIN_ACCEPTANCE}', step.split('      - name:', 1)[0])

    @unittest.skipUnless(shutil.which('git') and shutil.which('bash'), 'requires git and bash')
    def test_release_requires_an_accepted_commit_for_its_channel(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp, 'bin'); bin_dir.mkdir()
            gh = bin_dir / 'gh'
            # Every call leaves a marker. 'error' prints an accepting count but
            # fails, and a non-number count must also stop the job.
            gh.write_text('#!/bin/sh\ntouch gh-called\n'
                          '[ "$ACCEPTANCE_COUNT" = error ] && { echo 1; exit 1; }\n'
                          'printf "%s\\n" "$ACCEPTANCE_COUNT"\n'); gh.chmod(0o700)
            env = {**os.environ, 'PATH': f'{bin_dir}{os.pathsep}{os.environ["PATH"]}',
                   'GITHUB_REPOSITORY': 'example/router', 'GIT_AUTHOR_NAME': 'Probe',
                   'GIT_COMMITTER_NAME': 'Probe',
                   'GIT_AUTHOR_EMAIL': 'probe@example.invalid',
                   'GIT_COMMITTER_EMAIL': 'probe@example.invalid'}
            def git(*args, stdin=None):
                return subprocess.run(['git', *args], cwd=tmp, env=env, input=stdin,
                                      text=True, capture_output=True, check=True).stdout.strip()
            git('init', '--quiet')
            tree = git('mktree', stdin='')
            base = git('commit-tree', tree, '-m', 'base')
            main_only = git('commit-tree', tree, '-p', base, '-m', 'main only')
            develop_only = git('commit-tree', tree, '-p', base, '-m', 'develop only')
            feature = git('commit-tree', tree, '-p', base, '-m', 'merged feature commit')
            develop_tip = git('commit-tree', tree, '-p', develop_only, '-p', feature, '-m', 'merge')
            unmerged = git('commit-tree', tree, '-p', develop_only, '-m', 'unmerged')
            git('update-ref', 'refs/remotes/origin/main', main_only)
            git('update-ref', 'refs/remotes/origin/development', develop_tip)
            beta, stable = 'v0.6.123-beta', 'v0.6.123'
            # (tag, commit, successful main Check runs, publishes, asks gh)
            for tag, sha, count, allowed, asks_gh in (
                    (beta, develop_only, 0, True, False), (beta, develop_tip, 0, True, False),
                    (beta + '-express', develop_only, 0, True, False), (beta, main_only, 0, True, False),
                    (beta, unmerged, 1, False, False), (beta, '0' * 40, 1, False, False),
                    (beta, feature, 0, False, False),
                    (stable, develop_only, 1, False, False),
                    (stable + '-express', develop_only, 1, False, False),
                    (stable, '0' * 40, 1, False, False), (stable, main_only, 0, False, True),
                    (stable, main_only, 'error', False, True), (stable, main_only, 'noise', False, True),
                    (stable, main_only, 1, True, True)):
                with self.subTest(tag=tag, sha=sha, count=count):
                    Path(tmp, 'gh-called').unlink(missing_ok=True)
                    result = subprocess.run(
                        ['bash', '-e', '-c', run_block('Require an accepted commit')],
                        cwd=tmp, env={**env, 'GITHUB_REF_NAME': tag, 'GITHUB_SHA': sha,
                                     'ACCEPTANCE_COUNT': str(count)}, capture_output=True)
                    self.assertEqual(result.returncode == 0, allowed)
                    self.assertEqual(Path(tmp, 'gh-called').exists(), asks_gh)

    @unittest.skipUnless(shutil.which('jq'), 'requires jq to evaluate the gh filter')
    def test_acceptance_query_only_counts_successful_main_runs(self):
        expression = re.search(r"--jq '([^']+)'", RELEASE).group(1)
        sha = 'a' * 40
        accepted = {'head_sha': sha, 'event': 'push', 'head_branch': 'main',
                    'status': 'completed', 'conclusion': 'success'}
        cases = [
            ([accepted], 1),
            ([{**accepted, 'conclusion': 'failure'}], 0),
            ([{**accepted, 'status': 'in_progress', 'conclusion': None}], 0),
            ([{**accepted, 'head_branch': 'development'}], 0),
            ([{**accepted, 'head_sha': 'b' * 40}], 0),
        ]
        env = {**os.environ, 'GITHUB_SHA': sha}
        for runs, expected in cases:
            with self.subTest(runs=runs):
                result = subprocess.run(
                    ['jq', '-c', expression], input=json.dumps({'workflow_runs': runs}),
                    env=env, text=True, capture_output=True, check=True)
                self.assertEqual(result.stdout.strip(), str(expected))


class WorkflowBoundaryTests(unittest.TestCase):
    def test_release_serializes_feed_and_checks_both_actors(self):
        self.assertIn('group: release-feed\n  cancel-in-progress: false', RELEASE)
        self.assertIn('  queue: max\n', RELEASE)
        for actor in ('github.actor', 'github.triggering_actor'):
            self.assertIn(f'contains(fromJSON(\'["SC-Cyril", "BrentJMaxwell"]\'), {actor})', RELEASE)

    def test_public_prs_keep_read_only_checks_on_both_targets(self):
        check = (WORKFLOWS / 'check.yml').read_text()
        self.assertIn('pull_request:\n    branches: [main, development]', check)
        self.assertIn('types: [opened, synchronize, reopened, edited]', check)
        self.assertIn('permissions:\n  contents: read', check)
        self.assertIn('persist-credentials: false', check)
        # A title or body edit must not cancel running checks, and a skipped
        # gate must not carry the required name Test (skipped reads as passed).
        self.assertIn("!github.event.changes.base && format('-text-edit-{0}', github.run_id) || '' }}", check)
        self.assertIn("name: ${{ " + NOT_A_TEXT_EDIT + " && 'Test' || 'Skipped for a title or body edit' }}\n", check)
        self.assertNotIn('pull_request_target:', check)

if __name__ == '__main__':
    unittest.main()
