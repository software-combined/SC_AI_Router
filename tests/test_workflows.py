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


def run_block(name):
    step = RELEASE.split(f'      - name: {name}\n', 1)[1]
    block = re.search(r'        run: \|\n((?:          [^\n]*\n|\n)+)', step)
    return textwrap.dedent(block[1])


@unittest.skipUnless(os.name == 'posix' and shutil.which('bash'),
                     'release workflow runs on Ubuntu')
class ReleaseShellTests(unittest.TestCase):
    def test_release_uses_existing_tag_and_matching_download_url(self):
        base = (ROOT / 'packaging/VERSION').read_text().strip()
        for channel, suffix in [('stable', ''), ('beta', '-beta')]:
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
