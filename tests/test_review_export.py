"""The PR export preserves review scope and excludes private receipt fields."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
EXPORT = ROOT / "plugins/scg-review/scripts/export_review.py"


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
        config.write_text(json.dumps({"required_lanes": ["correctness", "quality", "adversarial"]}))
        root = self.git("rev-parse", "--show-toplevel").strip()
        repo_id = hashlib.sha256(root.encode()).hexdigest()
        tree = self.git("rev-parse", "HEAD^{tree}").strip()
        self.receipt = Path(self.temp.name) / ".cache/scg-agent-git-hooks/reviews" / repo_id / f"{tree}.review.json"
        self.receipt.parent.mkdir(parents=True)
        self.state = {"version": 2, "repo_root": root, "repo_id": repo_id, "branch": "feature",
                      "tree": tree, "decision": "ALL_CLEAR", "approved": True,
                      "created_at_epoch": int(time.time()),
                      "passes": dict.fromkeys(["correctness", "quality", "adversarial"],
                                              "fixture@high::unverified@unverified"),
                      "summary": "PRIVATE-FREE-TEXT", "runner": "PRIVATE-HOST"}
        self.save()

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.repo, env=self.env, text=True)

    def save(self):
        self.receipt.write_text(json.dumps(self.state))

    def export(self, url="https://github.com/example/project/actions/runs/123"):
        return subprocess.run([sys.executable, str(EXPORT), "--verification-url", url],
                              cwd=self.repo, env=self.env, text=True, capture_output=True)

    def test_export_binds_commit_tree_and_checks_without_private_fields(self):
        result = self.export()
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["commit"], self.git("rev-parse", "HEAD").strip())
        self.assertEqual(data["tree"], self.state["tree"])
        self.assertEqual(data["passes"], self.state["passes"])
        self.assertEqual(data["verification_urls"], ["https://github.com/example/project/actions/runs/123"])
        for private in [self.temp.name, "PRIVATE-FREE-TEXT", "PRIVATE-HOST", "repo_root", "repo_id"]:
            self.assertNotIn(private, result.stdout)

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


if __name__ == "__main__":
    unittest.main()
