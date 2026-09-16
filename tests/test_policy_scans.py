"""Plan 134: the policy-scan script's decision points.

The scanner replaced inline CI shell, so its globbing, skip rules and step
matcher need a runnable pin: each case below is a bypass found by review.
Runs against a temporary tree so nothing here touches the real repository.
"""
import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The probe strings are assembled from fragments: the policy scan reads this
# file too, and a literal token here would (correctly) fail its own gate.
SECRET_BYTES = (b'sk-' + b'or-v1-' + b'a' * 24)
CAP_BYTES = b'DEFAULT_' + b'REQUEST' + b'_CAP = 5\n'
# The scan-check name is built the same way: this file is inside the scanned
# tree, so it must not carry the literal it exists to detect.
CAP_CHECK = 'check_' + 'request' + '_cap'
# Assembled from fragments for the same reason: the account-id scan reads this
# file too, and a literal here would (correctly) fail its own gate.
ACCOUNT_PROBE = (b'arn:aws:iam::' + b'1' * 12 + b':role/publisher')
BUCKET_PROBE = b'scg-router-feed-' + b'2' * 12 + b'-apse2'


class ProviderKeyIgnoreTests(unittest.TestCase):
    """A provider's key file must be ignored before anyone writes one."""

    def test_every_external_key_file_is_ignored(self):
        from ai_router import provider_defs
        names = sorted(defn.key.file for defn in provider_defs.external_defs())
        self.assertTrue(names)
        result = subprocess.run(['git', 'check-ignore', *names], cwd=ROOT,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        ignored = result.stdout.split()
        for name in names:
            with self.subTest(key_file=name):
                self.assertIn(name, ignored)


def _load(root):
    """Import tools/check_policy_scans.py bound to `root` as its repository."""
    spec = importlib.util.spec_from_file_location(
        'policy_scans_under_test', root / 'tools' / 'check_policy_scans.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = root
    return module


class PolicyScanTests(unittest.TestCase):
    def _tree(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        root = Path(tmp)
        for rel in ('tools', 'ai_router', 'packaging', 'tests',
                    '.github/workflows', '.github/actions/setup'):
            (root / rel).mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / 'tools' / 'check_policy_scans.py',
                    root / 'tools' / 'check_policy_scans.py')
        shutil.copy(ROOT / '.github' / 'actions' / 'setup' / 'action.yml',
                    root / '.github' / 'actions' / 'setup' / 'action.yml')
        for name in ('check.yml', 'release.yml'):
            (root / '.github' / 'workflows' / name).write_text(
                'steps:\n  - uses: ./.github/actions/setup\n')
        (root / 'ai_router' / 'ok.py').write_text('x = 1\n')
        return root

    def test_clean_tree_passes(self):
        module = _load(self._tree())
        self.assertTrue(getattr(module, CAP_CHECK)())
        self.assertTrue(module.check_secrets())
        self.assertTrue(module.check_publication_identifiers())
        self.assertTrue(module.check_setup_single_owner())

    def test_an_account_identifier_anywhere_is_caught(self):
        # Non-vacuous: an account id inside an ARN, and one inside a
        # bucket-shaped name, each fail the scan on a tree that is otherwise
        # clean (Plan 160).
        for probe in (ACCOUNT_PROBE, BUCKET_PROBE):
            with self.subTest(probe=probe[:10]):
                root = self._tree()
                (root / 'infra').mkdir(exist_ok=True)
                (root / 'infra' / 'feed.yaml').write_bytes(
                    b'BucketName: ' + probe + b'\n')
                module = _load(root)
                self.assertFalse(module.check_publication_identifiers())

    def test_cap_token_outside_the_old_directories_is_caught(self):
        root = self._tree()
        (root / 'infra').mkdir()
        (root / 'infra' / 'stack.py').write_bytes(CAP_BYTES)
        self.assertFalse(getattr(_load(root), CAP_CHECK)())

    def test_source_less_pyc_with_a_secret_is_caught(self):
        # A force-added cache artefact must not hide a committed key.
        root = self._tree()
        cache = root / 'packaging' / '__pycache__'
        cache.mkdir()
        (cache / 'leak.cpython-314.pyc').write_bytes(SECRET_BYTES)
        self.assertFalse(_load(root).check_secrets())

    def test_derived_bytecode_is_skipped(self):
        root = self._tree()
        cache = root / 'packaging' / '__pycache__'
        cache.mkdir()
        (root / 'packaging' / 'clean.py').write_text('x = 1\n')
        (cache / 'clean.cpython-314.pyc').write_bytes(SECRET_BYTES)
        self.assertTrue(_load(root).check_secrets())

    def test_git_metadata_is_ignored(self):
        root = self._tree()
        (root / '.git' / 'logs').mkdir(parents=True)
        (root / '.git' / 'logs' / 'HEAD').write_text(
            'commit: refactor ' + 'request' + '_cap guard\n')
        self.assertTrue(getattr(_load(root), CAP_CHECK)())

    def test_yaml_workflow_with_its_own_pin_is_caught(self):
        root = self._tree()
        (root / '.github' / 'workflows' / 'extra.yaml').write_text(
            'steps:\n  - uses: actions/setup-python@'
            'a26af69be951a213d495a4c3e4e4022e16d87065\n')
        self.assertFalse(_load(root).check_setup_single_owner())

    def test_commented_out_composite_step_does_not_count(self):
        root = self._tree()
        (root / '.github' / 'workflows' / 'check.yml').write_text(
            'steps:\n  # - uses: ./.github/actions/setup\n')
        self.assertFalse(_load(root).check_setup_single_owner())

    def test_step_with_a_trailing_comment_still_counts(self):
        root = self._tree()
        (root / '.github' / 'workflows' / 'check.yml').write_text(
            'steps:\n  - uses: ./.github/actions/setup  # shared pin owner\n')
        self.assertTrue(_load(root).check_setup_single_owner())

    def test_two_line_named_step_still_counts(self):
        root = self._tree()
        (root / '.github' / 'workflows' / 'check.yml').write_text(
            'steps:\n  - name: Python setup\n'
            '    uses: ./.github/actions/setup\n')
        self.assertTrue(_load(root).check_setup_single_owner())

    def test_missing_scanned_path_fails_closed(self):
        module = _load(self._tree())
        with self.assertRaises(SystemExit):
            list(module._iter_files(('no-such-dir',)))


if __name__ == '__main__':
    unittest.main()
