"""The PR export preserves review scope and excludes private receipt fields."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
EXPORT = ROOT.parent / "plugins/development/scg-review/scripts/export_review.py"


@unittest.skipUnless(shutil.which('git'), 'requires real Git integration')
class ReviewExportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        self.env = {**os.environ, "HOME": self.temp.name, "USERPROFILE": self.temp.name,
                    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
        self.git("init", "-b", "feature")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("remote", "add", "origin", "https://github.com/example/project.git")
        (self.repo / "file.txt").write_text("fixture\n")
        self.git("add", "file.txt")
        self.git("commit", "-m", "test: fixture")
        config = Path(self.temp.name) / ".config/scg-agent-git-hooks/config.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"required_lanes": ["correctness", "quality", "adversarial", "security"]}))
        root = self.git("rev-parse", "--show-toplevel").strip()
        repo_id = hashlib.sha256(root.encode()).hexdigest()
        tree = self.git("rev-parse", "HEAD^{tree}").strip()
        self.receipt = Path(self.temp.name) / ".cache/scg-agent-git-hooks/reviews" / repo_id / f"{tree}.unborn.review.json"
        self.receipt.parent.mkdir(parents=True)
        self.state = {"version": 3, "repo_root": root, "repo_id": repo_id, "branch": "feature",
                      "tree": tree, "base_commit": None, "decision": "ALL_CLEAR", "approved": True,
                      "created_at_epoch": int(time.time()),
                      "passes": dict.fromkeys(["correctness", "quality", "adversarial", "security"],
                                              "fixture@high::unverified@unverified"),
                      "summary": "PRIVATE-FREE-TEXT", "runner": "PRIVATE-HOST"}
        self.save()

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.repo, env=self.env, text=True)

    def save(self):
        self.receipt.write_text(json.dumps(self.state))

    def record_review(self):
        base = self.git("rev-parse", "HEAD").strip()
        tree = self.git("write-tree").strip()
        self.state.update(base_commit=base, tree=tree)
        self.receipt = self.receipt.parent / f"{tree}.{base}.review.json"
        self.save()
        return base

    def export(self, url="https://github.com/example/project/actions/runs/123"):
        return subprocess.run([sys.executable, str(EXPORT), "--verification-url", url],
                              cwd=self.repo, env=self.env, text=True, capture_output=True)

    def test_export_binds_commit_tree_and_checks_without_private_fields(self):
        result = self.export()
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["commit"], self.git("rev-parse", "HEAD").strip())
        self.assertEqual(data["tree"], self.state["tree"])
        self.assertIsNone(data["base_commit"])
        self.assertEqual(data["passes"], self.state["passes"])
        self.assertEqual(data["verification_urls"], ["https://github.com/example/project/actions/runs/123"])
        for private in [self.temp.name, "PRIVATE-FREE-TEXT", "PRIVATE-HOST", "repo_root", "repo_id"]:
            self.assertNotIn(private, result.stdout)

    def test_router_bundle_can_execute_the_review_export(self):
        spec = importlib.util.spec_from_file_location("release", ROOT / "packaging/release.py")
        release = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(release)
        bundle = Path(self.temp.name) / "bundle"
        for name in release.plugin_files(ROOT):
            if not name.startswith("plugins/development/scg-review/"):
                continue
            target = bundle / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(release.source_file(ROOT, name), target)
        exporter = bundle / EXPORT.relative_to(ROOT.parent)
        result = subprocess.run([sys.executable, str(exporter), "--verification-url",
                                 "https://github.com/example/project/actions/runs/123"],
                                cwd=self.repo, env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["tree"], self.state["tree"])

    def test_invalid_receipt_cannot_be_published(self):
        for field, value in [("tree", "0" * 40), ("branch", "other"),
                             ("created_at_epoch", 1), ("decision", "BLOCK"),
                             ("passes", {"correctness": "fixture"})]:
            with self.subTest(field=field):
                original = self.state[field]
                self.state[field] = value
                self.save()
                result = self.export()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.state[field] = original
        self.save()

    def test_dirty_tree_missing_receipt_and_unsafe_urls_are_refused(self):
        (self.repo / "file.txt").write_text("changed\n")
        self.assertNotEqual(self.export().returncode, 0)
        (self.repo / "file.txt").write_text("fixture\n")
        for url in ["https://github.com/other/project/actions/runs/123",
                    "https://github.com/example/project/actions/runs/123?token=private"]:
            self.assertNotEqual(self.export(url).returncode, 0)
        self.receipt.unlink()
        self.assertNotEqual(self.export().returncode, 0)

    def test_same_tree_later_commit_cannot_reuse_export(self):
        self.git("commit", "--allow-empty", "-m", "test: later fixture commit")
        result = self.export()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")

    def test_export_binds_a_non_root_commit_to_its_reviewed_base(self):
        (self.repo / "file.txt").write_text("reviewed update\n")
        self.git("add", "file.txt")
        base = self.record_review()
        self.git("commit", "-m", "test: reviewed update")
        result = self.export()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["base_commit"], base)

    def test_reviewed_root_amendment_exports_against_the_replaced_head(self):
        (self.repo / "file.txt").write_text("reviewed root amendment\n")
        self.git("add", "file.txt")
        base = self.record_review()
        self.git("commit", "--amend", "-m", "test: amended root")
        result = self.export()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["base_commit"], base)

    def test_reviewed_non_root_amendment_survives_a_branch_checkout(self):
        (self.repo / "file.txt").write_text("second commit\n")
        self.git("add", "file.txt")
        self.git("commit", "-m", "test: second fixture")
        base = self.record_review()
        self.git("commit", "--amend", "-m", "test: amended second fixture")
        self.git("checkout", "-b", "other")
        self.git("checkout", "feature")
        result = self.export()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["base_commit"], base)

    def test_unreviewed_same_tree_amendment_cannot_reuse_parent_receipt(self):
        self.git("commit", "--amend", "-m", "test: unreviewed amendment")
        result = self.export()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")

    def test_missing_amendment_reflog_fails_closed_with_a_recovery_route(self):
        self.record_review()
        self.git("commit", "--amend", "-m", "test: reviewed amendment")
        self.git("reflog", "expire", "--expire=all", "--all")
        result = self.export()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("reflog", result.stderr.lower())
        self.assertIn("new regular commit", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_missing_amendment_predecessor_cannot_fall_back_to_parent_receipt(self):
        self.record_review()
        self.git("commit", "--amend", "-m", "test: reviewed amendment")
        self.git("reflog", "delete", "--rewrite", "refs/heads/feature@{1}")
        result = self.export()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("new regular commit", result.stderr)

    def test_ambiguous_reflog_action_fails_closed(self):
        self.record_review()
        self.env["GIT_REFLOG_ACTION"] = "unknown fixture operation"
        self.git("commit", "--amend", "-m", "test: ambiguous amendment")
        result = self.export()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("reflog", result.stderr.lower())
        self.assertIn("new regular commit", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_rewritten_amendment_predecessor_cannot_select_an_older_receipt(self):
        self.record_review()
        self.git("commit", "--allow-empty", "-m", "test: later fixture")
        self.record_review()
        self.git("commit", "--amend", "--allow-empty", "-m", "test: reviewed amendment")
        self.git("reflog", "delete", "--rewrite", "refs/heads/feature@{1}")
        result = self.export()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("new regular commit", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_consecutive_amendments_use_exact_transition_after_a_reflog_gap(self):
        self.record_review()
        self.git("commit", "--amend", "-m", "test: first amendment")
        base = self.record_review()
        self.git("commit", "--amend", "-m", "test: second amendment")
        self.git("reflog", "delete", "refs/heads/feature@{1}")
        result = self.export()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["base_commit"], base)

    def test_unreviewed_consecutive_amendment_cannot_reuse_older_sibling_receipt(self):
        self.record_review()
        self.git("commit", "--amend", "-m", "test: first amendment")
        self.git("commit", "--amend", "-m", "test: unreviewed second amendment")
        self.git("reflog", "delete", "refs/heads/feature@{1}")
        result = self.export()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")

    def test_export_binds_a_merge_commit_to_its_reviewed_base(self):
        self.git("checkout", "-b", "other")
        (self.repo / "other.txt").write_text("other\n")
        self.git("add", "other.txt")
        self.git("commit", "-m", "test: other fixture")
        self.git("checkout", "feature")
        self.git("commit", "--allow-empty", "-m", "test: feature fixture")
        self.git("merge", "--no-commit", "other")
        base = self.record_review()
        self.git("commit", "-m", "test: reviewed merge")
        result = self.export()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["base_commit"], base)

    def test_reviewed_conflicted_cherry_pick_continuation_exports(self):
        self.git("checkout", "-b", "incoming")
        (self.repo / "file.txt").write_text("incoming change\n")
        self.git("add", "file.txt")
        self.git("commit", "-m", "test: incoming change")
        incoming = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "feature")
        (self.repo / "file.txt").write_text("local change\n")
        self.git("add", "file.txt")
        self.git("commit", "-m", "test: local change")
        conflict = subprocess.run(["git", "cherry-pick", incoming], cwd=self.repo,
                                  env=self.env, capture_output=True, text=True)
        self.assertNotEqual(conflict.returncode, 0)
        self.assertEqual(self.git("rev-parse", "CHERRY_PICK_HEAD").strip(), incoming)
        (self.repo / "file.txt").write_text("reviewed resolution\n")
        self.git("add", "file.txt")
        base = self.record_review()
        self.env["GIT_EDITOR"] = ":"
        self.git("cherry-pick", "--continue")
        self.assertTrue(self.git("reflog", "-1", "--format=%gs").startswith("commit (cherry-pick): "))
        result = self.export()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["base_commit"], base)

    def test_reviewed_clean_cherry_pick_exports(self):
        self.git("checkout", "-b", "incoming")
        (self.repo / "incoming.txt").write_text("incoming change\n")
        self.git("add", "incoming.txt")
        self.git("commit", "-m", "test: clean incoming change")
        incoming = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "feature")
        self.git("cherry-pick", "--no-commit", incoming)
        base = self.record_review()
        self.git("restore", "--source=HEAD", "--staged", "--worktree", ".")
        self.git("cherry-pick", incoming)
        self.assertTrue(self.git("reflog", "-1", "--format=%gs").startswith("cherry-pick: "))
        result = self.export()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["base_commit"], base)


if __name__ == "__main__":
    unittest.main()
