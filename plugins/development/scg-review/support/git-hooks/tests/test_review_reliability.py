"""Real Git regressions for receipt scope and chained commit/merge hooks."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest import mock

from test_interpreter_selection import setup
import test_review_gate as gate_fixture


HOOKS = Path(__file__).resolve().parents[1]


class ReviewReliabilityTest(unittest.TestCase):
    def setUp(self):
        self.fixture = gate_fixture.ReviewGateTest(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def run_git(self, *args):
        return subprocess.run(["git", *args], cwd=self.fixture.repo,
                              env=self.fixture.env, capture_output=True, text=True)

    def install_hooks(self):
        target = self.fixture.home / ".config/scg-agent-git-hooks"
        for relative in setup.FILES:
            source = HOOKS / relative
            if source.is_file():
                dest = target / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, dest)
                dest.chmod(0o755)
        config = target / "config.json"
        data = json.loads(config.read_text())
        data["interpreter"] = sys.executable
        config.write_text(json.dumps(data))
        self.fixture.git("config", "core.hooksPath", str(target))

    def local_hook(self, name, body):
        hook = self.fixture.repo / ".git/hooks" / name
        hook.write_text(f"#!{Path(sys.executable).as_posix()}\n" + body)
        hook.chmod(0o755)

    def merge_branches(self):
        self.fixture.git("commit", "-m", "test: initial fixture")
        self.fixture.git("checkout", "-b", "other")
        (self.fixture.repo / "other.txt").write_text("other\n")
        self.fixture.git("add", "other.txt")
        self.fixture.git("commit", "-m", "test: other fixture")
        self.fixture.git("checkout", "main")
        (self.fixture.repo / "main.txt").write_text("main\n")
        self.fixture.git("add", "main.txt")
        self.fixture.git("commit", "-m", "test: main fixture")

    def test_unborn_receipt_records_explicit_base(self):
        self.assertEqual(self.fixture.approve().returncode, 0)
        receipt, = self.fixture.state_dir().glob("*.review.json")
        data = json.loads(receipt.read_text())
        self.assertEqual(data["version"], 3)
        self.assertIn("base_commit", data)
        self.assertIsNone(data["base_commit"])
        self.assertEqual(self.fixture.helper("pre-commit").returncode, 0)

    def test_changed_head_rejects_same_tree_receipt_and_preserves_history(self):
        self.assertEqual(self.fixture.approve().returncode, 0)
        before = {p: p.read_bytes() for p in self.fixture.state_dir().glob("*.review.json")}
        tree = self.fixture.tree()
        self.fixture.git("commit", "-m", "test: advance fixture head")
        self.assertEqual(self.fixture.tree(), tree)
        self.assertNotEqual(self.fixture.helper("pre-commit").returncode, 0)
        self.assertEqual(self.fixture.approve().returncode, 0)
        self.assertEqual(len(list(self.fixture.state_dir().glob("*.review.json"))), 2)
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)

    def test_legacy_receipt_is_preserved_but_cannot_approve(self):
        self.assertEqual(self.fixture.approve().returncode, 0)
        receipt, = self.fixture.state_dir().glob("*.review.json")
        data = json.loads(receipt.read_text())
        data["version"] = 2
        receipt.write_text(json.dumps(data))
        self.assertNotEqual(self.fixture.helper("pre-commit").returncode, 0)
        self.assertEqual(json.loads(receipt.read_text())["version"], 2)

    def test_chained_hook_cannot_stage_an_unreviewed_tree(self):
        self.local_hook("pre-commit", "import pathlib, subprocess\n"
                        "pathlib.Path('file.txt').write_text('changed by hook\\n')\n"
                        "subprocess.run(['git', 'add', 'file.txt'], check=True)\n")
        self.assertEqual(self.fixture.approve().returncode, 0)
        tree = self.fixture.tree()
        done = self.fixture.helper("pre-commit")
        self.assertNotEqual(self.fixture.tree(), tree)
        self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("scope changed", done.stderr)

    def test_chained_hook_rejection_is_preserved(self):
        self.local_hook("pre-commit", "import sys\nsys.exit(7)\n")
        self.assertEqual(self.fixture.approve().returncode, 0)
        self.assertEqual(self.fixture.helper("pre-commit").returncode, 7)

    def test_automatic_merge_requires_a_receipt(self):
        self.merge_branches()
        self.install_hooks()
        head = self.fixture.git("rev-parse", "HEAD").stdout.strip()
        done = self.run_git("merge", "--no-edit", "other")
        self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.fixture.git("rev-parse", "HEAD").stdout.strip(), head)
        self.assertIn("review", done.stderr.lower())

    def test_reviewed_automatic_merge_chains_original_merge_hook(self):
        self.merge_branches()
        self.fixture.git("merge", "--no-commit", "other")
        self.assertEqual(self.fixture.approve().returncode, 0)
        self.fixture.git("merge", "--abort")
        self.local_hook("pre-merge-commit", "import pathlib\n"
                        "pathlib.Path('merge-hook-ran').write_text('yes')\n")
        self.install_hooks()
        done = self.run_git("merge", "--no-edit", "other")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue((self.fixture.repo / "merge-hook-ran").exists())

    def test_commit_message_hook_cannot_stage_after_review(self):
        self.local_hook("commit-msg", "import pathlib, subprocess\n"
                        "pathlib.Path('file.txt').write_text('late change\\n')\n"
                        "subprocess.run(['git', 'add', 'file.txt'], check=True)\n")
        self.assertEqual(self.fixture.approve().returncode, 0)
        self.install_hooks()
        done = self.run_git("commit", "-m", "test: reviewed fixture")
        self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("scope changed", done.stderr)

    @unittest.skipIf(os.name == "nt", "uses a POSIX scanner fixture")
    def test_corrupt_copy_cannot_activate_fresh_hooks(self):
        self.fixture.pin_scanner(self.fixture.write_fake_scanner())
        config = json.loads((self.fixture.home / ".config/scg-agent-git-hooks/config.json").read_text())
        config["gitleaks"]["provenance"] = "synthetic test fixture"
        home = self.fixture.home / "fresh-install"
        copy = shutil.copy2

        def corrupt(source, dest):
            copy(source, dest)
            if source.name == "pre-commit":
                dest.write_text("corrupt copy\n")

        with mock.patch.dict(os.environ, self.fixture.env), \
                mock.patch.object(setup.shutil, "copy2", side_effect=corrupt):
            with self.assertRaisesRegex(ValueError, "adapter differs"):
                setup.provision(self.fixture.repo, config, install=True, home=home)
        self.assertFalse((home / ".config/scg-agent-git-hooks").exists())
        self.assertEqual(self.run_git("config", "--local", "--get", "core.hooksPath").returncode, 1)


if __name__ == "__main__":
    unittest.main()
