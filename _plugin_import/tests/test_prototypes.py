import importlib.util
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "plugins/scg-prototypes/skills/publish-prototype/scripts/prototypes.py"
spec = importlib.util.spec_from_file_location("scg_prototypes", SCRIPT)
prototypes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prototypes)

CONFIG = {
    "account": "852138521410",
    "archiveRepository": "software-combined/SC_Prototypes",
    "bucket": "scg-prototypes-852138521410",
    "distributionId": "E1234567890ABC",
    "domain": "prototypes.softwarecombined.com",
    "expiryDays": 30,
    "profile": "scg-prototypes",
}


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


class PrototypeTest(unittest.TestCase):
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

    def test_slug_rules_are_enforced(self):
        prototypes.validate_slug("checkout-v2-7f3a")
        for invalid in ["Checkout", "ab", "-leading", "trailing-", "with_underscore", "x" * 41]:
            with self.assertRaises(prototypes.ChannelError, msg=invalid):
                prototypes.validate_slug(invalid)

    def test_generated_slug_keeps_a_readable_prefix_and_fits_the_limit(self):
        generated = prototypes.make_slug(self.site)
        self.assertTrue(generated.startswith("checkout-v2-"))
        self.assertEqual(len(generated), len("checkout-v2-") + 4)
        long_name = self.root / ("very-long-prototype-name-that-keeps-going" * 2)
        self.assertLessEqual(len(prototypes.make_slug(long_name)), 40)
        self.assertEqual(prototypes.make_slug(self.site, "exact-name"), "exact-name")

    def test_root_absolute_references_are_reported_per_file_and_line(self):
        self.assertEqual(prototypes.find_root_absolute_refs(self.site, "checkout-v2-7f3a"), [])
        (self.site / "assets" / "app.css").write_text("body{background:url(/images/bg.png)}\n")
        (self.site / "index.html").write_text(
            '<script src="/assets/app.js"></script>\n<img src="/checkout-v2-7f3a/assets/ok.png">\n',
        )
        findings = prototypes.find_root_absolute_refs(self.site, "checkout-v2-7f3a")
        self.assertEqual(findings, [
            "assets/app.css:1: /images/bg.png",
            "index.html:1: /assets/app.js",
        ])

    def test_srcset_and_import_references_are_checked_without_flagging_relative_paths(self):
        (self.site / "index.html").write_text(
            '<img srcset="img/hero.webp 1x, img/hero@2x.webp 2x">\n'
            '<img srcset="img/other.webp 1x, /rooted/other.webp 2x">\n'
            '<style>@import "styles/print.css";</style>\n'
            '<style>@import "/rooted/print.css";</style>\n',
        )
        findings = prototypes.find_root_absolute_refs(self.site, "checkout-v2-7f3a")
        self.assertEqual(findings, [
            "index.html:2: /rooted/other.webp",
            "index.html:4: /rooted/print.css",
        ])

    def test_gitleaks_gate_refuses_an_environment_supplied_config(self):
        with patch.dict(os.environ, {"GITLEAKS_CONFIG_TOML": "[allowlist]"}):
            with self.assertRaises(prototypes.ChannelError) as error:
                prototypes.gitleaks_binary()
        self.assertIn("GITLEAKS_CONFIG", str(error.exception))

    def test_gitleaks_gate_verifies_the_pinned_binary_hash(self):
        binary = self.root / "fake-gitleaks"
        binary.write_text("#!/bin/sh\n")
        prototypes.GITLEAKS_PIN_PATH.write_text(json.dumps({"gitleaks": {"binary": str(binary), "sha256": "0" * 64}}))
        with self.assertRaises(prototypes.ChannelError) as error:
            prototypes.gitleaks_binary()
        self.assertIn("SHA-256", str(error.exception))

        prototypes.GITLEAKS_PIN_PATH.write_text(json.dumps({
            "gitleaks": {"binary": str(binary), "sha256": hashlib.sha256(binary.read_bytes()).hexdigest()},
        }))
        self.assertEqual(prototypes.gitleaks_binary(), str(binary))

    def test_gitleaks_gate_requires_the_review_hook_pin(self):
        prototypes.GITLEAKS_PIN_PATH = self.root / "missing-hook-config.json"
        with self.assertRaises(prototypes.ChannelError) as error:
            prototypes.gitleaks_binary()
        self.assertIn("review-setup", str(error.exception))

    def test_publish_rolls_the_registry_back_when_the_sync_fails(self):
        def failing_sync(args, cwd=None):
            joined = " ".join(str(item) for item in args)
            if "sts" in args:
                return json.dumps({"Account": CONFIG["account"]})
            if "status" in args and "--porcelain" in args:
                return " M prototypes.json\n"
            if joined.startswith("aws s3 sync"):
                raise prototypes.ChannelError("simulated transient sync failure")
            return ""

        with self.assertRaises(prototypes.ChannelError):
            prototypes.publish(
                arguments(directory=str(self.site), slug="checkout-v2-7f3a", repo_dir=str(self.repo)),
                CONFIG,
                run=failing_sync,
                verifier=lambda url: "",
                out=lambda _line: None,
            )
        self.assertNotIn("checkout-v2-7f3a", prototypes.load_registry(self.repo)["prototypes"])

    def test_publish_refuses_a_dirty_archive_clone_before_any_s3_call(self):
        runner = RecordingRunner(status=" M prototypes.json\n?? notes.md\n")
        with self.assertRaises(prototypes.ChannelError) as error:
            prototypes.publish(
                arguments(directory=str(self.site), slug="checkout-v2-7f3a", repo_dir=str(self.repo)),
                CONFIG,
                run=runner,
                verifier=lambda url: "",
                out=lambda _line: None,
            )
        self.assertIn("unrelated changes", str(error.exception))
        self.assertFalse(any(command[:2] == ["aws", "s3"] or command[:2] == ["aws", "cloudfront"] for command in runner.commands))

    def test_publish_refuses_symbolic_links_that_reach_outside_the_prototype(self):
        outside = self.root / "private-notes.txt"
        outside.write_text("do not publish me\n")
        (self.site / "linked.txt").symlink_to(outside)
        self.assertEqual(prototypes.find_symlinks(self.site), ["linked.txt"])
        with self.assertRaises(prototypes.ChannelError) as error:
            prototypes.publish(
                arguments(directory=str(self.site), slug="checkout-v2-7f3a", repo_dir=str(self.repo)),
                CONFIG,
                run=RecordingRunner(),
            )
        self.assertIn("symbolic links are not published", str(error.exception))
        self.assertFalse((self.repo / "prototypes.json").exists())

    def test_registry_entry_records_the_public_url_and_expiry(self):
        published_at = datetime(2026, 9, 12, 10, 30, tzinfo=timezone.utc)
        entry = prototypes.entry_for("checkout-v2-7f3a", "Checkout v2", CONFIG, published_at, "brent")
        self.assertEqual(entry["url"], "https://prototypes.softwarecombined.com/checkout-v2-7f3a/")
        self.assertEqual(entry["expiresAt"], (published_at + timedelta(days=30)).isoformat(timespec="seconds"))
        registry = {"prototypes": {"checkout-v2-7f3a": entry}}
        prototypes.save_registry(self.repo, registry)
        self.assertEqual(prototypes.load_registry(self.repo), registry)
        self.assertEqual(prototypes.load_registry(self.root / "missing"), {"prototypes": {}})

    def test_publish_dry_run_reports_the_plan_without_writing_anything(self):
        runner = RecordingRunner()
        printed = []
        result = prototypes.publish(
            arguments(directory=str(self.site), slug="checkout-v2-7f3a", dry_run=True, repo_dir=str(self.repo)),
            CONFIG,
            run=runner,
            out=printed.append,
        )
        self.assertTrue(result["dryRun"])
        self.assertTrue(all("detect" in command for command in runner.commands), runner.joined())
        self.assertIn("https://prototypes.softwarecombined.com/checkout-v2-7f3a/", " ".join(printed))
        self.assertFalse((self.repo / "prototypes").exists())
        self.assertFalse((self.repo / "prototypes.json").exists())

    def test_publish_archives_the_site_then_syncs_and_invalidates(self):
        runner = RecordingRunner()
        printed = []
        result = prototypes.publish(
            arguments(directory=str(self.site), slug="checkout-v2-7f3a", title="Checkout v2", repo_dir=str(self.repo)),
            CONFIG,
            run=runner,
            verifier=lambda url: "",
            out=printed.append,
        )
        archived = self.repo / "prototypes" / "checkout-v2-7f3a" / "site"
        self.assertTrue((archived / "index.html").is_file())
        self.assertTrue((archived / "assets" / "app.css").is_file())
        self.assertEqual(result["url"], "https://prototypes.softwarecombined.com/checkout-v2-7f3a/")
        registry = json.loads((self.repo / "prototypes.json").read_text())
        self.assertEqual(registry["prototypes"]["checkout-v2-7f3a"]["title"], "Checkout v2")
        commands = runner.joined()
        self.assertTrue(any(command.startswith("git -C") and "commit" in command for command in commands))
        self.assertTrue(any(command.startswith("aws s3 rm --recursive s3://scg-prototypes-852138521410/prototypes/checkout-v2-7f3a/") for command in commands))
        self.assertTrue(any("cloudfront create-invalidation" in command and "/checkout-v2-7f3a/*" in command for command in commands))
        self.assertIn("Published https://prototypes.softwarecombined.com/checkout-v2-7f3a/", printed[-1])

    def test_publish_refuses_an_existing_slug_unless_update_is_requested(self):
        prototypes.save_registry(self.repo, {"prototypes": {"checkout-v2-7f3a": prototypes.entry_for(
            "checkout-v2-7f3a", "Checkout v2", CONFIG, datetime.now(timezone.utc), "brent",
        )}})
        with self.assertRaises(prototypes.ChannelError) as error:
            prototypes.publish(
                arguments(directory=str(self.site), slug="checkout-v2-7f3a", repo_dir=str(self.repo)),
                CONFIG,
                run=RecordingRunner(),
                verifier=lambda url: "",
            )
        self.assertIn("already published", str(error.exception))

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
        subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)
        subprocess.run(["git", "config", "user.email", "publisher@example.com"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "Publisher"], cwd=self.repo, check=True)
        (self.repo / "prototypes.json").write_text('{\n  "prototypes": {}\n}\n')
        subprocess.run(["git", "add", "prototypes.json"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "chore: init"], cwd=self.repo, check=True)
        subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=self.repo, check=True)
        subprocess.run(["git", "push", "-qu", "origin", "main"], cwd=self.repo, check=True)

        def runner(args, cwd=None):
            joined = " ".join(str(item) for item in args)
            if args[0] == "aws" and "sts" in args:
                return json.dumps({"Account": CONFIG["account"]})
            if args[0] == "aws" or "detect" in args:
                return ""
            return prototypes.run_command(args, cwd=cwd)

        prototypes.publish(
            arguments(directory=str(self.site), slug="checkout-v2-7f3a", title="Checkout v2", repo_dir=str(self.repo)),
            CONFIG,
            run=runner,
            verifier=lambda url: "",
            out=lambda _line: None,
        )
        self.assertTrue((self.repo / "prototypes" / "checkout-v2-7f3a" / "site" / "index.html").is_file())
        log = subprocess.run(["git", "log", "--oneline"], cwd=self.repo, capture_output=True, text=True, check=True).stdout
        self.assertIn("publish prototype checkout-v2-7f3a", log)
        pushed = subprocess.run(["git", "log", "--oneline", "main"], cwd=remote, capture_output=True, text=True, check=True).stdout
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

    def test_marketplace_entry_and_skill_links_resolve_inside_the_plugin(self):
        plugin = ROOT / "plugins/scg-prototypes"
        marketplace = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text())
        entries = {entry["name"]: entry for entry in marketplace["plugins"]}
        self.assertIn("scg-prototypes", entries)
        self.assertEqual((ROOT / entries["scg-prototypes"]["source"]["path"]).resolve(), plugin)
        manifest = json.loads((plugin / ".codex-plugin/plugin.json").read_text())
        self.assertEqual(manifest["name"], "scg-prototypes")
        self.assertEqual(manifest["repository"], "https://github.com/software-combined/SC_Agent_plugins")
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+(?:\+[A-Za-z0-9.-]+)?$")
        self.assertTrue((plugin / "skills/publish-prototype/SKILL.md").is_file())
        for markdown in (plugin / "skills").glob("*/SKILL.md"):
            for target in re.findall(r"\]\(([^)]+)\)", markdown.read_text()):
                path = target.split("#")[0]
                if path and "://" not in path:
                    resolved = (markdown.parent / path).resolve()
                    self.assertTrue(resolved.is_relative_to(plugin), target)
                    self.assertTrue(resolved.is_file(), target)

    def test_channel_config_matches_the_deployed_channel_contract(self):
        config = json.loads((ROOT / "plugins/scg-prototypes/skills/publish-prototype/references/channel.json").read_text())
        self.assertEqual(config["account"], "852138521410")
        self.assertEqual(config["bucket"], "scg-prototypes-852138521410")
        self.assertEqual(config["domain"], "prototypes.softwarecombined.com")
        self.assertEqual(config["archiveRepository"], "software-combined/SC_Prototypes")
        self.assertEqual(config["expiryDays"], 30)
        self.assertEqual(config["profile"], "scg-prototypes")
        self.assertTrue(
            config["distributionId"] == "" or re.fullmatch(r"E[A-Z0-9]+", config["distributionId"]),
        )

    def test_unpublish_dry_run_keeps_the_archive_and_registry(self):
        prototypes.save_registry(self.repo, {"prototypes": {"checkout-v2-7f3a": prototypes.entry_for(
            "checkout-v2-7f3a", "Checkout v2", CONFIG, datetime.now(timezone.utc), "brent",
        )}})
        printed = []
        prototypes.unpublish(
            arguments(slug="checkout-v2-7f3a", repo_dir=str(self.repo), dry_run=True),
            CONFIG,
            run=RecordingRunner(),
            out=printed.append,
        )
        self.assertIn("checkout-v2-7f3a", printed[0])
        self.assertIn("checkout-v2-7f3a", prototypes.load_registry(self.repo)["prototypes"])

    def test_unpublish_deletes_only_the_slug_prefix_and_keeps_the_archive(self):
        prototypes.save_registry(self.repo, {"prototypes": {"checkout-v2-7f3a": prototypes.entry_for(
            "checkout-v2-7f3a", "Checkout v2", CONFIG, datetime.now(timezone.utc), "brent",
        )}})
        archive = self.repo / "prototypes" / "checkout-v2-7f3a" / "site"
        archive.mkdir(parents=True)
        (archive / "index.html").write_text("archived\n")

        runner = RecordingRunner()
        prototypes.unpublish(
            arguments(slug="checkout-v2-7f3a", repo_dir=str(self.repo), dry_run=False),
            CONFIG,
            run=runner,
            out=lambda _line: None,
        )
        commands = runner.joined()
        delete_index = next(index for index, command in enumerate(commands) if command.startswith(
            "aws s3 rm --recursive s3://scg-prototypes-852138521410/prototypes/checkout-v2-7f3a/",
        ))
        invalidation_index = next(index for index, command in enumerate(commands) if "create-invalidation" in command and "/checkout-v2-7f3a/*" in command)
        push_index = next(index for index, command in enumerate(commands) if command.endswith("push") and "git -C" in command)
        self.assertLess(delete_index, push_index)
        self.assertLess(invalidation_index, push_index)
        self.assertTrue((archive / "index.html").is_file(), "the archived source survives an unpublish")
        self.assertNotIn("checkout-v2-7f3a", prototypes.load_registry(self.repo)["prototypes"])
        self.assertFalse(any("--all" in command for command in commands))

    def test_list_reports_expired_entries(self):
        moment = datetime(2026, 9, 12, tzinfo=timezone.utc)
        prototypes.save_registry(self.repo, {"prototypes": {
            "fresh-0001": prototypes.entry_for("fresh-0001", "Fresh", CONFIG, moment, "brent"),
            "stale-0001": prototypes.entry_for("stale-0001", "Stale", CONFIG, moment - timedelta(days=40), "brent"),
        }})
        printed = []
        rows = prototypes.list_prototypes(arguments(repo_dir=str(self.repo)), CONFIG, out=printed.append, now=moment)
        statuses = {row["slug"]: row["status"] for row in rows}
        self.assertEqual(statuses, {"fresh-0001": "active", "stale-0001": "expired"})
        self.assertTrue(any("stale-0001" in line and "expired" in line for line in printed))


if __name__ == "__main__":
    unittest.main()
