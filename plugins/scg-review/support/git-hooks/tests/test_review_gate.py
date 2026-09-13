from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


HELPER = Path(__file__).resolve().parents[1] / "lib" / "scg_agent_git_hooks.py"
LANE_ARGS = [
    "--pass",
    "correctness=model-c",
    "--pass",
    "quality=model-q",
    "--pass",
    "adversarial=model-a",
]


class ReviewGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name) / "home"
        self.repo = Path(self.temp.name) / "repo"
        config_dir = self.home / ".config" / "scg-agent-git-hooks"
        config_dir.mkdir(parents=True)
        (config_dir / "config.json").write_text(
            json.dumps(
                {
                    "review_state_ttl_seconds": 86400,
                    "required_lanes": ["correctness", "quality", "adversarial"],
                }
            )
        )
        self.repo.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Test User")
        self.git("config", "user.email", "test@example.invalid")
        (self.repo / "file.txt").write_text("one\n")
        self.git("add", "file.txt")

    def tearDown(self) -> None:
        self.temp.cleanup()

    @property
    def env(self) -> dict[str, str]:
        return {**os.environ, "HOME": str(self.home)}

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=self.repo,
            env=self.env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )

    def helper(self, *args: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(HELPER), *args],
            cwd=self.repo,
            env={**self.env, **(env_extra or {})},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def tree(self) -> str:
        return self.git("write-tree").stdout.strip()

    def state_dir(self) -> Path:
        repo_root = self.git("rev-parse", "--show-toplevel").stdout.strip()
        repo_id = hashlib.sha256(repo_root.encode()).hexdigest()
        return self.home / ".cache" / "scg-agent-git-hooks" / "reviews" / repo_id

    def approve(self) -> subprocess.CompletedProcess[str]:
        return self.helper("approve", "--decision", "ALL_CLEAR", *LANE_ARGS)

    def test_pass_parsing_rejects_missing_duplicate_unknown_and_empty_models(self) -> None:
        cases = [
            (["--pass", "correctness=m", "--pass", "quality=m"], "Missing --pass"),
            (
                [*LANE_ARGS, "--pass", "correctness=other"],
                "Duplicate --pass",
            ),
            (
                [*LANE_ARGS, "--pass", "security=m"],
                "Unknown review lane",
            ),
            (
                [
                    "--pass",
                    "correctness=",
                    "--pass",
                    "quality=m",
                    "--pass",
                    "adversarial=m",
                ],
                "both be non-empty",
            ),
        ]
        for args, expected in cases:
            with self.subTest(expected=expected):
                result = self.helper("approve", *args)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stderr)

    def test_neutral_state_creation_records_chosen_models(self) -> None:
        result = self.helper(
            "approve",
            "--decision",
            "PROCEED_WITH_NOTES",
            "--runner",
            "local-cli",
            "--agent",
            "main-agent",
            *LANE_ARGS,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        path = self.state_dir() / f"{self.tree()}.review.json"
        self.assertTrue(path.exists())
        state = json.loads(path.read_text())
        self.assertEqual(state["version"], 2)
        self.assertNotIn("surface", state)
        self.assertEqual(
            state["passes"],
            {
                "correctness": "model-c",
                "quality": "model-q",
                "adversarial": "model-a",
            },
        )
        self.assertEqual(state["runner"], "local-cli")
        self.assertEqual(state["agent"], "main-agent")

    def test_old_surface_state_does_not_satisfy_gate(self) -> None:
        root = self.state_dir()
        root.mkdir(parents=True)
        legacy = root / f"{self.tree()}.codex.json"
        legacy.write_text(json.dumps({"version": 1, "approved": True}))
        result = self.helper("pre-commit")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SCG pre-commit hook blocked", result.stderr)

    def test_staged_tree_change_rejects_previous_approval(self) -> None:
        self.assertEqual(self.approve().returncode, 0)
        (self.repo / "file.txt").write_text("two\n")
        self.git("add", "file.txt")
        result = self.helper("pre-commit")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SCG pre-commit hook blocked", result.stderr)

    def test_expired_state_is_rejected(self) -> None:
        self.assertEqual(self.approve().returncode, 0)
        path = self.state_dir() / f"{self.tree()}.review.json"
        state = json.loads(path.read_text())
        state["created_at_epoch"] = int(time.time()) - 86401
        path.write_text(json.dumps(state))
        result = self.helper("pre-commit")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("review state expired", result.stderr)

    def test_pre_commit_accepts_valid_neutral_state(self) -> None:
        approval = self.approve()
        self.assertEqual(approval.returncode, 0, approval.stderr)
        result = self.helper("pre-commit")
        self.assertEqual(result.returncode, 0, result.stderr)

    def write_fake_scanner(self, version: str = "9.9.9", exit_code: int = 0) -> Path:
        scanner = self.home / "bin" / "fake-gitleaks"
        scanner.parent.mkdir(parents=True, exist_ok=True)
        scanner.write_text(
            "#!/bin/sh\n"
            f'if [ "$1" = "version" ]; then echo "{version}"; exit 0; fi\n'
            'echo "fake scan $*"\n'
            f"exit {exit_code}\n"
        )
        scanner.chmod(0o755)
        return scanner

    def pin_scanner(self, scanner: Path, *, version: str = "9.9.9", sha256: str | None = None) -> None:
        config_path = self.home / ".config" / "scg-agent-git-hooks" / "config.json"
        config = json.loads(config_path.read_text())
        config["gitleaks"] = {
            "binary": str(scanner),
            "version": version,
            "sha256": sha256 or hashlib.sha256(scanner.read_bytes()).hexdigest(),
            "timeout_seconds": 10,
        }
        config_path.write_text(json.dumps(config))

    def test_scan_passes_with_pinned_clean_scanner(self) -> None:
        scanner = self.write_fake_scanner()
        self.pin_scanner(scanner)
        result = self.helper("scan")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SCG secret scan passed", result.stdout)
        self.assertIn(self.tree(), result.stdout)

    def test_scan_blocks_without_pin(self) -> None:
        result = self.helper("scan")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must define a gitleaks pin", result.stderr)

    def test_scan_blocks_on_drift_external_config_and_leaks(self) -> None:
        scanner = self.write_fake_scanner()
        self.pin_scanner(scanner)
        good_sha = hashlib.sha256(scanner.read_bytes()).hexdigest()

        with self.subTest("sha mismatch"):
            self.pin_scanner(scanner, sha256="0" * 64)
            result = self.helper("scan")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("does not match the pinned", result.stderr)
            self.pin_scanner(scanner, sha256=good_sha)

        with self.subTest("version mismatch"):
            self.pin_scanner(scanner, version="1.0.0", sha256=good_sha)
            result = self.helper("scan")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("reports version", result.stderr)
            self.pin_scanner(scanner, sha256=good_sha)

        with self.subTest("env config"):
            result = self.helper("scan", env_extra={"GITLEAKS_CONFIG": "/tmp/x.toml"})
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("GITLEAKS_CONFIG is set", result.stderr)

        with self.subTest("repo config file"):
            (self.repo / ".gitleaks.toml").write_text("[allowlist]\n")
            result = self.helper("scan")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("repository supplies .gitleaks.toml", result.stderr)
            (self.repo / ".gitleaks.toml").unlink()

        with self.subTest("missing binary"):
            self.pin_scanner(scanner, sha256=good_sha)
            scanner.rename(scanner.with_name("moved"))
            result = self.helper("scan")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing or not executable", result.stderr)
            scanner.with_name("moved").rename(scanner)

        with self.subTest("leak exit code"):
            leaky = self.write_fake_scanner(exit_code=1)
            self.pin_scanner(leaky)
            result = self.helper("scan")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("found leaks or failed", result.stderr)


if __name__ == "__main__":
    unittest.main()
