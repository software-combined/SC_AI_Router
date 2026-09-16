"""Prototypes plugin failure paths and real-clone checks."""
import importlib.util
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

# POSIX fcntl locks the registry in the publish script; it cannot import on
# Windows. The publish path runs on macOS/Linux release hosts. Import it only
# on POSIX; on Windows the classes below are skipped via the ``load_tests``
# hook, so the fcntl-dependent script is never touched. A module-level
# ``raise SkipTest`` would surface as a collection ERROR, not a clean skip.
ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "plugins/scg-prototypes/skills/publish-prototype/scripts/prototypes.py"
if os.name == 'nt':
    prototypes = None
else:
    spec = importlib.util.spec_from_file_location("scg_prototypes", SCRIPT)
    prototypes = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prototypes)


def load_tests(loader, tests, pattern):
    """Skip this module cleanly on Windows (see the note above)."""
    if os.name == 'nt':
        return unittest.TestSuite()
    return tests

CONFIG = {
    "account": "852138521410",
    "archiveRepository": "software-combined/SC_Prototypes",
    "bucket": "scg-prototypes-852138521410",
    "distributionId": "E1234567890ABC",
    "domain": "prototypes.softwarecombined.com",
    "expiryDays": 30,
    "profile": "scg-prototypes",
}


ISOLATED_GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


class RecordingRunner:
    def __init__(self, status=" M prototypes.json\n"):
        self.commands = []
        self.status = status

    def __call__(self, args, cwd=None):
        self.commands.append([str(item) for item in args])
        if "sts" in args:
            return json.dumps({"Account": CONFIG["account"]})
        if "status" in args and "--porcelain" in args:
            return self.status
        return ""

    def joined(self):
        return [" ".join(command) for command in self.commands]


def arguments(**overrides):
    values = {
        "directory": None,
        "dry_run": False,
        "repo_dir": None,
        "slug": None,
        "source": None,
        "title": None,
        "update": False,
    }
    values.update(overrides)
    return Namespace(**values)


class PrototypeOpsTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.site = self.root / "checkout-v2"
        (self.site / "assets").mkdir(parents=True)
        (self.site / "index.html").write_text('<!doctype html><link rel="stylesheet" href="assets/app.css"><h1>checkout</h1>\n')
        (self.site / "assets" / "app.css").write_text("body{color:#111}\n")
        self.repo = self.root / "SC_Prototypes"
        (self.repo / ".git").mkdir(parents=True)
        self.previous_pin_path = prototypes.GITLEAKS_PIN_PATH
        prototypes.GITLEAKS_PIN_PATH = self.root / "hook-config.json"
        prototypes.GITLEAKS_PIN_PATH.write_text(json.dumps({
            "gitleaks": {"binary": sys.executable, "sha256": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()},
        }))
        self.addCleanup(self.restore_pin_path)

    def restore_pin_path(self):
        prototypes.GITLEAKS_PIN_PATH = self.previous_pin_path

    def test_publish_requires_a_built_index(self):
        empty = self.root / "empty"
        empty.mkdir()
        with self.assertRaises(prototypes.ChannelError) as error:
            prototypes.publish(arguments(directory=str(empty), slug="empty-1234", repo_dir=str(self.repo)), CONFIG, run=RecordingRunner())
        self.assertIn("no index.html", str(error.exception))

    def test_publish_stops_before_any_write_when_the_profile_is_the_wrong_account(self):
        def wrong_account(args, cwd=None):
            if "sts" in args:
                return json.dumps({"Account": "111122223333"})
            return ""

        with self.assertRaises(prototypes.ChannelError) as error:
            prototypes.publish(
                arguments(directory=str(self.site), slug="checkout-v2-7f3a", repo_dir=str(self.repo)),
                CONFIG,
                run=wrong_account,
                verifier=lambda url: "",
            )
        self.assertIn("expected 852138521410", str(error.exception))
        self.assertFalse((self.repo / "prototypes.json").exists())
        self.assertFalse((self.repo / "prototypes").exists())

    def test_publish_rechecks_the_copied_artifact_for_symlinks(self):
        def injecting_runner(args, cwd=None):
            if "sts" in args:
                (self.site / "late-link.txt").symlink_to("/etc/hostname")
                return json.dumps({"Account": CONFIG["account"]})
            return ""

        with self.assertRaises(prototypes.ChannelError) as error:
            prototypes.publish(
                arguments(directory=str(self.site), slug="checkout-v2-7f3a", repo_dir=str(self.repo)),
                CONFIG,
                run=injecting_runner,
                verifier=lambda url: "",
            )
        self.assertIn("copied artifact failed the publish checks", str(error.exception))
        self.assertFalse((self.repo / "prototypes.json").exists())
        self.assertFalse(
            (self.repo / "prototypes" / "checkout-v2-7f3a").exists(),
            "a failed copy leaves no residue to block later publishes",
        )

    def test_publish_works_in_a_real_clone_without_a_tracked_prototypes_directory(self):
        remote = self.root / "archive-remote.git"
        git_env = {**os.environ, **ISOLATED_GIT_ENV}
        subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True, env=git_env)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True, env=git_env)
        subprocess.run(["git", "config", "user.email", "publisher@example.com"], cwd=self.repo, check=True, env=git_env)
        subprocess.run(["git", "config", "user.name", "Publisher"], cwd=self.repo, check=True, env=git_env)
        (self.repo / "prototypes.json").write_text('{\n  "prototypes": {}\n}\n')
        subprocess.run(["git", "add", "prototypes.json"], cwd=self.repo, check=True, env=git_env)
        subprocess.run(["git", "commit", "-qm", "chore: init"], cwd=self.repo, check=True, env=git_env)
        subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=self.repo, check=True, env=git_env)
        subprocess.run(["git", "push", "-qu", "origin", "main"], cwd=self.repo, check=True, env=git_env)

        def runner(args, cwd=None):
            joined = " ".join(str(item) for item in args)
            if args[0] == "aws" and "sts" in args:
                return json.dumps({"Account": CONFIG["account"]})
            if args[0] == "aws" or "detect" in args:
                return ""
            if args[0] == "git":
                result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, env=git_env)
                if result.returncode != 0:
                    detail = (result.stderr or result.stdout).strip()
                    raise prototypes.ChannelError(f"command failed ({' '.join(args)}): {detail}")
                return result.stdout
            return prototypes.run_command(args, cwd=cwd)

        prototypes.publish(
            arguments(directory=str(self.site), slug="checkout-v2-7f3a", title="Checkout v2", repo_dir=str(self.repo)),
            CONFIG,
            run=runner,
            verifier=lambda url: "",
            out=lambda _line: None,
        )
        self.assertTrue((self.repo / "prototypes" / "checkout-v2-7f3a" / "site" / "index.html").is_file())
        log = subprocess.run(["git", "log", "--oneline"], cwd=self.repo, capture_output=True, text=True, check=True, env=git_env).stdout
        self.assertIn("publish prototype checkout-v2-7f3a", log)
        pushed = subprocess.run(["git", "log", "--oneline", "main"], cwd=remote, capture_output=True, text=True, check=True, env=git_env).stdout
        self.assertIn("publish prototype checkout-v2-7f3a", pushed)

    def test_publish_scans_the_source_snapshot_before_archiving_it(self):
        project = self.root / "project"
        project.mkdir()
        (project / "main.js").write_text("console.log('hi')\n")
        runner = RecordingRunner()
        prototypes.publish(
            arguments(directory=str(self.site), slug="checkout-v2-7f3a", source=str(project), repo_dir=str(self.repo)),
            CONFIG,
            run=runner,
            verifier=lambda url: "",
            out=lambda _line: None,
        )
        scans = [command for command in runner.commands if "detect" in command]
        self.assertEqual(len(scans), 3, "build output, source snapshot and the archived copy are all scanned")
        self.assertIn(str(project), " ".join(scans[1]))
        self.assertTrue((self.repo / "prototypes" / "checkout-v2-7f3a" / "source" / "main.js").is_file())

    def test_dry_run_does_not_clone_the_archive_repository(self):
        missing_repo = self.root / "never-cloned"
        runner = RecordingRunner()
        prototypes.publish(
            arguments(directory=str(self.site), slug="checkout-v2-7f3a", dry_run=True, repo_dir=str(missing_repo)),
            CONFIG,
            run=runner,
            out=lambda _line: None,
        )
        self.assertFalse(any("clone" in " ".join(command) for command in runner.commands))
        self.assertFalse(missing_repo.exists())

    def test_live_verification_rejects_a_redirected_url(self):
        class RedirectedResponse:
            status = 200
            headers = {"Content-Type": "text/html", "X-Robots-Tag": "noindex, nofollow"}

            def geturl(self):
                return "https://elsewhere.example/prototype/"

            def read(self, _size):
                return b"<h1>elsewhere</h1>"

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        with patch("urllib.request.urlopen", return_value=RedirectedResponse()):
            reason = prototypes.verify_live("https://prototypes.softwarecombined.com/checkout-v2-7f3a/", attempts=1, delay=0)
        self.assertIn("redirected", reason)

    def test_publish_stops_before_writing_when_gitleaks_fails(self):
        def failing_runner(args, cwd=None):
            if "detect" in args:
                raise prototypes.ChannelError("leak detected")
            return ""

        with self.assertRaises(prototypes.ChannelError) as error:
            prototypes.publish(
                arguments(directory=str(self.site), slug="checkout-v2-7f3a", repo_dir=str(self.repo)),
                CONFIG,
                run=failing_runner,
            )
        self.assertIn("potential secret", str(error.exception))
        self.assertFalse((self.repo / "prototypes.json").exists())

    def test_publish_refuses_a_repository_supplied_scanner_config(self):
        (self.site / ".gitleaks.toml").write_text("[allowlist]\n")
        with self.assertRaises(prototypes.ChannelError) as error:
            prototypes.publish(
                arguments(directory=str(self.site), slug="checkout-v2-7f3a", repo_dir=str(self.repo)),
                CONFIG,
                run=RecordingRunner(),
            )
        self.assertIn(".gitleaks.toml", str(error.exception))

    def test_channel_config_must_be_deployed_before_publishing(self):
        config_file = self.root / "channel.json"
        config_file.write_text(json.dumps({**CONFIG, "distributionId": ""}))
        with self.assertRaises(prototypes.ChannelError) as error:
            prototypes.load_config(config_file)
        self.assertIn("not deployed yet", str(error.exception))


if __name__ == "__main__":
    unittest.main()
